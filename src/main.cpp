#include <Arduino.h>
#include <SPI.h>
#include <CAN.h>

// This firmware is intentionally a single-purpose ODrive CAN test.  The
// values in this block are the only board/motor settings that normally need
// changing.
namespace config {
constexpr uint8_t kCanMisoPin = 16;
constexpr uint8_t kCanCsPin = 17;
constexpr uint8_t kCanSckPin = 18;
constexpr uint8_t kCanMosiPin = 19;
constexpr uint8_t kCanIntPin = 20;
constexpr uint32_t kMcp2515ClockHz = 16000000;
constexpr long kCanBaudRate = 250000;

constexpr uint8_t kODriveNodeId = 0;
constexpr float kStartupVelocityTurnsPerSecond = 1.0f;
constexpr float kTorqueFeedForwardNm = 0.0f;

constexpr uint32_t kCommandPeriodMs = 100;
constexpr uint32_t kEnableRetryPeriodMs = 1000;
constexpr uint32_t kHeartbeatTimeoutMs = 500;
constexpr uint32_t kStatusPeriodMs = 1000;
}  // namespace config

namespace odrive {
constexpr uint8_t kCommandMask = 0x1F;
constexpr uint8_t kHeartbeat = 0x01;
constexpr uint8_t kGetEncoderEstimates = 0x09;
constexpr uint8_t kSetControllerMode = 0x0B;
constexpr uint8_t kSetInputVelocity = 0x0D;
constexpr uint8_t kGetIq = 0x14;
constexpr uint8_t kClearErrors = 0x18;
constexpr uint8_t kSetAxisState = 0x07;

constexpr uint32_t kAxisStateClosedLoopControl = 8;
constexpr uint32_t kControlModeVelocity = 2;
constexpr uint32_t kInputModePassthrough = 1;
}  // namespace odrive

struct CanFrame {
  uint32_t id;
  uint8_t length;
  uint8_t data[8];
};

// MCP2515 receive callbacks run from the interrupt handler.  Keep that work
// short and defer decoding and all Serial output to loop().
constexpr uint8_t kReceiveQueueSize = 16;
volatile CanFrame receiveQueue[kReceiveQueueSize];
volatile uint8_t receiveHead = 0;
volatile uint8_t receiveTail = 0;
volatile uint32_t droppedReceiveFrames = 0;

uint32_t lastHeartbeatMs = 0;
uint32_t lastEnableRequestMs = 0;
uint32_t lastVelocityCommandMs = 0;
uint32_t lastStatusMs = 0;
uint32_t receivedFrames = 0;
uint32_t transmitFailures = 0;

uint32_t axisError = 0;
uint8_t axisState = 0;
float encoderPosition = 0.0f;
float encoderVelocity = 0.0f;
float measuredCurrent = 0.0f;
bool receivedEncoderEstimate = false;
bool motorEnabled = true;
bool traceReceivedFrames = true;
bool traceTransmittedFrames = false;
float targetVelocity = config::kStartupVelocityTurnsPerSecond;

uint32_t odriveId(uint8_t command) {
  return (static_cast<uint32_t>(config::kODriveNodeId) << 5) | command;
}

uint32_t readU32Le(const uint8_t* data) {
  return static_cast<uint32_t>(data[0]) |
         (static_cast<uint32_t>(data[1]) << 8) |
         (static_cast<uint32_t>(data[2]) << 16) |
         (static_cast<uint32_t>(data[3]) << 24);
}

float readFloatLe(const uint8_t* data) {
  float value;
  memcpy(&value, data, sizeof(value));
  return value;
}

void writeU32Le(uint8_t* data, uint32_t value) {
  data[0] = static_cast<uint8_t>(value);
  data[1] = static_cast<uint8_t>(value >> 8);
  data[2] = static_cast<uint8_t>(value >> 16);
  data[3] = static_cast<uint8_t>(value >> 24);
}

void writeFloatLe(uint8_t* data, float value) {
  memcpy(data, &value, sizeof(value));
}

void printFrame(const char* direction, const CanFrame& frame) {
  Serial.print(direction);
  Serial.print(F(" id=0x"));
  Serial.print(frame.id, HEX);
  Serial.print(F(" len="));
  Serial.print(frame.length);
  Serial.print(F(" data="));
  for (uint8_t i = 0; i < frame.length; ++i) {
    if (frame.data[i] < 16) Serial.print('0');
    Serial.print(frame.data[i], HEX);
    if (i + 1 != frame.length) Serial.print(' ');
  }
  Serial.println();
}

