#ifndef CONTROL_H
#define CONTROL_H

#include "coast_table.h"
#include "estimator.h"

extern float desiredCd;

float getCoastAltitude(float velocity, float cd);
void controlUpdate();

#endif  // CONTROL_H