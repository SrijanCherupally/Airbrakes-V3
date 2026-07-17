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

static uint32_t lastHeartbeatMs = 0;
static uint32_t lastFeedbackMs = 0;
static uint32_t lastEnableRequestMs = 0;

static constexpr uint32_t HEARTBEAT_TIMEOUT_MS = 350;
static constexpr uint32_t FEEDBACK_TIMEOUT_MS = 350;
static constexpr uint32_t ENABLE_RETRY_MS = 100;

static inline void canCallback(int packet_size) {
  if (packet_size > 8) {
    return;  // not supported
  }
  CanMsg msg = {.id = (unsigned int)CAN.packetId(),
                .len = (uint8_t)packet_size};
  CAN.readBytes(msg.buffer, packet_size);
  onReceive(msg, odrv);
}

static void odriveFeedback(Get_Encoder_Estimates_msg_t& msg, void* user_data) {
  motorpos = msg.Pos_Estimate;
  motorvel = msg.Vel_Estimate;
  lastFeedbackMs = millis();
}

static void odriveCurrents(Get_Iq_msg_t& msg, void* user_data) {
  motorcurrent = msg.Iq_Measured;
}

static void odriveHeartbeat(Heartbeat_msg_t& msg, void* user_data) {
  lastHeartbeat = msg;
  lastHeartbeatMs = millis();
  axisError = msg.Axis_Error;
}

void ledWrite(float r, float g, float b) {
  led.setColor(r, g, b);
}

