#include <math.h>
#include <config.h>
#include <orientation.cpp>
#include "kalman.h"

Kalman filter;
float MotorOffset;

float predictedCd(float newMotorPos) {

    float Cd = -0.00000283694 * pow(newMotorPos, 4) + 0.000292232 * pow(newMotorPos, 3) - 0.0128345 * pow(newMotorPos, 2) + 0.375533 * newMotorPos + 0.534332;
    return Cd;

}

float currentCd(float acceleration, float velocity) {

    float dragForce = MASS * (-acceleration - G);
    float currentCd = 2 * dragForce / (RHO * AREA * velocity * velocity);
    return currentCd;

}

void calcMotorOffset() {

    float predictedCd = predictedCd(motorPos);
    float measuredCd = currentCd(filter.getCorrectedAcceleration(), filter.getVelocity());
    MotorOffset = measuredCd - predictedCd;

}

float desiredMotorPos(float Cd) {

}