#ifndef BARO_H
#define BARO_H

#include <Arduino.h>
#include <Wire.h>

// ---------- PIN DEFINES ----------
#define DPS368_SCL 5
#define DPS368_SDA 4
#define dpsWire Wire

// DPS368 I2C address: 0x77 if SDO pin is high (or floating/pulled up),
// 0x76 if SDO pin is tied to GND. Change this if your board wires SDO low.
#define DPS368_I2C_ADDR 0x77

// ---------- REGISTERS ----------
#define REG_PRS_B2 0x00
#define REG_TMP_B2 0x03
#define REG_PRS_CFG 0x06
#define REG_TMP_CFG 0x07
#define REG_MEAS_CFG 0x08
#define REG_CFG_REG 0x09
#define REG_RESET 0x0C
#define REG_PROD_ID 0x0D
#define REG_COEF 0x10

// ---------- MEAS_CFG FLAGS ----------
#define MEAS_SENSOR_RDY (1u << 7)
#define MEAS_COEF_RDY (1u << 6)
#define MEAS_TMP_RDY (1u << 5)
#define MEAS_PRS_RDY (1u << 4)

// DPS368 barometric pressure sensor driver.
class BARO {
 public:
  BARO() {}

  void begin();
  bool update();
  bool isConnected();

  float getTemperatureC() const { return tempC; }
  float getPressurePa() const { return pressurePa; }
  float getAltitudeCm() const { return altitude_cm; }
  float getAltitudeM() const { return altitude_cm / 100.0f; }
  float getBaselinePressure() const { return baselinePressure; }

 private:
  // Calibration coefficients
  int16_t c0, c1;
  int32_t c00, c10;
  int16_t c01, c11, c20, c21, c30;

  float kT = 524288.0f;  // OSR=8
  float kP = 524288.0f;  // OSR=8

  float baselinePressure = 0.0f;
  const float R = 287.05f;
  const float g = 9.80665f;

  int32_t rawT = 0, rawP = 0;
  float tempC = 0.0f, pressurePa = 0.0f, altitude_cm = 0.0f;

  void init();

  // I2C helpers
  void dpsWrite(uint8_t reg, uint8_t val);
  uint8_t dpsRead8(uint8_t reg);
  void dpsReadBlock(uint8_t reg, uint8_t *buf, uint8_t len);
  int32_t readRaw24(uint8_t reg);
  int32_t readPressureRaw() { return readRaw24(REG_PRS_B2); }
  int32_t readTempRaw() { return readRaw24(REG_TMP_B2); }

  void readCoefficients();
  float calcTemperatureC(int32_t rawT);
  float calcPressurePa(int32_t rawP, int32_t rawT);
  float pressureToRelAlt_cm(float P, float P0, float T_K);
  bool waitForFlags(uint8_t mask, uint32_t timeout_ms);
};

#endif  // BARO_H
