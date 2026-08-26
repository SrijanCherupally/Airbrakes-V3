#include "baro.h"

#include <math.h>

bool BARO::begin() {
  initialized = init();
  return initialized;
}

void BARO::zeroAltitude() {
  if (hasValidSample()) altitude_offset_cm = altitude_cm;
}

bool BARO::update() {
  ++updateCount;
  if (!initialized) return false;
  // PRS_RDY remains asserted in continuous mode, so rate-limit reads to one
  // conversion period. This prevents a tight estimator loop from repeatedly
  // fusing the same held pressure register as if it were new data.
  uint32_t nowUs = micros();
  if (lastPressureReadUs != 0 &&
      (uint32_t)(nowUs - lastPressureReadUs) < 7500u) return false;
  uint8_t flags = dpsRead8(REG_MEAS_CFG);
  lastStatus = flags;
  if (flags & MEAS_TMP_RDY) rawT = readTempRaw();
  if (!(flags & MEAS_PRS_RDY)) return false;
  int32_t candidateRawP = readPressureRaw();
  float candidateTempC = calcTemperatureC(rawT);
  float candidatePressurePa = calcPressurePa(candidateRawP, rawT);
  float candidateAltitudeCm =
      pressureToRelAlt_cm(candidatePressurePa, baselinePressure);

  // A short/noisy I2C read must not replace the last good sensor value.  The
  // estimator and logger deliberately use the held value between 128 Hz DPS368
  // conversions, so a fast loop never turns normal "not ready yet" status
  // into a missing/zero barometer trace.
  if (!isfinite(candidateTempC) || candidateTempC <= -80.0f ||
      candidateTempC >= 100.0f || !isfinite(candidatePressurePa) ||
      candidatePressurePa <= 1000.0f || candidatePressurePa >= 130000.0f ||
      !isfinite(candidateAltitudeCm) || fabsf(candidateAltitudeCm) >= 10000000.0f) {
    ++invalidSampleCount;
    lastError = "invalid sample or incomplete I2C read";
    return false;
  }
  rawP = candidateRawP;
  tempC = candidateTempC;
  pressurePa = candidatePressurePa;
  altitude_cm = candidateAltitudeCm;
  lastPressureReadUs = nowUs;
  sampleTimeUs = nowUs;
  ++validSampleCount;
  lastError = "ok";
  return true;
}

void BARO::printDiagnostics() const {
  Serial.print("DPS368_DIAG: initialized=");
  Serial.print(initialized ? "YES" : "NO");
  Serial.print(" address=0x");
  Serial.print(i2cAddress, HEX);
  Serial.print(" status=0x");
  Serial.print(lastStatus, HEX);
  Serial.print(" updates=");
  Serial.print(updateCount);
  Serial.print(" valid=");
  Serial.print(validSampleCount);
  Serial.print(" invalid=");
  Serial.print(invalidSampleCount);
  Serial.print(" pressure_pa=");
  Serial.print(pressurePa, 2);
  Serial.print(" altitude_m=");
  Serial.print(getAltitudeM(), 3);
  Serial.print(" error=");
  Serial.println(lastError);
}

bool BARO::isConnected() {
  return initialized;
}

bool BARO::hasValidSample() const {
  return initialized && isfinite(pressurePa) && pressurePa > 1000.0f &&
         pressurePa < 130000.0f && isfinite(tempC) && tempC > -80.0f &&
         tempC < 100.0f && isfinite(altitude_cm) && fabsf(altitude_cm) < 10000000.0f;
}

