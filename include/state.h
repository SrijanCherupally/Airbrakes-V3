#ifndef STATE_H
#define STATE_H

#include "control.h"
#include "estimator.h"
#include "flash.h"
#include "hardware.h"

typedef enum State {
  STATE_IDLE,  // Initial state
  STATE_PAD,
  STATE_BOOST,
  STATE_CONTROL,
  STATE_DESCENT,
  STATE_LANDED
} State;

extern State currentState;
void debugPrintf(const char* format, ...);

void stateInit();
void stateUpdate();      // core 0: state machine, control, logging
void estimatorUpdate();  // core 1: sensor fusion

#endif  // STATE_H
