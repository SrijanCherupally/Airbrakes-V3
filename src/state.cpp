#include "state.h"

#include <stdarg.h>

#include "config.h"

volatile State currentState = STATE_IDLE;

/*
Color codes:
  IDLE: Blue to Green over 10s
  PAD: Solid Green (dim)
  BOOST: Solid Red
  CONTROL: Solid Yellow
  DESCENT: Solid White
  LANDED: Solid Purple
*/

uint32_t lastNonIdleTime = 0;

// Ground test is opt-in through the serial protocol. It never enters the
// normal BOOST/CONTROL/DESCENT states, so it cannot run flight control.
static uint32_t groundTestStartMs = 0;
static uint32_t groundTestLastSweepMs = 0;
static float groundTestTarget = MOTOR_MIN;
static bool groundTestOpening = true;
static bool groundTestSweepStopped = false;
static bool groundTestClosing = false;

// A single projected-acceleration sample can briefly be negative during boost
// as the vehicle tilts or vibrates. Require a persistent deceleration before
// declaring coast, because that transition enables airbrake control and later
// permits barometer aiding.
static uint32_t boostDecelerationStartMs = 0;
static constexpr uint32_t BOOST_TO_CONTROL_CONFIRM_MS = 250;
static uint32_t launchStartMs = 0;

const char* stateName(State state) {
  static const char* const names[] = {"IDLE", "PAD", "BOOST", "CONTROL",
                                      "DESCENT", "LANDED", "GROUND_TEST_ARMED",
                                      "GROUND_TEST_RECORDING"};
  return state <= STATE_GROUND_TEST_RECORDING ? names[state] : "UNKNOWN";
}

bool startGroundTest() {
  // The automatic state machine normally transitions from IDLE to PAD after
  // its stationary calibration. PAD is still a safe, pre-launch state and
  // must be accepted here; rejecting it produced the misleading combined
  // "heartbeat/error/state not ready" message.
  if ((currentState != STATE_IDLE && currentState != STATE_PAD) ||
      axisError != 0) {
    return false;
  }

  // Heartbeat freshness is intentionally disabled. Ask the ODrive to enter
  // closed loop now; serviceOdrive() will retry the request while the test is
  // armed, and the first position command is gated by the reported axis state.
  serviceOdrive();
  odrv.clearErrors();
  odrv.setState(ODriveAxisState::AXIS_STATE_CLOSED_LOOP_CONTROL);
  initFlash();
  currentState = STATE_GROUND_TEST_ARMED;
  groundTestStartMs = 0;
  groundTestTarget = MOTOR_MIN;
  groundTestOpening = true;
  groundTestSweepStopped = false;
  groundTestClosing = false;
  // Use one target command per phase. The ODrive performs the motion using
  // its configured controller rather than being chased by 100 ms setpoints.
  odrv.setLimits(GROUND_TEST_VELOCITY_LIMIT, GROUND_TEST_CURRENT_LIMIT_A);
  // Do not send an extra closed command here. The mechanism is already held
  // closed before the test; the test itself should be one open-then-close
  // cycle, not close -> open -> close.
  Serial.println("GROUND_TEST:ARMED");
  return true;
}

void abortGroundTest() {
  if (currentState == STATE_GROUND_TEST_ARMED ||
      currentState == STATE_GROUND_TEST_RECORDING) {
    odrvPosition(MOTOR_MIN);
    // Stop the producer before flushing/closing its queue. One estimator pass
    // can already be in flight on core 1, so give it one 1 kHz period to
    // observe the state change before the file is closed.
    currentState = STATE_IDLE;
    delay(3);
    finalizeFlightLog();
    lastNonIdleTime = millis();
  }
}

