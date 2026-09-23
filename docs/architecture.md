# Architecture decisions

## Runtime and training separation

The Raspberry Pi runs the edge system: sensing, event coordination, storage and
inference. Model training is performed on a development computer in the
separate `smart-fridge-ml` repository.

## Why Python

Python is the primary implementation language because it has strong Raspberry
Pi camera, GPIO and machine-learning support and enables rapid prototyping. A
C or C++ component should be added only if required by a vendor SDK, hard
real-time microcontroller firmware, or measured performance limitations.

## State machine

A state machine represents the system as a small number of explicit states.
Only defined transitions are allowed:

```text
IDLE --door opens--> DOOR_OPEN --door closes--> CAPTURING --> IDLE
                                                |
                                                +----------> ERROR
```

This prevents accidental duplicate recordings and makes error handling and
testing clearer than a collection of unrelated callbacks.

