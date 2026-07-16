#include "state.h"

#include <stdarg.h>

#include "config.h"

State currentState = STATE_IDLE;

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

// Launch tracking in PAD: arm early and recover pre-roll dv before BOOST.
constexpr uint32_t PAD_LAUNCH_WINDOW_MS = 100;
constexpr uint32_t PAD_LAUNCH_CHECK_DELAY_MS = 50;
constexpr float PAD_LAUNCH_ARM_ACCEL = 11.5f;  // accel magnitude (includes 1g)
constexpr int PAD_PREROLL_SAMPLES = 150;       // 0.30 s at 500 Hz
constexpr float PAD_LOOP_DT = 1.0f / 500.0f;

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
      // LED indicator: yellow if low storage, green otherwise
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
            resetPadLaunchTracking();
          }
        }
        break;
      }
      // If ODrive heartbeat is stale, show a bright, noticeable LED
      // indicator in PAD so the operator can see the fault immediately.
      if (!odriveHeartbeatFresh()) {
        // Flash bright magenta/red at ~2Hz to attract attention
        if (((millis() / 250) & 1) == 0) {
          ledWrite(1.0f, 0.0f, 0.5f);
        } else {
          ledWrite(1.0f, 0.0f, 0.0f);
        }
        debugPrintf("STATE: PAD - ODrive heartbeat stale\n");
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

    case STATE_BOOST:
      ledWrite(1.0f, 0.0f, 0.0f);  // Solid red
      debugPrintf("STATE: BOOST\n");

      // Log all data (GetOrientation called internally at 100Hz)
      logFlightData(estAltitude(), estVelocity(), estBias(), estAccel(),
                    estRawBaro(), motorpos, motorvel, motor_cmd_pos, estCd(),
                    estCd(), motorcurrent, axisError);

      // See if time for control (look at vertical vel)
      if (estVelocity() < VEL_CONTROL_START && estAltitude() > ALT_LANDED &&
          estAccel() < 0.0f) {
        currentState = STATE_CONTROL;
      }
      break;

    case STATE_CONTROL:
      ledWrite(1.0f, 1.0f, 0.0f);  // Solid yellow
      debugPrintf("STATE: CONTROL\n");

      // Log all data (GetOrientation called internally at 100Hz)
      logFlightData(estAltitude(), estVelocity(), estBias(), estAccel(),
                    estRawBaro(), motorpos, motorvel, motor_cmd_pos, estCd(),
                    desiredCd, motorcurrent, axisError);

      controlUpdate();

      // See if apogee reached
      if (estVelocity() < VEL_DESCENT) {
        currentState = STATE_DESCENT;
      }
      break;

    case STATE_DESCENT:
      ledWrite(1.0f, 1.0f, 1.0f);  // Solid white
      debugPrintf("STATE: DESCENT\n");
      logFlightData(estAltitude(), estVelocity(), estBias(), estAccel(),
                    estRawBaro(), motorpos, motorvel, motor_cmd_pos, estCd(),
                    estCd(), motorcurrent, axisError);
      odrvPosition(MOTOR_MIN);  // Closed

      if (estAltitude() < ALT_LANDED) {
        currentState = STATE_LANDED;
        flushLogBuffer();  // Flush log buffer
      }
      break;

    case STATE_LANDED:
      debugPrintf("STATE: LANDED\n");
      ledWrite(1.0f, 0.0f, 1.0f);  // Solid purple
      break;
  }
}

void stateInit() {
  currentState = STATE_IDLE;
  lastNonIdleTime = millis();
  resetPadLaunchTracking();
}

void estimatorUpdate() {
  switch (currentState) {
    case STATE_IDLE: {
      imu.update();
      float aZ = imu.getAccZ();  // Read Z accel (m/s^2)
      if (aZ < 9.0f || aZ > 11.0f) {
        // Movement, not idle
        lastNonIdleTime = millis();
      }

      if (millis() - lastNonIdleTime > 10000) {
        // Idle vertical for 10s, go to PAD state
        currentState = STATE_PAD;
        initFlash();          // Initialize flight data file
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

      // Enable odrive
      EnableOdrv();

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