static void groundTestSweepUpdate() {
  if (groundTestSweepStopped) return;

  if (odriveCurrentLimitExceeded()) {
    odrvPosition(MOTOR_MIN);
    groundTestSweepStopped = true;
    Serial.println("GROUND_TEST:CURRENT_LIMIT: sweep stopped and brakes closed");
    return;
  }

  // One command opens fully. Do not generate intermediate targets.
  if (groundTestOpening) {
    if (groundTestTarget != MOTOR_MAX) {
      groundTestTarget = MOTOR_MAX;
      groundTestLastSweepMs = millis();
      odrvPosition(MOTOR_MAX);
      Serial.println("GROUND_TEST:OPEN_COMMANDED: target=-42 velocity_limit=50");
      return;
    }

    // Once open feedback arrives, or after the safety timeout, issue the one
    // close command and remain in the closing phase.
    if (fabsf(motorpos - MOTOR_MAX) <= GROUND_TEST_POSITION_TOLERANCE ||
        (uint32_t)(millis() - groundTestLastSweepMs) >= GROUND_TEST_OPEN_TIMEOUT_MS) {
      groundTestOpening = false;
      groundTestClosing = true;
      groundTestTarget = MOTOR_MIN;
      odrvPosition(MOTOR_MIN);
      Serial.println("GROUND_TEST:OPEN_REACHED_OR_TIMEOUT: target=0");
    }
    return;
  }

  if (groundTestClosing &&
      fabsf(motorpos - MOTOR_MIN) <= GROUND_TEST_POSITION_TOLERANCE) {
    groundTestClosing = false;
    groundTestSweepStopped = true;
    Serial.println("GROUND_TEST:CLOSED_ENDPOINT_REACHED");
  }
}

// Launch tracking in PAD: arm early and recover pre-roll dv before BOOST.
constexpr uint32_t PAD_LAUNCH_WINDOW_MS = 100;
constexpr uint32_t PAD_LAUNCH_CHECK_DELAY_MS = 50;
constexpr float PAD_LAUNCH_ARM_ACCEL = 11.5f;  // accel magnitude (includes 1g)
constexpr int PAD_PREROLL_SAMPLES = 300;       // 0.30 s at 1 kHz
constexpr float PAD_LOOP_DT = 1.0f / 1000.0f;

float padPrerollAccel[PAD_PREROLL_SAMPLES];
int padPrerollHead = 0;
int padPrerollCount = 0;

static void resetPadLaunchTracking() {
  padPrerollHead = 0;
  padPrerollCount = 0;
  for (int i = 0; i < PAD_PREROLL_SAMPLES; ++i) {
    padPrerollAccel[i] = 0.0f;
  }
}

static void pushPadPreroll(float accelMag) {
  // Convert accel magnitude to approximate specific force ahead of launch.
  float specific = accelMag - G;
  if (specific > 120.0f) {
    specific = 120.0f;
  }
  if (specific < -20.0f) {
    specific = -20.0f;
  }

  padPrerollAccel[padPrerollHead] = specific;
  padPrerollHead = (padPrerollHead + 1) % PAD_PREROLL_SAMPLES;
  if (padPrerollCount < PAD_PREROLL_SAMPLES) {
    padPrerollCount++;
  }
}

static float computePadPrerollDv() {
  float dv = 0.0f;
  for (int i = 0; i < padPrerollCount; ++i) {
    int idx =
        (padPrerollHead - 1 - i + PAD_PREROLL_SAMPLES) % PAD_PREROLL_SAMPLES;
    if (padPrerollAccel[idx] > 0.0f) {
      dv += padPrerollAccel[idx] * PAD_LOOP_DT;
    }
  }
  return dv;
}