void setupHardware() {
  Serial.begin(115200);

  ledWrite(0.04f, 0.04f, 0.04f);

  // DPS368 barometer (I2C). begin() configures the Wire bus internally.
  baro.begin();
  if (!baro.isConnected()) {
    Serial.println("WARNING: DPS368 not detected");
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
  odrv.onStatus(odriveHeartbeat, NULL);
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

  CAN.onReceive(canCallback);

  // TEMP DEBUG: also poll manually so we can tell whether the INT pin is
  // the problem (frames arrive but interrupt never fires) vs. genuinely
  // no traffic on the bus at all. Remove once heartbeat issue is solved.
  Serial.println("CAN setup complete, entering poll-test mode");
}

void pollCanDebug() {
  int packetSize = CAN.parsePacket();
  if (packetSize) {
    Serial.print("POLL: CAN RX id=0x");
    Serial.print(CAN.packetId(), HEX);
    Serial.print(" len=");
    Serial.println(packetSize);
  }
}

void EnableOdrv() {
  serviceOdrive();

  if (!odriveHeartbeatFresh()) {
    return;
  }

  // Enable closed-loop
  if (lastHeartbeat.Axis_State ==
      ODriveAxisState::AXIS_STATE_CLOSED_LOOP_CONTROL) {
    return;
  }
  odrv.clearErrors();
  delay(1);
  odrv.setState(ODriveAxisState::AXIS_STATE_CLOSED_LOOP_CONTROL);
  // Pump events for 150ms. This delay is needed for two reasons;
  // 1. If there is an error condition, such as missing DC power, the ODrive
  //    might briefly attempt to enter CLOSED_LOOP_CONTROL state, so we can't
  //    rely on the first heartbeat response, so we want to receive at least
  //    two heartbeats (100ms default interval).
  // 2. If the bus is congested, the setState command won't get through
  //    immediately but can be delayed.
  for (int i = 0; i < 15; ++i) {
    delay(10);
    pumpEvents(CAN);
  }

  // If in error, read out error (print human-readable names)
  if (lastHeartbeat.Axis_State == ODriveAxisState::AXIS_STATE_IDLE &&
      lastHeartbeat.Axis_Error != 0) {
    Serial.print("ODrive error: ");
    uint32_t e = lastHeartbeat.Axis_Error;
    bool any = false;
    if (e & ODRIVE_ERROR_INITIALIZING) {
      if (any) Serial.print(", ");
      Serial.print("INITIALIZING");
      any = true;
    }
    if (e & ODRIVE_ERROR_SYSTEM_LEVEL) {
      if (any) Serial.print(", ");
      Serial.print("SYSTEM_LEVEL");
      any = true;
    }
    if (e & ODRIVE_ERROR_TIMING_ERROR) {
      if (any) Serial.print(", ");
      Serial.print("TIMING_ERROR");
      any = true;
    }
    if (e & ODRIVE_ERROR_MISSING_ESTIMATE) {
      if (any) Serial.print(", ");
      Serial.print("MISSING_ESTIMATE");
      any = true;
    }
    if (e & ODRIVE_ERROR_BAD_CONFIG) {
      if (any) Serial.print(", ");
      Serial.print("BAD_CONFIG");
      any = true;
    }
    if (e & ODRIVE_ERROR_DRV_FAULT) {
      if (any) Serial.print(", ");
      Serial.print("DRV_FAULT");
      any = true;
    }
    if (e & ODRIVE_ERROR_MISSING_INPUT) {
      if (any) Serial.print(", ");
      Serial.print("MISSING_INPUT");
      any = true;
    }
    if (e & ODRIVE_ERROR_DC_BUS_OVER_VOLTAGE) {
      if (any) Serial.print(", ");
      Serial.print("DC_BUS_OVER_VOLTAGE");
      any = true;
    }
    if (e & ODRIVE_ERROR_DC_BUS_UNDER_VOLTAGE) {
      if (any) Serial.print(", ");
      Serial.print("DC_BUS_UNDER_VOLTAGE");
      any = true;
    }
    if (e & ODRIVE_ERROR_DC_BUS_OVER_CURRENT) {
      if (any) Serial.print(", ");
      Serial.print("DC_BUS_OVER_CURRENT");
      any = true;
    }
    if (e & ODRIVE_ERROR_DC_BUS_OVER_REGEN_CURRENT) {
      if (any) Serial.print(", ");
      Serial.print("DC_BUS_OVER_REGEN_CURRENT");
      any = true;
    }
    if (e & ODRIVE_ERROR_CURRENT_LIMIT_VIOLATION) {
      if (any) Serial.print(", ");
      Serial.print("CURRENT_LIMIT_VIOLATION");
      any = true;
    }
    if (e & ODRIVE_ERROR_MOTOR_OVER_TEMP) {
      if (any) Serial.print(", ");
      Serial.print("MOTOR_OVER_TEMP");
      any = true;
    }
    if (e & ODRIVE_ERROR_INVERTER_OVER_TEMP) {
      if (any) Serial.print(", ");
      Serial.print("INVERTER_OVER_TEMP");
      any = true;
    }
    if (e & ODRIVE_ERROR_VELOCITY_LIMIT_VIOLATION) {
      if (any) Serial.print(", ");
      Serial.print("VELOCITY_LIMIT_VIOLATION");
      any = true;
    }
    if (e & ODRIVE_ERROR_POSITION_LIMIT_VIOLATION) {
      if (any) Serial.print(", ");
      Serial.print("POSITION_LIMIT_VIOLATION");
      any = true;
    }
    if (e & ODRIVE_ERROR_WATCHDOG_TIMER_EXPIRED) {
      if (any) Serial.print(", ");
      Serial.print("WATCHDOG_TIMER_EXPIRED");
      any = true;
    }
    if (e & ODRIVE_ERROR_ESTOP_REQUESTED) {
      if (any) Serial.print(", ");
      Serial.print("ESTOP_REQUESTED");
      any = true;
    }
    if (e & ODRIVE_ERROR_SPINOUT_DETECTED) {
      if (any) Serial.print(", ");
      Serial.print("SPINOUT_DETECTED");
      any = true;
    }
    if (e & ODRIVE_ERROR_BRAKE_RESISTOR_DISARMED) {
      if (any) Serial.print(", ");
      Serial.print("BRAKE_RESISTOR_DISARMED");
      any = true;
    }
    if (e & ODRIVE_ERROR_THERMISTOR_DISCONNECTED) {
      if (any) Serial.print(", ");
      Serial.print("THERMISTOR_DISCONNECTED");
      any = true;
    }
    if (e & ODRIVE_ERROR_CALIBRATION_ERROR) {
      if (any) Serial.print(", ");
      Serial.print("CALIBRATION_ERROR");
      any = true;
    }
    if (!any) {
      // Unknown bits set, fall back to hex
      Serial.print("0x");
      Serial.println(e, HEX);
    } else {
      Serial.println();
    }
  }
}

bool odriveHeartbeatFresh() {
  return (millis() - lastHeartbeatMs) <= HEARTBEAT_TIMEOUT_MS;
}

void serviceOdrive() {
  pumpEvents(CAN);

  uint32_t nowMs = millis();
  bool heartbeatFresh = (nowMs - lastHeartbeatMs) <= HEARTBEAT_TIMEOUT_MS;
  bool feedbackFresh = (nowMs - lastFeedbackMs) <= FEEDBACK_TIMEOUT_MS;

  // If heartbeat/feedback has gone stale or axis is not closed-loop,
  // periodically request closed-loop mode again.
  if (!heartbeatFresh || !feedbackFresh ||
      lastHeartbeat.Axis_State !=
          ODriveAxisState::AXIS_STATE_CLOSED_LOOP_CONTROL) {
    if ((nowMs - lastEnableRequestMs) >= ENABLE_RETRY_MS) {
      lastEnableRequestMs = nowMs;
      odrv.clearErrors();
      odrv.setState(ODriveAxisState::AXIS_STATE_CLOSED_LOOP_CONTROL);
    }
  }
}

void odrvPosition(float pos) {
  motor_cmd_pos = pos;
  serviceOdrive();

  if (!odriveHeartbeatFresh()) {
    return;
  }

  if (lastHeartbeat.Axis_State !=
      ODriveAxisState::AXIS_STATE_CLOSED_LOOP_CONTROL) {
    return;
  }

  odrv.setPosition(pos);
}