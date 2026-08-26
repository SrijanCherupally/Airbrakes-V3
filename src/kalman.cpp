#include "kalman.h"

#include <math.h>

#include "orientation.h"

namespace {
// A DPS368 can be very quiet on the bench, but the installed airframe,
// pressure port, vibration and airflow are the measurement system in flight.
// Treating it as an 8 cm sensor made each 32 Hz pressure frame dominate the
// inertial solution and caused matching steps in altitude and velocity.
// Coast qualification keeps dynamic-pressure frames out, so at apogee the
// pressure altitude can be trusted to about a metre without allowing it to
// dominate the high-speed ascent solution.
constexpr float kBaroStdDevM = 1.0f;
constexpr float kBaroVariance = kBaroStdDevM * kBaroStdDevM;
constexpr float kMinPredictDt = 0.00025f;
constexpr float kMaxPredictDt = 0.050f;

// A valid pressure observation may refine velocity through the covariance,
// but it must not create a discontinuity in the flight state.  These limits
// are per barometer frame (nominally 32 Hz), not limits on IMU propagation.
constexpr float kMaxAltitudeCorrectionM = 25.0f;
constexpr float kMaxVelocityCorrectionMps = 8.0f;
// Bias is calibrated while stationary. Altitude alone cannot independently
// observe both velocity and accelerometer bias during a short rocket flight;
// allowing pressure innovations to learn bias caused the runaway solutions.
constexpr float kMaxBiasCorrectionMps2 = 0.0f;

static float limitMagnitude(float value, float limit) {
  if (value > limit) return limit;
  if (value < -limit) return -limit;
  return value;
}
}  // namespace

Kalman::Kalman(float dt) {
  this->dt = dt;
  reset();
}

void Kalman::reset() {
  // Initial state
  altitude = 0.0f;
  velocity = 0.0f;
  bias = 0.0f;
  correctedAcceleration = 0.0f;

  worldAcc[0] = 0.0f;
  worldAcc[1] = 0.0f;
  worldAcc[2] = 0.0f;

  // Initial uncertainty
  P[0][0] = 0.05f;  // altitude uncertainty after zeroing the baro
  P[0][1] = 0.0f;
  P[0][2] = 0.0f;
  P[1][0] = 0.0f;
  P[1][1] = 1.0f;  // velocity uncertainty
  P[1][2] = 0.0f;
  P[2][0] = 0.0f;
  P[2][1] = 0.0f;
  P[2][2] = 0.0f;  // fixed to the stationary calibration in flight

  // Process noise
  Q_altitude = 0.8f * 0.8f;  // acceleration noise density
  Q_velocity = 0.0f;         // retained for compatibility with state layout
  Q_bias = 0.0f;  // do not infer accelerometer bias from pressure altitude

  // DPS368 noise
  R_altitude = kBaroVariance;
}

void Kalman::setBias(float value) {
  bias = value;
}

void Kalman::predict(float elapsedSeconds) {
  getWorldAcceleration(worldAcc);

  // Reject impossible/non-finite IMU values before they can poison the
  // integrated altitude and velocity states.
  if (!isfinite(worldAcc[2]) || fabsf(worldAcc[2]) > 200.0f) {
    correctedAcceleration = 0.0f;
    return;
  }

  if (!isfinite(elapsedSeconds) || elapsedSeconds < kMinPredictDt ||
      elapsedSeconds > kMaxPredictDt) {
    // A debugger halt, I2C fault, or scheduler stall must not be interpreted
    // as a long period of constant acceleration from one stale IMU sample.
    correctedAcceleration = worldAcc[2] - bias;
    return;
  }

  const float stepDt = elapsedSeconds;
  correctedAcceleration = worldAcc[2] - bias;

  const float dt2 = stepDt * stepDt;
  const float halfDt2 = 0.5f * dt2;
  altitude += velocity * stepDt + halfDt2 * correctedAcceleration;
  velocity += correctedAcceleration * stepDt;

  // Full constant-acceleration covariance propagation.  The previous code
  // discarded the altitude/velocity and altitude/bias cross-covariances, so
  // barometer measurements could not correct vertical velocity.
  float F[3][3] = {{1.0f, stepDt, -halfDt2},
                   {0.0f, 1.0f, -stepDt},
                   {0.0f, 0.0f, 1.0f}};
  float FP[3][3] = {};
  float nextP[3][3] = {};
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j)
      for (int k = 0; k < 3; ++k) FP[i][j] += F[i][k] * P[k][j];
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j)
      for (int k = 0; k < 3; ++k) nextP[i][j] += FP[i][k] * F[j][k];
  const float q = Q_altitude;
  nextP[0][0] += q * dt2 * dt2 * 0.25f;
  nextP[0][1] += q * dt2 * stepDt * 0.5f;
  nextP[1][0] += q * dt2 * stepDt * 0.5f;
  nextP[1][1] += q * dt2;
  nextP[2][2] += Q_bias * stepDt;
  // Bias is fixed after pad calibration. Keep its covariance decoupled so a
  // pressure residual cannot masquerade as a bias observation.
  nextP[0][2] = nextP[2][0] = 0.0f;
  nextP[1][2] = nextP[2][1] = 0.0f;
  nextP[2][2] = 0.0f;
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j) P[i][j] = nextP[i][j];
}

