#ifndef KALMAN_H
#define KALMAN_H


class Kalman
{

public:

    // dt = IMU update time
    Kalman(float dt);

    // Re-initialize state and covariance (call at launch)
    void reset();
    void setBias(float value);

    // IMU propagation.  The estimator supplies the measured interval rather
    // than assuming its caller always executes at exactly the nominal rate.
    void predict(float elapsedSeconds);


    // Barometer update.  The measurement is passed in explicitly so this
    // class remains a pure state estimator (and can validate the innovation
    // before changing altitude or velocity).
    bool update(float altitudeMeasurement);
    bool isAltitudeMeasurementPlausible(float altitudeMeasurement) const;


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
