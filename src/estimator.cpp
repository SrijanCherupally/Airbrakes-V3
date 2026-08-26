#include "estimator.h"

#include <math.h>

#include "config.h"
#include "hardware.h"
#include "kalman.h"
#include "orientation.h"
#include "flash.h"
#include "state.h"
#include "control.h"

#define LOOPRATE 1000  // Hz, pad calibration only; flight runs sensor-paced
static const float dTest = 1.0f / (float)LOOPRATE;

// Scalar altitude/velocity Kalman filter running at the loop rate.
static Kalman filter(1.0f / (float)LOOPRATE);

static float gCd = BASE_CD;
static float gRawBaro = 0.0f;
static float gRawAccel = 0.0f;
static float gVerticalAccel = 0.0f;
static float gCalibratedBias = 0.0f;
static uint32_t gLastPredictUs = 0;
static uint32_t gCoastStartMs = 0;
static uint8_t gBaroQualifiedSamples = 0;
static bool gBaroQualified = false;

bool biasActive = true;

// Stationary detection tolerances for pad bias calibration.
static constexpr float BIAS_STATIONARY_ACCEL_TOL = 0.6f;  // m/s^2 around 1g
static constexpr float BIAS_STATIONARY_GYRO_MAX = 0.35f;  // rad/s
static const float alpha_cd = 0.025f;  // Cd low-pass, ~4 Hz @ 1 kHz

// Barometer pressure is not a static-pressure measurement while the vehicle
// is under thrust or moving quickly.  Re-enable it only after coast has had
// time to settle, then demand several innovation-valid readings before it can
// change the state.  The motion thresholds intentionally match the original
// Rock7-style coast gate; timing and consecutive-frame qualification prevent
// a single early-coast pressure reading from producing a state jump.
static constexpr uint32_t BARO_COAST_SETTLE_MS = 600;
static constexpr float BARO_COAST_MAX_ACCEL = 4.0f * G;
static constexpr uint8_t BARO_QUALIFY_SAMPLES = 5;

static void holdLoopRate(unsigned long startUs) {
  unsigned long deltmicros = micros() - startUs;
  unsigned long budget = (unsigned long)(dTest * 1e6f);
  if (deltmicros < budget) {
    delayMicroseconds(budget - deltmicros);
  }
}

void filterReset() {
  imu.update();
  baro.update();
  initOrientation();
  // Zero both raw barometric altitude and the Kalman measurement at the
  // instant a ground test or flight begins.
  baro.zeroAltitude();
  filter.reset();
  filter.setBias(gCalibratedBias);
  gLastPredictUs = micros();
  gCoastStartMs = 0;
  gBaroQualifiedSamples = 0;
  gBaroQualified = false;
  gCd = BASE_CD;
  if (baro.isConnected()) gRawBaro = baro.getAltitudeM();
  gRawAccel = 0.0f;
  gVerticalAccel = 0.0f;
}

