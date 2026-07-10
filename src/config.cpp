#include <Math.h>
#include <Arduino.h>

// Motor limits
#define motorMax 0.0f // motorPos, 1 unit is 1 revolution of the motor
#define motorMin 41.0f // 41 revolutions of the motor

// Rocket parameters
#define mass 0.608f // kg
#define baseCd 0.492f // OpenRocket estimate

// Launch detection
#define launchAccel 30.0f // m/s^2
#define launchVel 1.0f // m/s

// Control Starts
#define velControl 55.0f // vel drops below this to start control

// Control Ends
#define velControlEnd -1.0f // vel drops below this to end control and go to descent
#define velLand 1.0f // abs vel drops below this to consider landed
#define altLand 2.0f // alt drops below this to consider landed

// Targets
#define targetAlt 243.84f // target apogee altitude in meters