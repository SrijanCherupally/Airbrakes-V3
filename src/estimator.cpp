#include "estimator.h"

#include <math.h>

#include "config.h"
#include "hardware.h"
#include "kalman.h"
#include "orientation.h"

#define LOOPRATE 500  // Hz
static const float dTest = 1.0f / (float)LOOPRATE;

// Scalar altitude/velocity Kalman filter running at the loop rate.
static Kalman filter(1.0f / (float)LOOPRATE);

static float gCd = BASE_CD;
static float gRawBaro = 0.0f;

bool biasActive = true;

// Stationary detection tolerances for pad bias calibration.
static constexpr float BIAS_STATIONARY_ACCEL_TOL = 0.6f;  // m/s^2 around 1g
static constexpr float BIAS_STATIONARY_GYRO_MAX = 0.35f;  // rad/s
static const float alpha_cd = 0.05f;  // Cd low-pass, ~4 Hz @ 500 Hz

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
  filter.reset();
  gCd = BASE_CD;
  gRawBaro = baro.getAltitudeM();
}

float biasUpdate() {
  unsigned long start = micros();

  imu.update();

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
  }

  // Keep the barometer reference fresh.
  baro.update();
  gRawBaro = baro.getAltitudeM();

  holdLoopRate(start);

  return aMag;
}

void filterUpdate() {
  unsigned long start = micros();

  // Read IMU and propagate attitude
  imu.update();
  updateOrientation();

  // Kalman prediction from world-frame vertical acceleration
  filter.predict();

  // Barometer correction when a new sample is available
  if (baro.update()) {
    gRawBaro = baro.getAltitudeM();
    // High accel / high velocity make the baro unreliable (Mach effects),
    // so only fuse it during the calmer coast phase.
    float accel = filter.getCorrectedAcceleration();
    float vel = filter.getVelocity();
    if (fabsf(accel) < (4.0f * G) && fabsf(vel) < 55.0f) {
      filter.update();
    }
  }

  // Update Cd estimate only while decelerating under drag (coast phase).
  float accel = filter.getCorrectedAcceleration();
  float vel = filter.getVelocity();
  if (accel < -G && fabsf(vel) > 1.0f) {
    float currCd = -(2.0f * MASS * (accel + G)) / (rhoA * vel * fabsf(vel));
    gCd = (1.0f - alpha_cd) * gCd + alpha_cd * currCd;
  }

  holdLoopRate(start);
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
float estBias() {
  return filter.getBias();
}
float estRawBaro() {
  return gRawBaro;
}
float estCd() {
  return gCd;
}
