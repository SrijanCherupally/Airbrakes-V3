#include "baro.h"

#include <math.h>

bool BARO::begin() {
  initialized = init();
  return initialized;
}

bool BARO::update() {
  if (!initialized) return false;
  if (!waitForFlags(MEAS_PRS_RDY | MEAS_TMP_RDY, 100)) return false;
  rawT = readTempRaw();
  rawP = readPressureRaw();
  tempC = calcTemperatureC(rawT);
  pressurePa = calcPressurePa(rawP, rawT);
  altitude_cm =
      pressureToRelAlt_cm(pressurePa, baselinePressure, tempC + 273.15f);
  return true;
}

bool BARO::isConnected() {
  return initialized;
}

bool BARO::init() {
  dpsWire.setSCL(DPS368_SCL);
  dpsWire.setSDA(DPS368_SDA);
  dpsWire.begin();
  dpsWire.setClock(400000);  // 400kHz fast mode

  if (!selectAddress()) return false;

  dpsWrite(REG_RESET, 0x09);
  delay(50);
  if (!waitForFlags(MEAS_SENSOR_RDY, 100) ||
      !waitForFlags(MEAS_COEF_RDY, 100)) {
    return false;
  }

  readCoefficients();

  // High rate: 32Hz, OSR=8x
  dpsWrite(REG_PRS_CFG, 0x53);
  dpsWrite(REG_TMP_CFG, 0xA3);

  // Enable result shift
  uint8_t cfg = dpsRead8(REG_CFG_REG);
  cfg |= (1 << 2) | (1 << 3);
  dpsWrite(REG_CFG_REG, cfg);

  // Start background mode
  dpsWrite(REG_MEAS_CFG, 0x07);

  // Set baseline
  if (!waitForFlags(MEAS_PRS_RDY | MEAS_TMP_RDY, 100)) return false;
  rawT = readTempRaw();
  rawP = readPressureRaw();
  baselinePressure = calcPressurePa(rawP, rawT);
  return isfinite(baselinePressure) && baselinePressure > 1000.0f;
}

bool BARO::selectAddress() {
  const uint8_t addresses[] = {DPS368_I2C_ADDR_HIGH, DPS368_I2C_ADDR_LOW};
  for (uint8_t address : addresses) {
    dpsWire.beginTransmission(address);
    if (dpsWire.endTransmission() != 0) continue;

    i2cAddress = address;
    if (dpsRead8(REG_PROD_ID) == 0x10) return true;
  }
  return false;
}

void BARO::dpsWrite(uint8_t reg, uint8_t val) {
  dpsWire.beginTransmission(i2cAddress);
  dpsWire.write(reg);
  dpsWire.write(val);
  dpsWire.endTransmission();
}

uint8_t BARO::dpsRead8(uint8_t reg) {
  dpsWire.beginTransmission(i2cAddress);
  dpsWire.write(reg);
  dpsWire.endTransmission(false);  // repeated start, keep bus held
  dpsWire.requestFrom(i2cAddress, (uint8_t)1);
  uint8_t val = 0;
  if (dpsWire.available()) val = dpsWire.read();
  return val;
}

void BARO::dpsReadBlock(uint8_t reg, uint8_t *buf, uint8_t len) {
  dpsWire.beginTransmission(i2cAddress);
  dpsWire.write(reg);
  dpsWire.endTransmission(false);  // repeated start, keep bus held
  dpsWire.requestFrom(i2cAddress, len);
  for (uint8_t i = 0; i < len && dpsWire.available(); i++) {
    buf[i] = dpsWire.read();
  }
}

int32_t BARO::readRaw24(uint8_t reg) {
  uint8_t b[3];
  dpsReadBlock(reg, b, 3);
  int32_t x = ((int32_t)b[0] << 16) | ((int32_t)b[1] << 8) | b[2];
  if (x & 0x800000) x |= 0xFF000000;  // sign-extend
  return x;
}

void BARO::readCoefficients() {
  uint8_t buf[18];
  dpsReadBlock(REG_COEF, buf, 18);

  c0 = ((int16_t)buf[0] << 4) | (buf[1] >> 4);
  if (c0 & 0x0800) c0 |= 0xF000;

  c1 = (((int16_t)(buf[1] & 0x0F)) << 8) | buf[2];
  if (c1 & 0x0800) c1 |= 0xF000;

  c00 = ((int32_t)buf[3] << 12) | ((int32_t)buf[4] << 4) | (buf[5] >> 4);
  if (c00 & 0x80000) c00 |= 0xFFF00000;

  c10 = (((int32_t)(buf[5] & 0x0F)) << 16) | ((int32_t)buf[6] << 8) | buf[7];
  if (c10 & 0x80000) c10 |= 0xFFF00000;

  c01 = (int16_t)((buf[8] << 8) | buf[9]);
  c11 = (int16_t)((buf[10] << 8) | buf[11]);
  c20 = (int16_t)((buf[12] << 8) | buf[13]);
  c21 = (int16_t)((buf[14] << 8) | buf[15]);
  c30 = (int16_t)((buf[16] << 8) | buf[17]);
}

float BARO::calcTemperatureC(int32_t rawT) {
  return (float)c0 * 0.5f + (float)c1 * ((float)rawT / kT);
}

float BARO::calcPressurePa(int32_t rawP, int32_t rawT) {
  float Praw = rawP / kP;
  float Traw = rawT / kT;
  return (float)c00 +
         Praw * ((float)c10 + Praw * ((float)c20 + Praw * (float)c30)) +
         Traw * ((float)c01 + Praw * ((float)c11 + Praw * (float)c21));
}

float BARO::pressureToRelAlt_cm(float P, float P0, float T_K) {
  float h = -(R * T_K / g) * logf(P / P0);
  return h * 100.0f;
}

bool BARO::waitForFlags(uint8_t mask, uint32_t timeout_ms) {
  uint32_t t0 = millis();
  while (millis() - t0 < timeout_ms) {
    uint8_t m = dpsRead8(REG_MEAS_CFG);
    if ((m & mask) == mask) return true;
  }
  return false;
}
