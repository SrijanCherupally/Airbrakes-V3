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
        sampleCount(0),
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
  bool hasValidSample() const;

 private:
  static float median3(float a, float b, float c);
  ICM42688 imu;
  float acc_x, acc_y, acc_z;
  float gyr_x, gyr_y, gyr_z;
  float temp_c;
  // A 3-sample median removes isolated SPI/bus read glitches without adding
  // meaningful latency to the 1 kHz estimator. This is intentionally at
  // the driver boundary so both ground tests and flight use identical data.
  float accXHistory[3] = {0.0f, 0.0f, 0.0f};
  float accYHistory[3] = {0.0f, 0.0f, 0.0f};
  float accZHistory[3] = {0.0f, 0.0f, 0.0f};
  float gyrXHistory[3] = {0.0f, 0.0f, 0.0f};
  float gyrYHistory[3] = {0.0f, 0.0f, 0.0f};
  float gyrZHistory[3] = {0.0f, 0.0f, 0.0f};
  uint8_t sampleCount;
  bool initialized;
};

#endif  // IMU_H
