#include "kalman.h"

#include <math.h>

#include "hardware.h"
#include "orientation.h"

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
  P[2][2] = 0.25f;  // bias uncertainty

  // Process noise
  Q_altitude = 0.8f * 0.8f;  // acceleration noise density
  Q_velocity = 0.00001f;     // bias random walk density
  Q_bias = 0.00001f;

  // DPS368 noise
  R_altitude = 0.08f * 0.08f;
}

void Kalman::setBias(float value) {
  bias = value;
}

void Kalman::predict() {
  getWorldAcceleration(worldAcc);

  // Reject impossible/non-finite IMU values before they can poison the
  // integrated altitude and velocity states.
  if (!isfinite(worldAcc[2]) || fabsf(worldAcc[2]) > 200.0f) {
    correctedAcceleration = 0.0f;
    return;
  }

  correctedAcceleration = worldAcc[2] - bias;

  const float dt2 = dt * dt;
  const float halfDt2 = 0.5f * dt2;
  altitude += velocity * dt + halfDt2 * correctedAcceleration;
  velocity += correctedAcceleration * dt;

  // Full constant-acceleration covariance propagation.  The previous code
  // discarded the altitude/velocity and altitude/bias cross-covariances, so
  // barometer measurements could not correct vertical velocity.
  float F[3][3] = {{1.0f, dt, -halfDt2}, {0.0f, 1.0f, -dt}, {0.0f, 0.0f, 1.0f}};
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
  nextP[0][1] += q * dt2 * dt * 0.5f;
  nextP[1][0] += q * dt2 * dt * 0.5f;
  nextP[1][1] += q * dt2;
  nextP[2][2] += Q_velocity * dt;
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j) P[i][j] = nextP[i][j];
}

void Kalman::update() {
  float altitudeMeasurement = baro.getAltitudeM();
  if (!isfinite(altitudeMeasurement) || fabsf(altitudeMeasurement) > 100000.0f ||
      !isfinite(altitude) || !isfinite(velocity) || !isfinite(bias)) {
    return;
  }

  float error = altitudeMeasurement - altitude;
  // A barometer frame jump is not physically plausible and must not be used
  // to drag the integrated state into the 1e28-range values seen in logs.
  if (!isfinite(error) || fabsf(error) > 1000.0f) {
    return;
  }

  const float S = P[0][0] + R_altitude;
  if (!isfinite(S) || S <= 0.0f) return;
  float K[3] = {P[0][0] / S, P[1][0] / S, P[2][0] / S};
  altitude += K[0] * error;
  velocity += K[1] * error;
  bias += K[2] * error;

  float oldP[3][3];
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j) oldP[i][j] = P[i][j];
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j)
      P[i][j] = oldP[i][j] - K[i] * oldP[0][j] - oldP[i][0] * K[j] +
                K[i] * S * K[j];
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
