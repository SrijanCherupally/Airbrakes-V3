#ifndef KALMAN_H
#define KALMAN_H


class Kalman
{

public:

    // dt = IMU update time
    Kalman(float dt);

    // Re-initialize state and covariance (call at launch)
    void reset();

    // IMU update
    void predict();


    // Barometer update
    void update();


    // Add a velocity increment (e.g. recovered pre-roll dv at launch)
    void injectVelocity(float dv);

    float getAltitude();
    float getVelocity();
    float getBias();
    float getCorrectedAcceleration();



private:

    float dt;


    // State

    float altitude;
    float velocity;
    float bias;
    float correctedAcceleration;

    float worldAcc[3];



    // Covariance

    float P[3][3];


    // Noise

    float Q_altitude;
    float Q_velocity;
    float Q_bias;

    float R_altitude;


};


#endif