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
  P[0][0] = 10.0f;  // altitude uncertainty
  P[0][1] = 0.0f;
  P[0][2] = 0.0f;
  P[1][0] = 0.0f;
  P[1][1] = 10.0f;  // velocity uncertainty
  P[1][2] = 0.0f;
  P[2][0] = 0.0f;
  P[2][1] = 0.0f;
  P[2][2] = 0.1f;  // bias uncertainty

  // Process noise
  Q_altitude = 0.01f;
  Q_velocity = 0.1f;
  Q_bias = 0.0001f;

  // DPS368 noise
  R_altitude = 2.0f;
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

  float oldVelocity = velocity;

  velocity += correctedAcceleration * dt;

  altitude += oldVelocity * dt + 0.5f * correctedAcceleration * dt * dt;

  P[0][0] += Q_altitude;
  P[1][1] += Q_velocity;
  P[2][2] += Q_bias;
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

  float K = P[0][0] / (P[0][0] + R_altitude);

  altitude += K * error;

  P[0][0] *= (1.0f - K);

  bias += 0.001f * error;
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
