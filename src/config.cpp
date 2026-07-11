#include <Math.h>
#include <Arduino.h>
#include <config.h>

// Motor limits
float motorMax = 41.0f; // motorPos, 41 units is 41 revolution of the motor
float motorMin = 0.0f; // 0 revolutions of the motor
float motorPos = 0.0f; // Current position of motor

void setMotorPos(float newMotorPos) { // Motor position limits
    motorPos = newMotorPos;
    if (motorPos > motorMax) {
        motorPos = motorMax;
    } else if (motorPos < motorMin) {
        motorPos = motorMin;
    }
}

// Rocket parameters
float mass = 0.608f; // kg
float baseCd = 0.492f; // OpenRocket estimate

// Launch detection
float launchAccel = 30.0f; // m/s^2
float launchVel = 1.0f; // m/s

// Control Starts
float velControl = 55.0f; // vel drops below this to start control

// Control Ends
float velControlEnd = -1.0f; // vel drops below this to end control and go to descent
float velLand = 1.0f; // abs vel drops below this to consider landed
float altLand = 2.0f; // alt drops below this to consider landed

// Targets
float targetAlt = 243.84f; // target apogee altitude in meters