bool BARO::init() {
  initialized = false;
  lastError = "starting";
  dpsWire.setSCL(DPS368_SCL);
  dpsWire.setSDA(DPS368_SDA);
  dpsWire.begin();
  dpsWire.setClock(400000);  // 400kHz fast mode

  if (!selectAddress()) {
    lastError = "no DPS368 at 0x76 or 0x77";
    return false;
  }

  dpsWrite(REG_RESET, 0x09);
  delay(50);
  if (!waitForFlags(MEAS_SENSOR_RDY, 100) ||
      !waitForFlags(MEAS_COEF_RDY, 100)) {
    lastError = "sensor/coefficients not ready after reset";
    return false;
  }

  readCoefficients();

  // Maximum 128 Hz pressure rate with 1x oversampling. At this rate the
  // Kalman filter, rather than the sensor, performs temporal averaging.
  constexpr uint8_t kPressureCfg = 0x70;
  constexpr uint8_t kTemperatureCfg = 0x00;  // 1 Hz, 1x
  constexpr float kSingleSampleScale = 524288.0f;
  dpsWrite(REG_PRS_CFG, kPressureCfg);
  // The compensation coefficients are valid only for the sensor selected by
  // TMP_COEF_SRCE.  Preserve that read-only source bit instead of assuming
  // every DPS368 board uses the external/MEMS temperature sensor.
  uint8_t tempSource = dpsRead8(REG_COEF_SRCE) & 0x80;
  dpsWrite(REG_TMP_CFG, tempSource | kTemperatureCfg);
  kP = kSingleSampleScale;
  kT = kSingleSampleScale;

  // Result shifting is only valid above 8x oversampling; explicitly disable
  // it for the raw 1x configuration.
  uint8_t cfg = dpsRead8(REG_CFG_REG);
  cfg &= ~((1 << 2) | (1 << 3));
  dpsWrite(REG_CFG_REG, cfg);

  // Read the configuration back.  A failed I2C write must not silently leave
  // compensation using scale factors for a different sensor configuration.
  uint8_t appliedPrsCfg = dpsRead8(REG_PRS_CFG);
  uint8_t appliedTmpCfg = dpsRead8(REG_TMP_CFG);
  uint8_t appliedCfg = dpsRead8(REG_CFG_REG);
  if (appliedPrsCfg != kPressureCfg ||
      appliedTmpCfg != (uint8_t)(tempSource | kTemperatureCfg) ||
      (appliedCfg & ((1 << 2) | (1 << 3))) != 0) {
    lastError = "DPS368 configuration readback mismatch";
    return false;
  }

  // Start background mode
  dpsWrite(REG_MEAS_CFG, 0x07);

  // Average a complete second of pressure conversions for the launch
  // reference. A single conversion makes every later relative altitude carry
  // its quantization/noise error as a fixed offset.
  constexpr uint8_t kBaselineSamples = 128;
  float pressureSum = 0.0f;
  for (uint8_t i = 0; i < kBaselineSamples; ++i) {
    if (!waitForFlags(MEAS_PRS_RDY, 100)) {
      lastError = "pressure conversion not ready";
      return false;
    }
    rawP = readPressureRaw();
    if (!waitForFlags(MEAS_TMP_RDY, 100)) {
      lastError = "temperature conversion not ready";
      return false;
    }
    rawT = readTempRaw();
    float samplePressure = calcPressurePa(rawP, rawT);
    if (!isfinite(samplePressure) || samplePressure <= 1000.0f ||
        samplePressure >= 130000.0f) {
      lastError = "invalid baseline pressure/calibration";
      return false;
    }
    pressureSum += samplePressure;
    // MEAS_*_RDY remains asserted between background conversions on this
    // device. Waiting one ODR period prevents averaging the same register
    // value 64 times.
    if (i + 1 < kBaselineSamples) delay(8);
  }
  baselinePressure = pressureSum / kBaselineSamples;
  if (!isfinite(baselinePressure) || baselinePressure <= 1000.0f) {
    lastError = "invalid baseline pressure/calibration";
    return false;
  }
  lastError = "initialized; waiting for sample";
  return true;
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
  for (uint8_t i = 0; i < len; ++i) buf[i] = 0;
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

float BARO::pressureToRelAlt_cm(float P, float P0) {
  // The DPS368 reports die temperature, not free-stream air temperature.
  // Feeding it into an isothermal equation creates a thermal altitude drift.
  // ISA pressure altitude is substantially more stable over this vehicle's
  // operating range and only requires the pressure ratio.
  constexpr float kIsaAltitudeM = 44330.0f;
  constexpr float kIsaExponent = 0.190263f;
  float h = kIsaAltitudeM * (1.0f - powf(P / P0, kIsaExponent));
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