void stateUpdate() {
  float prog;
  switch (currentState) {
    case STATE_IDLE:
      // Estimator update handles it all, just show color
      prog = (millis() - lastNonIdleTime) / 10000.0f;
      if (prog > 1.0f) prog = 1.0f;
      if (checkStorageWarning()) {
        ledWrite(0.1f, 0.1f, 0.0f);  // Yellow warning
      } else {
        ledWrite(0.0f, prog, 1.0f - prog);  // Blue to Green (normal)
      }
      debugPrintf("STATE: IDLE\n");
      break;

    case STATE_PAD:
      if (millis() - lastNonIdleTime < PAD_LAUNCH_WINDOW_MS) {
        uint32_t launchElapsed = millis() - lastNonIdleTime;
        // During potential launch, fade to solid red
        prog = launchElapsed / (float)PAD_LAUNCH_WINDOW_MS;
        ledWrite(prog, 0.0f, 0.0f);
        debugPrintf("STATE: PAD (LAUNCH WINDOW)\n");
        // Check for launch after brief settle
        if (launchElapsed > PAD_LAUNCH_CHECK_DELAY_MS) {
          if (estVelocity() > LAUNCH_VEL && estAccel() > LAUNCH_ACCEL) {
            currentState = STATE_BOOST;
            launchStartMs = millis();
            boostDecelerationStartMs = 0;
            resetPadLaunchTracking();
          }
        }
        break;
      }
      // Indicate PAD state: blue when shaken (i.e. not stationary),
      // dim green otherwise.
      if (!biasActive) {
        ledWrite(0.0f, 0.0f, 0.5f);  // Shaken (blue)
      } else {
        ledWrite(0.0f, 0.1f, 0.0f);  // Dim green (calibrating/idle)
      }
      debugPrintf("STATE: PAD\n");
      break;

    case STATE_BOOST: {
      ledWrite(1.0f, 0.0f, 0.0f);  // Solid red
      debugPrintf("STATE: BOOST\n");

      // Flight 2 crossed the old instantaneous gate at 0.742 s and then
      // returned to positive acceleration, entering coast while powered.
      bool minimumBurnTimeElapsed =
          launchStartMs != 0 &&
          (uint32_t)(millis() - launchStartMs) >= MOTOR_MIN_BURN_TIME_MS;
      if (minimumBurnTimeElapsed && estVelocity() < VEL_CONTROL_START &&
          estAltitude() > ALT_LANDED &&
          estAccel() < 0.0f) {
        if (boostDecelerationStartMs == 0) {
          boostDecelerationStartMs = millis();
        } else if ((uint32_t)(millis() - boostDecelerationStartMs) >=
                   BOOST_TO_CONTROL_CONFIRM_MS) {
          currentState = STATE_CONTROL;
          boostDecelerationStartMs = 0;
        }
      } else {
        boostDecelerationStartMs = 0;
      }
      break;
    }

    case STATE_CONTROL:
      ledWrite(1.0f, 1.0f, 0.0f);  // Solid yellow
      debugPrintf("STATE: CONTROL\n");

      controlUpdate();

      // See if apogee reached
      if (estVelocity() < VEL_DESCENT) {
        currentState = STATE_DESCENT;
      }
      break;

    case STATE_DESCENT:
      ledWrite(1.0f, 1.0f, 1.0f);  // Solid white
      debugPrintf("STATE: DESCENT\n");
      odrvPosition(MOTOR_MIN);  // Closed

      // Do not let an inertial-only altitude error end a flight. Flight 2
      // reached this branch with a false -50 m/s velocity while the raw
      // pressure altitude still showed the rocket tens of metres aloft.
      // The pressure reference is independent of attitude and must agree
      // before closing the log.
      if (estAltitude() < ALT_LANDED && estRawBaro() < ALT_LANDED + 1.0f) {
        currentState = STATE_LANDED;
        // A landed flight is complete. Leaving the file open makes CURRENT
        // and DELETE treat it as an active log indefinitely.
        delay(3);
        finalizeFlightLog();
      }
      break;

    case STATE_LANDED:
      debugPrintf("STATE: LANDED\n");
      ledWrite(1.0f, 0.0f, 1.0f);  // Solid purple
      break;

    case STATE_GROUND_TEST_ARMED:
      // Cyan pulse: explicit test mode, waiting for a hand shake.
      ledWrite(0.0f, 0.25f, ((millis() / 250) & 1) ? 0.15f : 0.7f);
      debugPrintf("STATE: GROUND TEST ARMED\n");
      break;

    case STATE_GROUND_TEST_RECORDING:
      ledWrite(0.0f, 0.5f, 0.5f);  // Solid cyan while log is active.
      groundTestSweepUpdate();
      if ((uint32_t)(millis() - groundTestStartMs) >= GROUND_TEST_DURATION_MS) {
        odrvPosition(MOTOR_MIN);
        currentState = STATE_IDLE;
        delay(3);
        finalizeFlightLog();
        lastNonIdleTime = millis();
        Serial.println("GROUND_TEST:COMPLETE: log closed, brakes commanded closed");
      }
      break;
  }
}

