#include <math.h>
#include <config.h>

float calcCd(float newMotorPos) {
    setMotorPos(newMotorPos);
    float Cd = -0.0054546*pow(motorPos, 4) + 0.561877*pow(motorPos, 3) - 24.67688*pow(motorPos, 2) + 722.03958*motorPos + 81.39165;
    return Cd;
}

