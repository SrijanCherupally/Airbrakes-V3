#include "imu.h"
#include <math.h>

// The ICM42688 library reports acceleration in g and angular rate in
// degrees/second. The rest of the flight software works in SI units
// (m/s^2 and rad/s), so convert here at the driver boundary.
static constexpr float G_TO_MS2 = 9.80665f;
static constexpr float DPS_TO_RADS = 0.017453292519943295f;  // pi / 180

bool IMU::begin() {
  SPI1.setSCK(PIN_SCK);
  SPI1.setMISO(PIN_MISO);
  SPI1.setMOSI(PIN_MOSI);
  SPI1.begin();

  Serial.println("Starting IMU initialization...");

  int status = imu.begin();
  if (status < 0) {
    Serial.println("IMU initialization unsuccessful");
    Serial.println("Check IMU wiring or try cycling power");
    Serial.print("Status: ");
    Serial.println(status);
    initialized = false;
    return false;
  }

  // Flight configuration: widest ranges so high-G boost does not saturate.
  // 32 kHz is the ICM42688-P's maximum low-noise output rate; the estimator
  // polls the most recent sample at 1 kHz, avoiding stale 1 kHz data while
  // retaining ample margin for SPI and the second core's services.
  if (imu.setAccelFS(ICM42688::gpm16) < 0 ||
      imu.setGyroFS(ICM42688::dps2000) < 0 ||
      imu.setAccelODR(ICM42688::odr32k) < 0 ||
      imu.setGyroODR(ICM42688::odr32k) < 0 ||
      // Keep the sensor's anti-alias filters enabled. At 32 kHz they reject
      // vibration above the estimator bandwidth without sacrificing usable
      // flight dynamics.
      imu.setFilters(true, true) < 0) {
    Serial.println("IMU flight configuration unsuccessful");
    initialized = false;
    return false;
  }

  Serial.println("IMU initialized on SPI1!");
  sampleCount = 0;
  initialized = true;
  return true;
}

bool IMU::update() {
  if (!initialized) return false;
  // The sensor is configured for its 32 kHz low-noise ODR. Never publish the
  // same output register more than once per conversion period.
  uint32_t nowUs = micros();
  if (sampleTimeUs != 0 && (uint32_t)(nowUs - sampleTimeUs) < 30u) return false;
  // getAGT() reports a failed SPI transaction. Do not timestamp or publish it
  // as a fresh estimator sample.
  if (imu.getAGT() < 0) return false;
  float ax = imu.accX() * G_TO_MS2;
  float ay = imu.accY() * G_TO_MS2;
  float az = imu.accZ() * G_TO_MS2;
  float gx = imu.gyrX() * DPS_TO_RADS;
  float gy = imu.gyrY() * DPS_TO_RADS;
  float gz = imu.gyrZ() * DPS_TO_RADS;
  float tc = imu.temp();

  // Never let a malformed SPI transaction enter the estimator or overwrite
  // the last good sample. No software averaging is applied: the Kalman filter
  // receives every valid read with minimum latency.
  if (!isfinite(ax) || !isfinite(ay) || !isfinite(az) ||
      !isfinite(gx) || !isfinite(gy) || !isfinite(gz) || !isfinite(tc) ||
      fabsf(ax) >= 200.0f || fabsf(ay) >= 200.0f || fabsf(az) >= 200.0f ||
      fabsf(gx) >= 40.0f || fabsf(gy) >= 40.0f || fabsf(gz) >= 40.0f) {
    return false;
  }

  acc_x = ax;
  acc_y = ay;
  acc_z = az;
  gyr_x = gx;
  gyr_y = gy;
  gyr_z = gz;
  temp_c = tc;
  sampleTimeUs = micros();
  ++sampleCount;
  return true;
}


bool IMU::hasValidSample() const {
  return initialized && isfinite(acc_x) && isfinite(acc_y) && isfinite(acc_z) &&
         isfinite(gyr_x) && isfinite(gyr_y) && isfinite(gyr_z) &&
         isfinite(temp_c) && fabsf(acc_x) < 200.0f && fabsf(acc_y) < 200.0f &&
         fabsf(acc_z) < 200.0f && fabsf(gyr_x) < 40.0f && fabsf(gyr_y) < 40.0f &&
         fabsf(gyr_z) < 40.0f;
}