bool sendFrame(uint8_t command, const uint8_t* data, uint8_t length,
               const char* label) {
  CanFrame frame = {odriveId(command), length, {0}};
  if (data != nullptr && length != 0) {
    memcpy(frame.data, data, length);
  }

  if (!CAN.beginPacket(frame.id, frame.length)) {
    ++transmitFailures;
    Serial.print(F("TX begin failed: "));
    Serial.println(label);
    return false;
  }
  if (frame.length != 0 && CAN.write(frame.data, frame.length) != frame.length) {
    ++transmitFailures;
    Serial.print(F("TX write failed: "));
    Serial.println(label);
    CAN.endPacket();
    return false;
  }
  if (!CAN.endPacket()) {
    ++transmitFailures;
    Serial.print(F("TX failed: "));
    Serial.println(label);
    return false;
  }
  if (traceTransmittedFrames) printFrame("TX", frame);
  return true;
}

void sendClearErrors() {
  const uint8_t identify = 0;
  sendFrame(odrive::kClearErrors, &identify, 1, "Clear_Errors");
}

void sendVelocityMode() {
  uint8_t data[8] = {};
  writeU32Le(data, odrive::kControlModeVelocity);
  writeU32Le(data + 4, odrive::kInputModePassthrough);
  sendFrame(odrive::kSetControllerMode, data, sizeof(data),
            "Set_Controller_Mode");
}

void sendClosedLoopRequest() {
  uint8_t data[4] = {};
  writeU32Le(data, odrive::kAxisStateClosedLoopControl);
  sendFrame(odrive::kSetAxisState, data, sizeof(data), "Set_Axis_State");
}

void sendVelocity(float velocity) {
  uint8_t data[8] = {};
  writeFloatLe(data, velocity);
  writeFloatLe(data + 4, config::kTorqueFeedForwardNm);
  sendFrame(odrive::kSetInputVelocity, data, sizeof(data), "Set_Input_Vel");
}

void queueReceivedFrame(int packetLength) {
  const uint8_t length = static_cast<uint8_t>(min(packetLength, 8));
  const uint8_t nextHead = (receiveHead + 1) % kReceiveQueueSize;
  if (nextHead == receiveTail) {
    ++droppedReceiveFrames;
    while (CAN.available()) CAN.read();
    return;
  }

  volatile CanFrame& frame = receiveQueue[receiveHead];
  frame.id = static_cast<uint32_t>(CAN.packetId());
  frame.length = length;
  for (uint8_t i = 0; i < length; ++i) {
    frame.data[i] = static_cast<uint8_t>(CAN.read());
  }
  while (CAN.available()) CAN.read();
  receiveHead = nextHead;
}

bool dequeueReceivedFrame(CanFrame& frame) {
  noInterrupts();
  if (receiveTail == receiveHead) {
    interrupts();
    return false;
  }
  const volatile CanFrame& queued = receiveQueue[receiveTail];
  frame.id = queued.id;
  frame.length = queued.length;
  for (uint8_t i = 0; i < frame.length; ++i) frame.data[i] = queued.data[i];
  receiveTail = (receiveTail + 1) % kReceiveQueueSize;
  interrupts();
  return true;
}

void processReceivedFrame(const CanFrame& frame) {
  ++receivedFrames;
  if (traceReceivedFrames) printFrame("RX", frame);

  if ((frame.id >> 5) != config::kODriveNodeId) return;

  switch (frame.id & odrive::kCommandMask) {
    case odrive::kHeartbeat:
      if (frame.length >= 6) {
        axisError = readU32Le(frame.data);
        axisState = frame.data[4];
        lastHeartbeatMs = millis();
      }
      break;
    case odrive::kGetEncoderEstimates:
      if (frame.length == 8) {
        encoderPosition = readFloatLe(frame.data);
        encoderVelocity = readFloatLe(frame.data + 4);
        receivedEncoderEstimate = true;
      }
      break;
    case odrive::kGetIq:
      if (frame.length == 8) measuredCurrent = readFloatLe(frame.data + 4);
      break;
    default:
      break;
  }
}

bool heartbeatIsFresh(uint32_t now) {
  return lastHeartbeatMs != 0 && now - lastHeartbeatMs <= config::kHeartbeatTimeoutMs;
}

void requestMotorStart() {
  Serial.println(F("Requesting ODrive velocity closed-loop control"));
  sendClearErrors();
  sendVelocityMode();
  sendClosedLoopRequest();
}

void printHelp() {
  Serial.println(F("Commands: h help | + / - adjust velocity by 0.25 rev/s | 0 stop | s toggle motor | c clear errors + re-enable | r MCP2515 registers | t RX trace | x TX trace"));
}