void stateInit() {
  currentState = STATE_IDLE;
  lastNonIdleTime = millis();
  launchStartMs = 0;
  boostDecelerationStartMs = 0;
  resetPadLaunchTracking();
}

void estimatorUpdate() {
  switch (currentState) {
    case STATE_IDLE: {
      imu.update();
      // Keep hardware telemetry alive before the estimator enters PAD. This
      // also makes a disconnected barometer visible in logs/diagnostics.
      baro.update();
      float aZ = imu.getAccZ();  // Read Z accel (m/s^2)
      if (aZ < 9.0f || aZ > 11.0f) {
        // Movement, not idle
        lastNonIdleTime = millis();
      }

      if (millis() - lastNonIdleTime > 10000) {
        // Idle vertical for 10s, go to PAD state
        currentState = STATE_PAD;
        lastNonIdleTime = 0;  // Reset for bias calibration
        resetPadLaunchTracking();
      }
      break;
    }

    case STATE_PAD: {
      // Update filter during hypothetical launch window instead of bias
      // calibrating
      if (millis() - lastNonIdleTime < PAD_LAUNCH_WINDOW_MS) {
        filterUpdate();
        break;
      }

      // Calibrate bias (estimator updates PAD UI state internally)
      float acc = biasUpdate();
      pushPadPreroll(acc);

      if (acc > PAD_LAUNCH_ARM_ACCEL) {
        // Potential launch: start launch window and seed missing pre-roll dv.
        lastNonIdleTime = millis();
        filterReset();
        float dv = computePadPrerollDv();
        estimatorInjectVelocity(dv);
        debugPrintf("PAD preroll dv injected: %.4f m/s\n", dv);
      }
      break;
    }

    case STATE_BOOST:
    case STATE_CONTROL:
    case STATE_DESCENT:
      filterUpdate();
      break;

    case STATE_LANDED:
      // Nothing
      break;

    case STATE_GROUND_TEST_ARMED: {
      // Keep calibrating while armed. This state can be entered directly from
      // IDLE, bypassing PAD's normal stationary-bias calibration.
      float accelMag = biasUpdate();
      if (accelMag >= GROUND_TEST_SHAKE_ACCEL) {
        filterReset();
        groundTestStartMs = millis();
        groundTestLastSweepMs = groundTestStartMs;
        groundTestTarget = MOTOR_MIN;
        groundTestOpening = true;
        groundTestSweepStopped = false;
        currentState = STATE_GROUND_TEST_RECORDING;
        Serial.println("GROUND_TEST:TRIGGERED: recording and sweep started");
      }
      break;
    }

    case STATE_GROUND_TEST_RECORDING:
      filterUpdate();
      break;
  }
}

// Logging
uint32_t lastPrintTime = 0;
void debugPrintf(const char* format, ...) {
  if (millis() - lastPrintTime < 50) {
    return;  // Limit to 20Hz
  }
  lastPrintTime = millis();

  char buffer[128];
  va_list args;
  va_start(args, format);
  vsnprintf(buffer, sizeof(buffer), format, args);
  va_end(args);
  Serial.print(buffer);
}
