#ifndef ESTIMATOR_H
#define ESTIMATOR_H

// High-level state estimator: drives the IMU/baro reads, the quaternion
// attitude filter, and the scalar Kalman altitude/velocity filter, and
// derives the current coefficient of drag.

void filterReset();
void filterUpdate();

// Bias/stationary calibration on the pad. Returns the accelerometer
// magnitude (m/s^2) for launch detection.
float biasUpdate();

// Add a velocity increment to the filter (recovered pre-roll dv at launch).
void estimatorInjectVelocity(float dv);

// Estimated flight state
float estAltitude();
float estVelocity();
float estAccel();    // corrected world-frame vertical acceleration (m/s^2)
float estBias();
float estRawBaro();  // latest raw barometric altitude (m)
float estCd();       // low-pass filtered coefficient of drag

// True while the vehicle is considered stationary (for PAD LED/UI).
extern bool biasActive;

#endif  // ESTIMATOR_H
