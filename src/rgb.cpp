#include "rgb.h"

RGBLed::RGBLed(uint8_t pinR, uint8_t pinG, uint8_t pinB)
    : rPin(pinR), gPin(pinG), bPin(pinB) {
  pinMode(rPin, OUTPUT);
  pinMode(gPin, OUTPUT);
  pinMode(bPin, OUTPUT);
  analogWriteResolution(16);  // 0-65535
  off();
}

void RGBLed::setColor(float r, float g, float b) {
  analogWrite(rPin, invert((uint16_t)(r * 65535.0f)));
  analogWrite(gPin, invert((uint16_t)(g * 65535.0f)));
  analogWrite(bPin, invert((uint16_t)(b * 65535.0f)));
}

void RGBLed::off() {
  analogWrite(rPin, 65535);
  analogWrite(gPin, 65535);
  analogWrite(bPin, 65535);
}

void RGBLed::flash(float r, float g, float b, int duration) {
  setColor(r, g, b);
  delay(duration);
  off();
}

void RGBLed::rainbow(int wait) {
  for (int i = 0; i < 256; i++) {
    setColor(wheel(i) / 255.0f, wheel((i + 85) % 256) / 255.0f,
             wheel((i + 170) % 256) / 255.0f);
    delay(wait);
  }
}

void RGBLed::blink(float r, float g, float b, int times, int onTime,
                   int offTime) {
  for (int i = 0; i < times; i++) {
    setColor(r, g, b);
    delay(onTime);
    off();
    delay(offTime);
  }
}

uint8_t RGBLed::wheel(byte pos) {
  if (pos < 85) {
    return pos * 3;
  } else if (pos < 170) {
    return (170 - pos) * 3;
  } else {
    return 0;
  }
}
