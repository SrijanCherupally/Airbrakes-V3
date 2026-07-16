#include <Arduino.h>
#include <baro.cpp>
#include <imu.cpp>
#include <rgb.cpp>
#include <config.h>

BARO baro;
RGBLed led(24,23,22);

void setup() {
    baro.begin();
    Serial.println(baro.isConnected());
}

void loop() {
    Serial.println(baro.getAltitudeCm());
    baro.update();
}

void setup1() {
    led.setColor(0.0f, 0.5882352941f, 1.0f); // Bright Blue
}

void loop1() {
    led.rainbow(10);
}