# N2 mission modes

**Implemented:** a handwritten C++ demo transition guard in [MissionApp](../../ArtemisRpiTeensy_N2/Components/MissionApp/MissionApp.cpp), with mode values declared in [Types.fpp](../../ArtemisRpiTeensy_N2/Components/Types/Types.fpp). This is not the full flight-mode design in the SDD.

The nominal scheduled demo follows:

```text
BASE → COLLECTION_PENDING → COLLECTING → SCIENCE_READY → DOWNLINKING → BASE
```

MissionApp owns the current mode and validates updates. ScienceApp owns capture scheduling/execution and reports collection states; CommsApp reports downlink state. MissionApp's rate callback publishes heartbeat/telemetry; it does not itself execute the capture countdown. Commands include `SCHEDULE_COLLECTION` (delay 1–300 seconds), `CANCEL_COLLECTION`, and `ENTER_BASE_MODE`.

Additional allowed transitions support direct collection/downlink from BASE. Repeating the current mode and returning to BASE are accepted; other transitions are rejected by `isAllowedTransition`. Returning to BASE/canceling a pending collection is not proof of aborting every active hardware operation. See source for exact behavior.

[MissionApp tests](../../ArtemisRpiTeensy_N2/Components/MissionApp/test/ut/MissionAppTestMain.cpp) cover nominal transitions, rejection guards, manual downlink retry, and cancellation. They passed in [baseline packaging validation](../verification/evidence/n2-packaging-2026-10-14/README.md).

Revised October CDR scope is payload acquisition plus PDU-controlled payload on/off, without COMMS or required formal mission modes. CDR command/telemetry uses Pi Zero W F′ TCP over the local network to Pi 5 Ubuntu/Yamcs, with operator browsers on the LAN. This is the selected direction, not implemented or hardware-tested TCP support. December FSR adds the complete COMMS/ground chain with the previously planned nominal scheduling/modes and integrated PDU power sequence; the fuller flight-mode model and hardware sequence remain separate work. See [development intent](../planning/DEVELOPMENT_INTENT.md) and [system architecture](SYSTEM_ARCHITECTURE.md).
