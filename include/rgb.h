// RGBLed class for inverted-logic (common anode) RGB LED control.
#ifndef RGB_H
#define RGB_H

#include <Arduino.h>

class RGBLed {
 public:
  RGBLed(uint8_t pinR, uint8_t pinG, uint8_t pinB);

  // Set color with user input (0.0-1.0 for each channel)
  void setColor(float r, float g, float b);

  // Turn off LED
  void off();

  // Flash a color for a duration (ms)
  void flash(float r, float g, float b, int duration);

  // Rainbow color shifting effect
  void rainbow(int wait = 10);

  // Simple blink effect
  void blink(float r, float g, float b, int times, int onTime = 200,
             int offTime = 200);

 private:
  uint8_t rPin, gPin, bPin;

  // Invert logic for common anode LED (LOW=ON, HIGH=OFF)
  uint16_t invert(uint16_t val) { return 65535 - val; }

  // Helper for rainbow effect
  uint8_t wheel(byte pos);
};

#endif  // RGB_H
