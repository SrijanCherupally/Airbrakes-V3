#ifndef FLASH_H
#define FLASH_H

#include <Arduino.h>

void initFlash();
void logFlightData(float altitude, float velocity, float accelBias,
                   float rawAccel, float rawBaro, float motorPos,
                   float motorVel, float motorCmdPos, float Cd, float desiredCd,
                   float motorCurrent, float batteryVoltage, uint32_t axisError);
void flushLogBuffer();  // Flush RAM buffer to flash
void finalizeFlightLog();  // Flush and close the active log file
void handleFlashCommands();
bool checkStorageWarning();  // Returns true if low storage warning is active

#endif  // FLASH_H