float biasUpdate() {
  unsigned long start = micros();

  imu.update();
  gRawAccel = imu.getAccZ() - G;

  float a[3] = {imu.getAccX(), imu.getAccY(), imu.getAccZ()};
  float g[3] = {imu.getGyrX(), imu.getGyrY(), imu.getGyrZ()};

  float aMag = sqrtf(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
  float gMag = sqrtf(g[0] * g[0] + g[1] * g[1] + g[2] * g[2]);

  bool stationary = (fabsf(aMag - G) < BIAS_STATIONARY_ACCEL_TOL) &&
                    (gMag < BIAS_STATIONARY_GYRO_MAX);
  biasActive = stationary;

  // While stationary, keep the attitude aligned to gravity so launch starts
  // from a good reference.
  if (stationary) {
    initOrientation();
    float worldAcceleration[3];
    getWorldAcceleration(worldAcceleration);
    // At rest, world-frame vertical specific force should be zero. Average
    // it slowly so the estimate is not reset to zero when the filter starts.
    gCalibratedBias = 0.995f * gCalibratedBias + 0.005f * worldAcceleration[2];
    filter.setBias(gCalibratedBias);
  }

  // Keep the barometer reference fresh.
  baro.update();
  gRawBaro = baro.getAltitudeM();

  holdLoopRate(start);

  return aMag;
}

void filterUpdate() {
  // Propagate only when a fresh IMU conversion was published. This lets the
  // flight loop run as quickly as SPI permits without integrating duplicates.
  bool imuFresh = imu.update();
  uint32_t predictNowUs = imuFresh ? imu.getSampleTimeUs() : gLastPredictUs;
  float predictDt = (gLastPredictUs == 0 || !imuFresh)
                        ? dTest
                        : (float)(predictNowUs - gLastPredictUs) * 1.0e-6f;
  if (imuFresh) gLastPredictUs = predictNowUs;
  // Descent rotation makes gyro-only tilt drift into a false vertical
  // acceleration. Specific force is near 1 g after deployment, so use it to
  // keep gravity aligned without trusting it during boost or controlled coast.
  if (imuFresh) {
    updateOrientation(predictDt, currentState == STATE_DESCENT);
  }

  // Keep raw sensor telemetry independent of the Kalman/barometer update.
  // Previously the logger used estAccel(), which is already bias-corrected,
  // and the raw field therefore did not contain the raw accelerometer data.
  float worldAcceleration[3];
  getWorldAcceleration(worldAcceleration);
  gRawAccel = worldAcceleration[2];
  // Match the acceleration used by Kalman::predict(), including the current
  // bias estimate. This is the physically meaningful vertical acceleration
  // for airbrake analysis, not merely the original pad calibration value.
  gVerticalAccel = worldAcceleration[2] - filter.getBias();

  if (!isfinite(gRawAccel) || !isfinite(gVerticalAccel) ||
      fabsf(gRawAccel) > 200.0f || fabsf(gVerticalAccel) > 200.0f) {
    gRawAccel = 0.0f;
    gVerticalAccel = 0.0f;
  }

  // Capture every estimator sample for flight and ground-test analysis. The
  // logger only copies into a RAM queue here; core 0 writes the queue to flash.
  // Flash is deliberately sampled at 100 Hz. Logging every 1 kHz estimator
  // iteration made the producer faster than LittleFS/CAN servicing and caused
  // queue overflow, which looked like a test that started seconds late.
  static uint32_t lastLogMs = 0;
  uint32_t nowMs = millis();
  bool logDue = (lastLogMs == 0) || (uint32_t)(nowMs - lastLogMs) >= 10;
  // Kalman prediction from world-frame vertical acceleration.  Do not assume
  // that loop1 has executed exactly every 2 ms: SPI, serial interrupts and
  // scheduler load otherwise scale velocity and altitude by the wrong factor.
  if (imuFresh) {
    filter.predict(predictDt);
  }

  // Barometer correction when a new sample is available
  if (baro.update()) {
    gRawBaro = baro.getAltitudeM();
    // Do not use the estimated velocity to decide whether pressure may aid:
    // once inertial velocity drifts, that circular gate prevents the only
    // independent altitude sensor from ever correcting it. Continuous boost
    // pressure data remains logged but cannot change the state.
    float accel = filter.getCorrectedAcceleration();
    bool calmCoast = fabsf(accel) < BARO_COAST_MAX_ACCEL;

    if (currentState == STATE_CONTROL) {
      if (gCoastStartMs == 0) gCoastStartMs = nowMs;
      bool coastSettled = (uint32_t)(nowMs - gCoastStartMs) >=
                         BARO_COAST_SETTLE_MS;
      // Never qualify pressure against the drifting inertial altitude. Flights
      // 3-5 showed that circular check permanently locked out the only absolute
      // reference after the inertial state had diverged.
      if (coastSettled && calmCoast) {
        if (gBaroQualifiedSamples < BARO_QUALIFY_SAMPLES) {
          ++gBaroQualifiedSamples;
        }
        gBaroQualified =
            gBaroQualifiedSamples >= BARO_QUALIFY_SAMPLES;
      } else {
        // A pressure frame that becomes inconsistent again must requalify;
        // this handles transient airflow and pressure-port disturbances.
        gBaroQualifiedSamples = 0;
        gBaroQualified = false;
      }
    } else if (currentState == STATE_BOOST) {
      gCoastStartMs = 0;
      gBaroQualifiedSamples = 0;
      gBaroQualified = false;
    }

    bool baroAidingAllowed =
        (currentState == STATE_CONTROL && gBaroQualified && calmCoast) ||
        (currentState == STATE_DESCENT && fabsf(accel) < (4.0f * G)) ||
        currentState == STATE_GROUND_TEST_RECORDING;
    if (baroAidingAllowed) {
      filter.update(gRawBaro);
    }
  }

  // Update Cd estimate only while decelerating under drag (coast phase).
  float accel = filter.getCorrectedAcceleration();
  float vel = filter.getVelocity();
  // CD is identifiable only during powered-flight coast/control.  Ground
  // tests never enter these states, but keep the state gate explicit so a
  // future diagnostic mode cannot turn bench motion into a flight CD.
  bool flightCoast = (currentState == STATE_BOOST ||
                      currentState == STATE_CONTROL);
  if (flightCoast && accel < -G && vel > 1.0f) {
    float currCd = -(2.0f * MASS * (accel + G)) / (rhoA * vel * fabsf(vel));
    if (isfinite(currCd) && currCd >= 0.0f && currCd < 10.0f) {
      gCd = (1.0f - alpha_cd) * gCd + alpha_cd * currCd;
    }
  }

  if (logDue && (currentState == STATE_GROUND_TEST_RECORDING ||
      currentState == STATE_BOOST || currentState == STATE_CONTROL ||
      currentState == STATE_DESCENT)) {
    lastLogMs = nowMs;
    logFlightData(estAltitude(), estVelocity(), estBias(), estRawAccel(),
                  estVerticalAccel(), estRawBaro(), motorpos, motorvel,
                  motor_cmd_pos, estCd(), desiredCd, motorcurrent,
                  batteryVoltage, axisError);
  }

  // No fixed sleep in flight: fresh IMU and pressure timestamps independently
  // pace prediction and correction at the fastest rates the sensors deliver.
}

void estimatorInjectVelocity(float dv) {
  filter.injectVelocity(dv);
}

float estAltitude() {
  return filter.getAltitude();
}
float estVelocity() {
  return filter.getVelocity();
}
float estAccel() {
  return filter.getCorrectedAcceleration();
}
float estRawAccel() {
  return gRawAccel;
}
float estVerticalAccel() {
  return gVerticalAccel;
}
float estBias() {
  // Log the bias that prediction actually subtracts. The Kalman barometer
  // update can refine this after pad calibration; returning only
  // gCalibratedBias made that evolving value appear to remain at zero.
  float filterBias = filter.getBias();
  return isfinite(filterBias) ? filterBias : 0.0f;
}
float estRawBaro() {
  return baro.isConnected() ? baro.getAltitudeM() : gRawBaro;
}
float estCd() {
  return gCd;
}
