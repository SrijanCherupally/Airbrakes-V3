# `tools/`

Standalone development and diagnostic utilities that are not part of the main firmware build.

## What is here

- `odrive_can_standalone_test.cpp.txt` — a standalone ODrive CAN test source intended as a reference or manual diagnostic aid. It is not compiled into the firmware by default and should be treated as a development helper, not a production target.

## How to use these utilities

These files are provided for reference and manual testing. Use them as:

- Examples for communicating with ODrive hardware over CAN.
- Diagnostic starting points when debugging motor-control issues.
- Reference implementations to compare against the integrated firmware behavior.

## Build and usage notes

- There is no automated build step for the contents of this directory. If you want to compile and run one of these sources, follow your own build instructions for the appropriate toolchain and target environment.
- Do not assume these utilities are tested or maintained to the same standard as the main firmware. Verify their behavior independently before relying on them for critical operations.

## Contributing

If you add a new utility here, include a short README or comment header explaining:

- The purpose of the utility.
- Any prerequisites or build instructions.
- How it fits into the development workflow.

## Links

- [`../src/control.cpp`](../src/control.cpp) — integrated control logic.
- [`../include/control.h`](../include/control.h) — control interface.
- [`../lib/CAN/README.md`](../lib/CAN/README.md) — CAN library used for ODrive communication.
