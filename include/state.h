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

// Read on both RP2350 cores. Volatile ensures each loop observes a state
// transition made by the other core; queue publication itself uses fences.
extern volatile State currentState;
void debugPrintf(const char* format, ...);

void stateInit();
void stateUpdate();      // core 0: state machine, control, logging
void estimatorUpdate();  // core 1: sensor fusion
bool startGroundTest();
void abortGroundTest();
const char* stateName(State state);

#endif  // STATE_H
