#include "kalman.h"
#include <math.h>

Kalman::Kalman(float dt)
{

    this->dt = dt;


    // Initial state

    altitude = 0.0f;
    velocity = 0.0f;
    bias = 0.0f;



    // Initial uncertainty

    P[0][0] = 10.0f;   // altitude uncertainty
    P[1][1] = 10.0f;   // velocity uncertainty
    P[2][2] = 0.1f;    // bias uncertainty



    // Process noise

    Q_altitude = 0.01f;

    Q_velocity = 0.1f;

    Q_bias = 0.0001f;



    // DPS368 noise

    R_altitude = 2.0f;

}

void Kalman::predict(float acceleration)
{

    // Remove estimated bias

    float correctedAcceleration =
        acceleration - bias;



    // Store old velocity

    float oldVelocity = velocity;



    // Integrate acceleration

    velocity += correctedAcceleration * dt;



    altitude += oldVelocity * dt
              + 0.5f *
                correctedAcceleration *
                dt * dt;



    // Increase uncertainty

    P[0][0] += Q_altitude;

    P[1][1] += Q_velocity;

    P[2][2] += Q_bias;

}

void Kalman::update(float altitudeMeasurement)
{

    float error =
        altitudeMeasurement - altitude;



    // Kalman gain

    float K =
        P[0][0] /
        (P[0][0] + R_altitude);



    // Correct altitude

    altitude += K * error;



    // Reduce uncertainty

    P[0][0] *= (1.0f - K);



    /*
       Bias correction

       If altitude error exists,
       adjust bias slightly
    */

    bias += 0.001f * error;


}

float Kalman::getAltitude()
{
    return altitude;
}


float Kalman::getVelocity()
{
    return velocity;
}


float Kalman::getBias()
{
    return bias;
}