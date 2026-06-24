#ifndef ESTIMATOR_H
#define ESTIMATOR_H

#include "config.h"
#include "hardware.h"

void FilterReset();
void FilterUpdate();
float BiasUpdate();
void GetOrientation(float* roll, float* pitch, float* yaw);
void ReadIMU();

extern float aGlob[3];
extern float x[3];
extern float rawSensorData[2];
extern float rawBaroData;
extern float C[3][3];
extern float Cd;

// PAD/bias UI state (managed by BiasUpdate)
extern bool biasActive;

#endif  // ESTIMATOR_H