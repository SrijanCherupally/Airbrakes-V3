#include "hardware.h"

#include <SPI.h>
#include <Wire.h>

#include "MCP2515.h"
#include "ODriveEnums.h"

// ---------- Global hardware instances ----------
BARO baro;
IMU imu;
RGBLed led(LED_R, LED_G, LED_B);
ODriveCAN odrv(wrap_can_intf(CAN), ODRV_NODE_ID);
Heartbeat_msg_t lastHeartbeat;

// ---------- ODrive telemetry ----------
float motorvel = 0.0f;
float motorpos = 0.0f;
float motorcurrent = 0.0f;
float motor_cmd_pos = 0.0f;
uint32_t axisError = 0;

static uint32_t lastFeedbackMs = 0;
static uint32_t lastVelocityCommandMs = 0;

// TEMPORARY ODrive CAN velocity test. ODrive velocity units are turns/second.
static constexpr float ODRIVE_TEST_VELOCITY_TURNS_PER_SECOND = 50.0f;
static constexpr uint32_t ODRIVE_TEST_COMMAND_PERIOD_MS = 50;

void onCanMessage(const CanMsg& msg) {
  odrv.onReceive(msg.id, msg.len, msg.buffer);
}

static void odriveFeedback(Get_Encoder_Estimates_msg_t& msg, void* user_data) {
  motorpos = msg.Pos_Estimate;
  motorvel = msg.Vel_Estimate;
  lastFeedbackMs = millis();
}

static void odriveCurrents(Get_Iq_msg_t& msg, void* user_data) {
  motorcurrent = msg.Iq_Measured;
}

void ledWrite(float r, float g, float b) {
  led.setColor(r, g, b);
}

void setupHardware() {
  Serial.begin(115200);

  ledWrite(0.04f, 0.04f, 0.04f);

  // DPS368 barometer (I2C). begin() probes both valid DPS368 addresses.
  if (!baro.begin()) {
    Serial.println("WARNING: DPS368 initialization failed");
  }

  // ICM42688 IMU (SPI1)
  while (!imu.begin()) {
    ledWrite(0.1f, 0.0f, 0.0f);
    Serial.println("IMU not found!");
    delay(1000);
  }

  // CAN (MCP2515 on SPI0)
  SPI.setMISO(CAN_MISO);
  SPI.setMOSI(CAN_MOSI);
  SPI.setSCK(CAN_SCK);
  SPI.begin(false);

  odrv.onFeedback(odriveFeedback, NULL);
  // Heartbeat processing is disabled during the temporary velocity test.
  // odrv.onStatus(odriveHeartbeat, NULL);
  odrv.onCurrents(odriveCurrents, NULL);

  CAN.setPins(CAN_CS, CAN_INT);
  CAN.setClockFrequency(MCP2515_CLK_HZ);

  if (!CAN.begin(CAN_BAUDRATE)) {
    while (1) {
      ledWrite(0.1f, 0.0f, 0.0f);
      Serial.println("CAN not found!");
      delay(1000);
    }
  }

  Serial.println("CAN setup complete");

  // Configure a direct velocity command over CAN. The ODrive must already be
  // calibrated and able to enter closed-loop control.
  odrv.clearErrors();
  odrv.setControllerMode(ODriveControlMode::CONTROL_MODE_VELOCITY_CONTROL,
                         ODriveInputMode::INPUT_MODE_PASSTHROUGH);
  odrv.setState(ODriveAxisState::AXIS_STATE_CLOSED_LOOP_CONTROL);
}

void EnableOdrv() {
  // The setup sequence already requested closed-loop control. Do not resend
  // state commands here: STATE_PAD invokes this function every update.
}

bool odriveHeartbeatFresh() {
  // Heartbeat monitoring is intentionally disabled during this test.
  return true;
}

void serviceOdrive() {
  pumpEvents(CAN);

  // Refresh the input at 20 Hz for an enabled ODrive watchdog without
  // flooding the 250 kbit/s CAN bus from the main loop.
  uint32_t nowMs = millis();
  if ((nowMs - lastVelocityCommandMs) >= ODRIVE_TEST_COMMAND_PERIOD_MS) {
    lastVelocityCommandMs = nowMs;
    odrv.setVelocity(ODRIVE_TEST_VELOCITY_TURNS_PER_SECOND);
  }
}

void odrvPosition(float pos) {
  motor_cmd_pos = pos;
  // Position commands are disabled so they cannot override the velocity test.
}
