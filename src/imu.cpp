#include "imu.h"

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

  // Flight configuration: widest ranges so high-G boost does not saturate,
  // sampled well above the 500 Hz estimator loop.
  imu.setAccelFS(ICM42688::gpm16);
  imu.setGyroFS(ICM42688::dps2000);
  imu.setAccelODR(ICM42688::odr1k);
  imu.setGyroODR(ICM42688::odr1k);

  Serial.println("IMU initialized on SPI1!");
  initialized = true;
  return true;
}

void IMU::update() {
  if (!initialized) return;
  imu.getAGT();
  acc_x = imu.accX() * G_TO_MS2;
  acc_y = imu.accY() * G_TO_MS2;
  acc_z = imu.accZ() * G_TO_MS2;
  gyr_x = imu.gyrX() * DPS_TO_RADS;
  gyr_y = imu.gyrY() * DPS_TO_RADS;
  gyr_z = imu.gyrZ() * DPS_TO_RADS;
  temp_c = imu.temp();
}
