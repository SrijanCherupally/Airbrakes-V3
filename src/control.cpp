#include <math.h>
#include <config.h>
#include <orientation.cpp>

float calcCd(float newMotorPos) {

    float Cd = -0.00000283694 * pow(newMotorPos, 4) + 0.000292232 * pow(newMotorPos, 3) - 0.0128345 * pow(newMotorPos, 2) + 0.375533 * newMotorPos + 0.534332;
    return Cd;

}


