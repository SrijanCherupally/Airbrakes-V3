#ifndef ORIENTATION_H
#define ORIENTATION_H

// Quaternion-based attitude estimator. Reads the global IMU instance
// (declared in hardware.h) and integrates gyro rates.

void initOrientation();
void updateOrientation();

// World-frame acceleration (m/s^2) with gravity removed on the Z axis.
void getWorldAcceleration(float world[3]);

// Extract Euler angles (radians) from the current attitude.
void GetOrientation(float* roll, float* pitch, float* yaw);

#endif  // ORIENTATION_H
