// RGBLed class for inverted logic RGB LED control
#include <Arduino.h>

class RGBLed {
public:
	RGBLed(uint8_t pinR, uint8_t pinG, uint8_t pinB)
		: rPin(pinR), gPin(pinG), bPin(pinB) {
		pinMode(rPin, OUTPUT);
		pinMode(gPin, OUTPUT);
		pinMode(bPin, OUTPUT);
		analogWriteResolution(16); // 0-65535
		off();
	}

	// Set color with user input (0.0-1.0 for each channel)
	void setColor(float r, float g, float b) {
		analogWrite(rPin, invert((uint16_t)(r * 65535.0f)));
		analogWrite(gPin, invert((uint16_t)(g * 65535.0f)));
		analogWrite(bPin, invert((uint16_t)(b * 65535.0f)));
	}

	// Turn off LED
	void off() {
		analogWrite(rPin, 65535);
		analogWrite(gPin, 65535);
		analogWrite(bPin, 65535);
	}

	// Flash a color for a duration (ms)
	void flash(float r, float g, float b, int duration) {
		setColor(r, g, b);
		delay(duration);
		off();
	}

	// Rainbow color shifting effect
	void rainbow(int wait = 10) {
		for (int i = 0; i < 256; i++) {
			setColor(wheel(i) / 255.0f, wheel((i + 85) % 256) / 255.0f, wheel((i + 170) % 256) / 255.0f);
			delay(wait);
		}
	}

	// Simple blink effect
	void blink(float r, float g, float b, int times, int onTime = 200, int offTime = 200) {
		for (int i = 0; i < times; i++) {
			setColor(r, g, b);
			delay(onTime);
			off();
			delay(offTime);
		}
	}

private:
	uint8_t rPin, gPin, bPin;

	// Invert logic for common anode LED (LOW=ON, HIGH=OFF)
	uint16_t invert(uint16_t val) {
		return 65535 - val;
	}

	// Helper for rainbow effect
	uint8_t wheel(byte pos) {
		if (pos < 85) {
			return pos * 3;
		} else if (pos < 170) {
			return (170 - pos) * 3;
		} else {
			return 0;
		}
	}
};