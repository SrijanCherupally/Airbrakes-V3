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
  STATE_LANDED,
  STATE_GROUND_TEST_ARMED,
  STATE_GROUND_TEST_RECORDING
} State;

extern State currentState;
void debugPrintf(const char* format, ...);

void stateInit();
void stateUpdate();      // core 0: state machine, control, logging
void estimatorUpdate();  // core 1: sensor fusion
bool startGroundTest();
void abortGroundTest();
const char* stateName(State state);

#endif  // STATE_H
