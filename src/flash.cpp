/*
#include "flash.h"

#include <LittleFS.h>

//#include "estimator.h"
//#include "state.h"

// Binary data structure (68 bytes per record)
struct __attribute__((packed)) FlightRecord {
  uint32_t time_ms;
  float altitude_m;
  float velocity_ms;
  float accel_bias_ms2;
  float raw_accel_ms2;
  float raw_baro_m;
  float motor_pos;
  float motor_vel;
  float motor_cmd_pos;
  float roll_rad;
  float pitch_rad;
  float yaw_rad;
  float Cd;
  float desired_Cd;
  float motor_current;
  uint32_t state;
  uint32_t axis_error;
};

// RAM buffer for non-blocking writes
#define BUFFER_SIZE 768  // 768 records = 52KB buffer (~7.7 seconds at 100Hz)
static FlightRecord writeBuffer[BUFFER_SIZE];
static volatile int bufferHead = 0;
static volatile int bufferTail = 0;

static File dataFile;
static unsigned long logStartTime = 0;
static int flightNumber = 0;
static String commandBuffer = "";
static unsigned long lowStorageWarningStart = 0;
static bool lowStorageWarningActive = false;

#define LOW_STORAGE_THRESHOLD (4 * 1024 * 1024)  // 4MB
#define WARNING_DURATION 10000                   // 10 seconds

static bool fsInitialized = false;  // Track if filesystem is mounted

void initFlash() {
  // Mount filesystem if not already mounted
  if (!fsInitialized) {
    if (!LittleFS.begin()) {
      Serial.println("Failed to mount filesystem");
      return;
    }
    fsInitialized = true;
  }

  // Check storage
  FSInfo fs_info;
  LittleFS.info(fs_info);
  size_t freeSpace = fs_info.totalBytes - fs_info.usedBytes;

  Serial.print("Flash storage: ");
  Serial.print(freeSpace / 1024);
  Serial.print(" KB free / ");
  Serial.print(fs_info.totalBytes / 1024);
  Serial.println(" KB total");

  if (freeSpace < LOW_STORAGE_THRESHOLD) {
    Serial.println("WARNING: Low storage (<4MB free)");
    lowStorageWarningActive = true;
    lowStorageWarningStart = millis();
  }

  // Find next available flight number (but don't create file yet)
  flightNumber = 0;  // Reset to 0 to enumerate from the beginning
  while (true) {
    String filename = "/flight_" + String(flightNumber) + ".bin";
    if (!LittleFS.exists(filename)) {
      break;
    }
    flightNumber++;
  }

  Serial.print("Ready to log flight ");
  Serial.println(flightNumber);
  // File will be created on first log entry (when STATE_BOOST/CONTROL/DESCENT
  // starts)
  logStartTime = 0;
}

bool checkStorageWarning() {
  if (lowStorageWarningActive) {
    unsigned long elapsed = millis() - lowStorageWarningStart;
    if (elapsed >= WARNING_DURATION) {
      lowStorageWarningActive = false;
    }
    return true;
  }
  return false;
}

void logFlightData(float altitude, float velocity, float accelBias,
                   float rawAccel, float rawBaro, float motorPos,
                   float motorVel, float motorCmdPos, float Cd, float desiredCd,
                   float motorCurrent, uint32_t axisError) {
  // Create file on first log entry (lazy initialization)
  if (!dataFile) {
    if (!fsInitialized) return;  // Filesystem not ready

    String filename = "/flight_" + String(flightNumber) + ".bin";
    dataFile = LittleFS.open(filename, "w");

    if (dataFile) {
      Serial.print("Started logging to: ");
      Serial.println(filename);
    } else {
      Serial.println("Failed to open file for writing");
      return;
    }
  }

  // Rate limit to 100Hz
  static uint32_t lastLogTime = 0;
  if (millis() - lastLogTime < 10) {  // 100Hz = 10ms period
    return;
  }
  lastLogTime = millis();

  // Set log start time on first actual log entry (when STATE_BOOST starts)
  if (logStartTime == 0) {
    logStartTime = millis();
  }

  // Get orientation at 100Hz instead of every loop iteration
  float roll, pitch, yaw;
  GetOrientation(&roll, &pitch, &yaw);

  // Add to RAM buffer (non-blocking)
  int nextHead = (bufferHead + 1) % BUFFER_SIZE;
  if (nextHead == bufferTail) {
    // Buffer full - force flush now
    flushLogBuffer();
    // Try again after flush
    nextHead = (bufferHead + 1) % BUFFER_SIZE;
    if (nextHead == bufferTail) return;  // Still full, skip
  }

  writeBuffer[bufferHead].time_ms = millis() - logStartTime;
  writeBuffer[bufferHead].altitude_m = altitude;
  writeBuffer[bufferHead].velocity_ms = velocity;
  writeBuffer[bufferHead].accel_bias_ms2 = accelBias;
  writeBuffer[bufferHead].raw_accel_ms2 = rawAccel;
  writeBuffer[bufferHead].raw_baro_m = rawBaro;
  writeBuffer[bufferHead].motor_pos = motorPos;
  writeBuffer[bufferHead].motor_vel = motorVel;
  writeBuffer[bufferHead].motor_cmd_pos = motorCmdPos;
  writeBuffer[bufferHead].roll_rad = roll;
  writeBuffer[bufferHead].pitch_rad = pitch;
  writeBuffer[bufferHead].yaw_rad = yaw;
  writeBuffer[bufferHead].Cd = Cd;
  writeBuffer[bufferHead].desired_Cd = desiredCd;
  writeBuffer[bufferHead].motor_current = motorCurrent;
  writeBuffer[bufferHead].state = (uint32_t)currentState;
  writeBuffer[bufferHead].axis_error = axisError;

  bufferHead = nextHead;
}

void flushLogBuffer() {
  // Write buffered data to flash (call from main loop)
  if (!dataFile) return;

  while (bufferTail != bufferHead) {
    dataFile.write((uint8_t*)&writeBuffer[bufferTail], sizeof(FlightRecord));
    bufferTail = (bufferTail + 1) % BUFFER_SIZE;
  }

  // Flush to disk so file size is accurate and data persists
  dataFile.flush();
}

void handleFlashCommands() {
  // Early return if filesystem not mounted yet
  if (!fsInitialized) {
    // Try to mount filesystem (won't create files, just mount)
    if (LittleFS.begin()) {
      fsInitialized = true;
    } else {
      return;  // Filesystem not ready, skip command processing
    }
  }

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      commandBuffer.trim();

      if (commandBuffer == "LIST") {
        Dir dir = LittleFS.openDir("/");
        while (dir.next()) {
          if (dir.fileName().startsWith("flight_")) {
            Serial.print("FLASH:FLIGHT:");
            Serial.print(dir.fileName());

            // Show file size in human-readable format
            size_t fileSize = dir.fileSize();
            Serial.print(" (");
            if (fileSize >= 1024 * 1024) {
              Serial.print(fileSize / (1024.0 * 1024.0), 2);
              Serial.print(" MB");
            } else if (fileSize >= 1024) {
              Serial.print(fileSize / 1024.0, 2);
              Serial.print(" KB");
            } else {
              Serial.print(fileSize);
              Serial.print(" bytes");
            }
            Serial.print(")");

            // Mark if this is the current active flight (only if file is
            // actually open for logging)
            String currentFile = "flight_" + String(flightNumber) + ".bin";
            if ((dir.fileName() == currentFile ||
                 dir.fileName() == ("/" + currentFile)) &&
                dataFile) {
              Serial.print(" [ACTIVE]");
            }
            Serial.println();
          }
        }
        Serial.println("FLASH:END");
      } else if (commandBuffer == "CURRENT") {
        Serial.print("FLASH:CURRENT:");
        Serial.println(flightNumber);
      } else if (commandBuffer.startsWith("GET ")) {
        int flightNum = commandBuffer.substring(4).toInt();
        String filename = "/flight_" + String(flightNum) + ".bin";

        // Close current file if it's the one being downloaded
        bool needReopen = false;
        if (flightNum == flightNumber && dataFile) {
          dataFile.flush();  // Ensure all data is written before closing
          dataFile.close();
          needReopen = true;
        }

        File f = LittleFS.open(filename, "r");
        if (f) {
          Serial.println("FLASH:DATA_START");
          // Send in chunks to avoid blocking
          uint8_t chunk[256];
          while (f.available()) {
            int bytesRead = f.read(chunk, sizeof(chunk));
            Serial.write(chunk, bytesRead);
          }
          f.close();
          Serial.println("FLASH:END");
        } else {
          Serial.println("FLASH:ERROR: File not found");
        }

        // Reopen current file if we closed it
        if (needReopen) {
          String currentFilename = "/flight_" + String(flightNumber) + ".bin";
          dataFile = LittleFS.open(currentFilename, "a");
        }
      } else if (commandBuffer.startsWith("DELETE ")) {
        int flightNum = commandBuffer.substring(7).toInt();
        // Don't delete the currently active flight (only if file is actually
        // open for logging)
        if (flightNum == flightNumber && dataFile) {
          Serial.println("FLASH:ERROR: Cannot delete active flight");
        } else {
          String filename = "/flight_" + String(flightNum) + ".bin";
          if (LittleFS.remove(filename)) {
            Serial.println("FLASH:DELETED");
          } else {
            Serial.println("FLASH:ERROR: Delete failed");
          }
        }
      } else if (commandBuffer == "INFO") {
        FSInfo fs_info;
        LittleFS.info(fs_info);
        Serial.print("FLASH:STORAGE: ");

        // Format used bytes
        if (fs_info.usedBytes >= 1024 * 1024) {
          Serial.print(fs_info.usedBytes / (1024.0 * 1024.0), 2);
          Serial.print(" MB");
        } else if (fs_info.usedBytes >= 1024) {
          Serial.print(fs_info.usedBytes / 1024.0, 2);
          Serial.print(" KB");
        } else {
          Serial.print(fs_info.usedBytes);
          Serial.print(" bytes");
        }

        Serial.print(" / ");

        // Format total bytes
        if (fs_info.totalBytes >= 1024 * 1024) {
          Serial.print(fs_info.totalBytes / (1024.0 * 1024.0), 2);
          Serial.print(" MB");
        } else if (fs_info.totalBytes >= 1024) {
          Serial.print(fs_info.totalBytes / 1024.0, 2);
          Serial.print(" KB");
        } else {
          Serial.print(fs_info.totalBytes);
          Serial.print(" bytes");
        }

        Serial.println(" used");
      }

      commandBuffer = "";
    } else {
      commandBuffer += c;
    }
  }
}

*/