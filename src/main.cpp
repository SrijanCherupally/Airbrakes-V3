#include <Arduino.h>

#include "state.h"

// Make setup blocking so core1 waits for hardware init.
semaphore_t setup_done;

void setup() {
  sem_init(&setup_done, 0, 1);

  setupHardware();
  stateInit();

  // Flash logging will be initialized when entering STATE_PAD

  // Indicate setup done
  sem_release(&setup_done);
}

void loop() {
  handleFlashCommands();
  serviceOdrive();

  // Update state machine
  stateUpdate();
}

void setup1() {
  // wait for core0 setup to finish
  sem_acquire_blocking(&setup_done);
}

void loop1() {
  // Update filter
  estimatorUpdate();
}
