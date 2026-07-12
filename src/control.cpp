#include <math.h>
#include <config.h>
#include <cdEstimator.cpp>

float calcCd(float newMotorPos) {

    float Cd = -0.00000236412 * pow(newMotorPos, 4) + 0.000243527 * pow(newMotorPos, 3) - 0.0106954 * pow(newMotorPos, 2) + 0.312944 * newMotorPos + 0.527277;
    
    return Cd;

}

