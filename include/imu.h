#ifndef IMU_H
#define IMU_H

#include <Arduino.h>
#include <SPI.h>

#include "ICM42688.h"

#define PIN_CS 9
#define PIN_SCK 10
#define PIN_MISO 8
#define PIN_MOSI 11

// ICM42688 6-axis IMU driver (SPI1).
class IMU {
 public:
  IMU()
      : imu(SPI1, PIN_CS),
        acc_x(0),
        acc_y(0),
        acc_z(0),
        gyr_x(0),
        gyr_y(0),
        gyr_z(0),
        temp_c(0),
        initialized(false) {}

  bool begin();
  void update();

  float getAccX() const { return acc_x; }
  float getAccY() const { return acc_y; }
  float getAccZ() const { return acc_z; }
  float getGyrX() const { return gyr_x; }
  float getGyrY() const { return gyr_y; }
  float getGyrZ() const { return gyr_z; }
  float getTemp() const { return temp_c; }
  bool isInitialized() const { return initialized; }

 private:
  ICM42688 imu;
  float acc_x, acc_y, acc_z;
  float gyr_x, gyr_y, gyr_z;
  float temp_c;
  bool initialized;
};

#endif  // IMU_H
