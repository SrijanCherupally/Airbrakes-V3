#ifndef KALMAN_H
#define KALMAN_H


class Kalman
{

public:

    // dt = IMU update time
    Kalman(float dt);


    // IMU update
    void predict();


    // Barometer update
    void update();



    float getAltitude();
    float getVelocity();
    float getBias();
    float getCorrectedAcceleration();

    float getVerticalAcceleration();
    float* getWorldAcceleration(float world[3]);



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