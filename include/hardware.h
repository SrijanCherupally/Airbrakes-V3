#ifndef HARDWARE_H
#define HARDWARE_H

#include <Arduino.h>

#include "ODriveCAN.h"
#include "ODriveMCPCAN.hpp"
#include "baro.h"
#include "imu.h"
#include "rgb.h"

// ---------- RGB LED PINS ----------
#define LED_R 24
#define LED_G 23
#define LED_B 22

// ---------- CAN (MCP2515 on SPI0) PINS ----------
#define CAN_MISO 16
#define CAN_CS 17
#define CAN_SCK 18
#define CAN_MOSI 19
#define CAN_INT 20
#define MCP2515_CLK_HZ 20000000  // 20 MHz crystal (see lib/CAN, a fork of
                                 // sandeepmistry/CAN with 20 MHz support)
#define CAN_BAUDRATE 250000
#define ODRV_NODE_ID 0

// Global hardware instances (defined in hardware.cpp)
extern BARO baro;
extern IMU imu;
extern RGBLed led;
extern ODriveCAN odrv;

// ODrive telemetry (updated from CAN callbacks)
extern float motorvel;
extern float motorpos;
extern float motorcurrent;
extern float motor_cmd_pos;
extern uint32_t axisError;

void setupHardware();
void ledWrite(float r, float g, float b);

// ODrive helpers
void EnableOdrv();
void odrvPosition(float pos);
void serviceOdrive();
bool odriveHeartbeatFresh();

#endif  // HARDWARE_H