bool Kalman::isAltitudeMeasurementPlausible(float altitudeMeasurement) const {
  if (!isfinite(altitudeMeasurement) || fabsf(altitudeMeasurement) > 100000.0f ||
      !isfinite(altitude) || !isfinite(velocity) || !isfinite(bias)) {
    return false;
  }

  // Innovation size cannot determine sensor validity. If inertial propagation
  // has drifted, a valid barometer reading is necessarily a large innovation;
  // rejecting it makes recovery impossible. Individual pressure frames are
  // screened at the driver boundary and correction magnitude is bounded in
  // update(), so only validate the measurement/state domain here.
  return true;
}

bool Kalman::update(float altitudeMeasurement) {
  if (!isAltitudeMeasurementPlausible(altitudeMeasurement)) return false;

  float error = altitudeMeasurement - altitude;
  const float S = P[0][0] + R_altitude;

  // Once barometric aiding is enabled, a very large innovation means the
  // inertial solution has already diverged. Limiting a normal Kalman gain to
  // 25 m would leave the velocity wrong for seconds and was the mechanism
  // behind the kilometre-scale flight-log errors. Re-anchor altitude to the
  // independent pressure measurement and bound the remaining inertial
  // velocity before resuming normal covariance-based corrections.
  if (fabsf(error) > 100.0f) {
    altitude = altitudeMeasurement;
    if (!isfinite(velocity) || fabsf(velocity) > 100.0f) velocity = 0.0f;
    P[0][0] = kBaroVariance;
    P[0][1] = P[1][0] = 0.0f;
    P[1][1] = fminf(P[1][1], 25.0f);
    P[0][2] = P[2][0] = P[1][2] = P[2][1] = 0.0f;
    return true;
  }

  float K[3] = {P[0][0] / S, P[1][0] / S, P[2][0] / S};
  float effectiveK[3] = {K[0], K[1], K[2]};
  float correctionLimits[3] = {kMaxAltitudeCorrectionM,
                               kMaxVelocityCorrectionMps,
                               kMaxBiasCorrectionMps2};
  for (int i = 0; i < 3; ++i) {
    float requestedCorrection = K[i] * error;
    float limitedCorrection = limitMagnitude(requestedCorrection, correctionLimits[i]);
    // If a correction is limited, use the corresponding reduced gain in the
    // covariance update as well.  Shrinking P with the original, much larger
    // gain would make the filter falsely believe a large jump had been
    // applied and prevent later valid measurements from helping.
    if (requestedCorrection != 0.0f) {
      effectiveK[i] = limitedCorrection / error;
    }
  }

  altitude += effectiveK[0] * error;
  velocity += effectiveK[1] * error;
  // Bias remains the independently measured stationary calibration.

  if (!isfinite(altitude) || !isfinite(velocity)) return false;

  // Joseph-form covariance update.  Unlike the compact (I-KH)P form used
  // by Rock7, this remains symmetric and positive semidefinite in float32,
  // including when a correction was deliberately limited above.
  float oldP[3][3];
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j) oldP[i][j] = P[i][j];

  float I_KH[3][3] = {{1.0f - effectiveK[0], 0.0f, 0.0f},
                      {-effectiveK[1], 1.0f, 0.0f},
                      {-effectiveK[2], 0.0f, 1.0f}};
  float temp[3][3] = {};
  float joseph[3][3] = {};
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j)
      for (int k = 0; k < 3; ++k) temp[i][j] += I_KH[i][k] * oldP[k][j];
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j)
      for (int k = 0; k < 3; ++k) joseph[i][j] += temp[i][k] * I_KH[j][k];
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j)
      joseph[i][j] += effectiveK[i] * S * effectiveK[j];

  for (int i = 0; i < 3; ++i) {
    for (int j = i + 1; j < 3; ++j) {
      float symmetric = 0.5f * (joseph[i][j] + joseph[j][i]);
      joseph[i][j] = symmetric;
      joseph[j][i] = symmetric;
    }
    if (!isfinite(joseph[i][i]) || joseph[i][i] < 0.0f) return false;
  }
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j) P[i][j] = joseph[i][j];
  return true;
}

void Kalman::injectVelocity(float dv) {
  velocity += dv;
}

float Kalman::getAltitude() {
  return altitude;
}

float Kalman::getVelocity() {
  return velocity;
}

float Kalman::getBias() {
  return bias;
}

float Kalman::getCorrectedAcceleration() {
  return correctedAcceleration;
}
