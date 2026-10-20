# N2 PDU payload-power integration

**CDR scope revised October 18, 2026:** OBC + real payload + PDU. The PDU turns payload power on/off; acquisition and raw-data retention must work without the COMMS stack. FSR extends this same payload/PDU integration through SatNOGS, SDR and Yamcs ground operations. See [current intent](../planning/DEVELOPMENT_INTENT.md).

## Target CDR sequence

1. Command/observe Pi Zero W F′ from Pi 5/Yamcs over LAN TCP (selected October 19; not implemented). SSH/SCP remains separate host access/product retrieval.
2. OBC commands the agreed PDU payload output on. Confirm the rail/readback and payload-ready condition after the agreed startup delay.
3. Command collection through the USB↔RS-422 payload interface. Observe acceptance and terminal status separately.
4. Retrieve the complete raw product, verify its identity/size/integrity and retain it on the OBC.
5. Command the PDU output off and confirm the off state. The raw product remains available for inspection through the agreed local access method.

This is a hardware acceptance target, not a result established by the local simulator. Formal modes and time-based scheduling are not CDR prerequisites. The PDU power sequence and the operator/data-inspection procedure still need implementation/runbook agreement.

## Inputs to agree

- Selected hardware is Artemis PDU v2.2; verify exact populated board, running firmware and payload output/rail mapping; harness, connector/pinout, voltage and current requirements.
- Selected path: Pi Zero W F′ → UART mux channel 2/local RPC → satellite Teensy → UART → PDU v2 protocol. Dennis reports the bench mostly wired; this is not an observed HIL result. Firmware reference: [`codex/pdu-protocol-refactor`](https://github.com/hsfl/artemis-cubesat-pdu-firmware/tree/codex/pdu-protocol-refactor). Hardware v2.2 and protocol v2 are distinct; the pinned reference remains unchanged.
- Payload startup/readiness and shutdown/standby timing; command order and what readback or measurement proves powered-on and powered-off states.
- All payload supply paths, including the USB↔RS-422 adapter, so the intended PDU-controlled off state can be verified.
- Timeout, missing readback, payload-not-ready, failed collection and failed retrieval behavior. Agree whether/when power is removed on each failure and how retained data are protected.
- Implement the selected CDR LAN TCP/Yamcs command/telemetry path, returned outcomes and retained-product inspection/retrieval procedure; see the [TCP plan](../planning/CDR_TCP_YAMCS_IMPLEMENTATION_PLAN.md).

## Source and evidence boundary

- [PDU v2 ICD](../../external/artemis-pdu/PDU_PROTOCOL_ICD.md) owns wire semantics for the pinned reference.
- [EpsManager](../../ArtemisRpiTeensy_N2/Components/EpsManager/EpsManager.fpp), [EpsDriver_Artemis](../../ArtemisRpiTeensy_N2/Components/EpsDriver_Artemis/EpsDriver_Artemis.fpp) and [topology](../../ArtemisRpiTeensy_N2/ArtemisRpiTeensyDeployment/Top/topology.fpp) own current software wiring.
- [Payload contract](PAYLOAD.md) owns the USB↔RS-422 command/lifecycle and raw-product boundary.

Record exact board/firmware, F′ binary/dictionary, command outcomes, payload rail/readiness observations, retained-product integrity and off-state evidence for the CDR sequence. The current software tests do not establish real-PDU HIL. Hardware operations follow a revision-matched runbook and separate task-specific authorization.
