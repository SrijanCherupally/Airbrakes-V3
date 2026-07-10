#include <Arduino.h>
#include <SPI.h>
#include <math.h>

// ---------- PIN DEFINES ----------
#define DPS368_CS   17
#define DPS368_SCK  18
#define DPS368_MOSI 19
#define DPS368_MISO 16
#define dpsSPI SPI

// ---------- REGISTERS ----------
#define REG_PRS_B2     0x00
#define REG_TMP_B2     0x03
#define REG_PRS_CFG    0x06
#define REG_TMP_CFG    0x07
#define REG_MEAS_CFG   0x08
#define REG_CFG_REG    0x09
#define REG_RESET      0x0C
#define REG_PROD_ID    0x0D
#define REG_COEF       0x10

// ---------- MEAS_CFG FLAGS ----------
#define MEAS_SENSOR_RDY (1u << 7)
#define MEAS_COEF_RDY   (1u << 6)
#define MEAS_TMP_RDY    (1u << 5)
#define MEAS_PRS_RDY    (1u << 4)


class BARO 
{
public:
  BARO() {}

  void begin() {
    Serial.begin(115200);
    delay(200);
    Serial.println("DPS368 Initialized");
    init();
  }

  bool update() {
    if (!waitForFlags(MEAS_PRS_RDY | MEAS_TMP_RDY, 100)) return false;
    rawT = readTempRaw();
    rawP = readPressureRaw();
    tempC = calcTemperatureC(rawT);
    pressurePa = calcPressurePa(rawP, rawT);
    altitude_cm = pressureToRelAlt_cm(pressurePa, baselinePressure, tempC + 273.15f);
    return true;
  }

  bool isConnected() {
    uint8_t prodId = dpsRead8(REG_PROD_ID);
    return prodId == 0x10; // DPS368 product ID is 0x10
  }

  float getTemperatureC() const { return tempC; }
  float getPressurePa() const { return pressurePa; }
  float getAltitudeCm() const { return altitude_cm; }
  float getBaselinePressure() const { return baselinePressure; }

private:
  // Calibration coefficients
  int16_t c0, c1;
  int32_t c00, c10;
  int16_t c01, c11, c20, c21, c30;

  float kT = 524288.0f; // OSR=8
  float kP = 524288.0f; // OSR=8

  float baselinePressure = 0.0f;
  const float R = 287.05f;
  const float g = 9.80665f;

  int32_t rawT = 0, rawP = 0;
  float tempC = 0.0f, pressurePa = 0.0f, altitude_cm = 0.0f;

  void init() {
    pinMode(DPS368_CS, OUTPUT);
    digitalWrite(DPS368_CS, HIGH);

    dpsSPI.setSCK(DPS368_SCK);
    dpsSPI.setTX(DPS368_MOSI);
    dpsSPI.setRX(DPS368_MISO);
    dpsSPI.begin();
    dpsSPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));

    dpsWrite(REG_RESET, 0x09);
    delay(50);
    waitForFlags(MEAS_SENSOR_RDY, 100);
    waitForFlags(MEAS_COEF_RDY, 100);

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
    waitForFlags(MEAS_PRS_RDY | MEAS_TMP_RDY, 100);
    rawT = readTempRaw();
    rawP = readPressureRaw();
    baselinePressure = calcPressurePa(rawP, rawT);
  }

  // SPI helpers
  void dpsWrite(uint8_t reg, uint8_t val) {
    digitalWrite(DPS368_CS, LOW);
    dpsSPI.transfer(reg & 0x7F);
    dpsSPI.transfer(val);
    digitalWrite(DPS368_CS, HIGH);
  }

  uint8_t dpsRead8(uint8_t reg) {
    digitalWrite(DPS368_CS, LOW);
    dpsSPI.transfer(reg | 0x80);
    uint8_t val = dpsSPI.transfer(0x00);
    digitalWrite(DPS368_CS, HIGH);
    return val;
  }

  void dpsReadBlock(uint8_t reg, uint8_t *buf, uint8_t len) {
    digitalWrite(DPS368_CS, LOW);
    dpsSPI.transfer(reg | 0x80);
    for (uint8_t i = 0; i < len; i++) buf[i] = dpsSPI.transfer(0x00);
    digitalWrite(DPS368_CS, HIGH);
  }

  int32_t readRaw24(uint8_t reg) {
    uint8_t b[3];
    dpsReadBlock(reg, b, 3);
    int32_t x = ((int32_t)b[0] << 16) | ((int32_t)b[1] << 8) | b[2];
    if (x & 0x800000) x |= 0xFF000000; // sign-extend
    return x;
  }

  int32_t readPressureRaw() { return readRaw24(REG_PRS_B2); }
  int32_t readTempRaw()     { return readRaw24(REG_TMP_B2); }

  void readCoefficients() {
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

    c01 = (int16_t)((buf[8]  << 8) | buf[9]);
    c11 = (int16_t)((buf[10] << 8) | buf[11]);
    c20 = (int16_t)((buf[12] << 8) | buf[13]);
    c21 = (int16_t)((buf[14] << 8) | buf[15]);
    c30 = (int16_t)((buf[16] << 8) | buf[17]);
  }

  float calcTemperatureC(int32_t rawT) {
    return (float)c0 * 0.5f + (float)c1 * ((float)rawT / kT);
  }

  float calcPressurePa(int32_t rawP, int32_t rawT) {
    float Praw = rawP / kP;
    float Traw = rawT / kT;
    return (float)c00
      + Praw * ((float)c10 + Praw * ((float)c20 + Praw * (float)c30))
      + Traw * ((float)c01 + Praw * ((float)c11 + Praw * (float)c21));
  }

  float pressureToRelAlt_cm(float P, float P0, float T_K) {
    float h = - (R * T_K / g) * logf(P / P0);
    return h * 100.0f;
  }

  float getAltitudeFeet(float P, float P0, float T_K) {
    float h_m = - (R * T_K / g) * logf(P / P0);
    return h_m * 3.28084f;
  }

  bool waitForFlags(uint8_t mask, uint32_t timeout_ms) {
    uint32_t t0 = millis();
    while (millis() - t0 < timeout_ms) {
      uint8_t m = dpsRead8(REG_MEAS_CFG);
      if ((m & mask) == mask) return true;
    }
    return false;
  }
};