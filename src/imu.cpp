#include <Arduino.h>
#include <SPI.h>
#include "ICM42688.h"

#define PIN_CS   9
#define PIN_SCK 10
#define PIN_MISO 8
#define PIN_MOSI 11

class IMU {
public:
  IMU() : imu(SPI1, PIN_CS), acc_x(0), acc_y(0), acc_z(0), gyr_x(0), gyr_y(0), gyr_z(0), temp_c(0), initialized(false) {}

  bool begin() {
    Serial.begin(115200);
    while (!Serial) { }
    delay(100);

    Serial.println("Starting IMU initialization...");

    SPI1.setSCK(PIN_SCK);
    SPI1.setMISO(PIN_MISO);
    SPI1.setMOSI(PIN_MOSI);
    SPI1.begin();

    int status = imu.begin();
    if (status < 0) {
      Serial.println("IMU initialization unsuccessful");
      Serial.println("Check IMU wiring or try cycling power");
      Serial.print("Status: ");
      Serial.println(status);
      initialized = false;
      return false;
    }

    Serial.println("IMU initialized on SPI1!");
    Serial.println("ax,ay,az,gx,gy,gz,temp_C");
    initialized = true;
    return true;
  }

  void update() {
    if (!initialized) return;
    imu.getAGT();
    acc_x = imu.accX();
    acc_y = imu.accY();
    acc_z = imu.accZ();
    gyr_x = imu.gyrX();
    gyr_y = imu.gyrY();
    gyr_z = imu.gyrZ();
    temp_c = imu.temp();
  }

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