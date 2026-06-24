#ifndef HARDWARE_H
#define HARDWARE_H

// #include "dps368.h"
#include "ODriveCAN.h"
#include "ODriveMCPCAN.hpp"
#include "icm42688.h"

#define LEDR 24
#define LEDG 22
#define LEDB 23

#define IMU_SCK 10
#define IMU_MOSI 11
#define IMU_MISO 8
#define IMU_CS 9

#define CAN_MISO 16
#define CAN_CS 17
#define CAN_SCK 18
#define CAN_MOSI 19
#define CAN_INT 20
#define MCP2515_CLK_HZ 16000000
#define CAN_BAUDRATE 250000
#define ODRV_NODE_ID 0

#define BARO_SDA 4
#define BARO_SCL 5

extern HP203B hp;
extern Mpu6500 mpu;
extern ODriveCAN odrv;
extern float motorvel;
extern float motorpos;
extern float motorcurrent;
extern float motor_cmd_pos;
extern uint32_t axisError;

extern void ledWrite(float r, float g, float b);
void setupHardware();
void EnableOdrv();
void odrvPosition(float pos);
void serviceOdrive();
bool odriveHeartbeatFresh();

#endif  // HARDWARE_H