void handleSerial() {
  while (Serial.available()) {
    const char command = static_cast<char>(Serial.read());
    switch (command) {
      case 'h': case '?': printHelp(); break;
      case '+': targetVelocity += 0.25f; break;
      case '-': targetVelocity -= 0.25f; break;
      case '0': targetVelocity = 0.0f; motorEnabled = false; sendVelocity(0.0f); break;
      case 's':
        motorEnabled = !motorEnabled;
        Serial.println(motorEnabled ? F("Motor command enabled") : F("Motor command stopped"));
        if (!motorEnabled) sendVelocity(0.0f);
        break;
      case 'c': requestMotorStart(); break;
      case 'r': CAN.dumpRegisters(Serial); break;
      case 't':
        traceReceivedFrames = !traceReceivedFrames;
        Serial.println(traceReceivedFrames ? F("RX tracing enabled") : F("RX tracing disabled"));
        break;
      case 'x':
        traceTransmittedFrames = !traceTransmittedFrames;
        Serial.println(traceTransmittedFrames ? F("TX tracing enabled") : F("TX tracing disabled"));
        break;
      case '\r': case '\n': case ' ': break;
      default:
        Serial.print(F("Unknown command: "));
        Serial.println(command);
        printHelp();
        break;
    }
  }
}

void printStatus(uint32_t now) {
  if (now - lastStatusMs < config::kStatusPeriodMs) return;
  lastStatusMs = now;

  Serial.print(F("STATUS heartbeat="));
  Serial.print(heartbeatIsFresh(now) ? F("fresh") : F("missing"));
  Serial.print(F(" state="));
  Serial.print(axisState);
  Serial.print(F(" error=0x"));
  Serial.print(axisError, HEX);
  Serial.print(F(" target_rev_s="));
  Serial.print(targetVelocity, 3);
  Serial.print(F(" enabled="));
  Serial.print(motorEnabled ? F("yes") : F("no"));
  if (receivedEncoderEstimate) {
    Serial.print(F(" pos_rev="));
    Serial.print(encoderPosition, 3);
    Serial.print(F(" vel_rev_s="));
    Serial.print(encoderVelocity, 3);
    Serial.print(F(" iq_A="));
    Serial.print(measuredCurrent, 3);
  } else {
    Serial.print(F(" encoder=not configured"));
  }
  Serial.print(F(" rx="));
  Serial.print(receivedFrames);
  Serial.print(F(" drop="));
  Serial.print(droppedReceiveFrames);
  Serial.print(F(" tx_fail="));
  Serial.println(transmitFailures);
}

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < 30 && !Serial; ++i) delay(100);

  Serial.println(F("\nODrive CAN constant-velocity test"));
  Serial.print(F("CAN="));
  Serial.print(config::kCanBaudRate);
  Serial.print(F(" node="));
  Serial.print(config::kODriveNodeId);
  Serial.print(F(" startup_velocity_rev_s="));
  Serial.println(targetVelocity, 3);

  SPI.setMISO(config::kCanMisoPin);
  SPI.setMOSI(config::kCanMosiPin);
  SPI.setSCK(config::kCanSckPin);
  SPI.begin(false);

  CAN.setPins(config::kCanCsPin, config::kCanIntPin);
  CAN.setClockFrequency(config::kMcp2515ClockHz);
  if (!CAN.begin(config::kCanBaudRate)) {
    Serial.println(F("FATAL: MCP2515 initialization failed. Check SPI pins, CS/INT, and the 16 MHz oscillator."));
    while (true) delay(1000);
  }
  CAN.onReceive(queueReceivedFrame);
  Serial.println(F("MCP2515 ready. Waiting for ODrive heartbeat..."));
  printHelp();
}

void loop() {
  CanFrame frame;
  while (dequeueReceivedFrame(frame)) processReceivedFrame(frame);
  handleSerial();

  const uint32_t now = millis();
  if (heartbeatIsFresh(now)) {
    if (axisError != 0) {
      // Do not continuously clear a fault: preserve it for diagnosis. 'c' is
      // the explicit operator action to clear and retry.
    } else if (axisState != odrive::kAxisStateClosedLoopControl &&
               now - lastEnableRequestMs >= config::kEnableRetryPeriodMs) {
      lastEnableRequestMs = now;
      requestMotorStart();
    } else if (axisState == odrive::kAxisStateClosedLoopControl &&
               now - lastVelocityCommandMs >= config::kCommandPeriodMs) {
      lastVelocityCommandMs = now;
      sendVelocity(motorEnabled ? targetVelocity : 0.0f);
    }
  }

  printStatus(now);
}
