#ifndef KALMAN_H
#define KALMAN_H


class Kalman
{

public:

    // dt = IMU update time
    Kalman(float dt);


    // IMU update
    void predict(float acceleration);


    // Barometer update
    void update(float altitudeMeasurement);



    float getAltitude();
    float getVelocity();
    float getBias();



private:

    float dt;


    // State

    float altitude;
    float velocity;
    float bias;



    // Covariance

    float P[3][3];


    // Noise

    float Q_altitude;
    float Q_velocity;
    float Q_bias;

    float R_altitude;


};


#endif