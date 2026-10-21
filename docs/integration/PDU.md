# N2 PDU payload-power integration

**CDR scope, transport selected October 20, 2026:** OBC + real payload + PDU, including payload power on/off. Use stock ComCcsds over TCP between Pi Zero W F′ and Pi 5 Yamcs, with stock FileDownlink for the retained file. No network mux or SatNOGS/SDR/RF is required. The physical UART mux channel 2 remains for PDU RPC. Final local native loopback passed both opaque fixture transfers with independent GET byte/hash checks and 41 fake channel-2 PDU RPCs before/during transfer and while disconnected; the guard tests and legacy Yamcs regressions also passed. This does not exercise real PDU power. FSR adds SatNOGS/SDR/RF and the complete ground chain. See the [canonical plan](../planning/CDR_TCP_YAMCS_IMPLEMENTATION_PLAN.md), [runbook](../operations/CDR_TCP.md), and [portable evidence pack](../verification/evidence/n2-cdr-tcp-2026-10-20/README.md).

## Target CDR sequence

1. Command/observe Pi Zero W F′ from Pi 5/Yamcs over stock ComCcsds/TCP. Keep the physical UART mux channel 2 for PDU RPC.
2. OBC commands the agreed PDU payload output on. Confirm the rail/readback and payload-ready condition after the agreed startup delay.
3. Command collection through the USB↔RS-422 payload interface. Observe acceptance and terminal status separately.
4. Retain the complete raw product on the OBC and use stock FileDownlink SendFile. Independently verify received bytes, size and hash; command completion or FileSent alone is not ground receipt. Start with the supplied multi-packet test files before wiring a retained-product ground helper.
5. Command the PDU output off and confirm the off state. Keep the onboard product after verified ground receipt.

This is a hardware acceptance target, not a result established by the local simulator. Formal modes and time-based scheduling are not CDR prerequisites. The PDU power sequence and the operator/data-inspection procedure still need implementation/runbook agreement.

## Inputs to agree

- Selected hardware is Artemis PDU v2.2; verify exact populated board, running firmware and payload output/rail mapping; harness, connector/pinout, voltage and current requirements.
- Selected path: Pi Zero W F′ → UART mux channel 2/local RPC → satellite Teensy → UART → PDU v2 protocol. Dennis reports the bench mostly wired; this is not an observed HIL result. Firmware reference: [`codex/pdu-protocol-refactor`](https://github.com/hsfl/artemis-cubesat-pdu-firmware/tree/codex/pdu-protocol-refactor). Hardware v2.2 and protocol v2 are distinct; the pinned reference remains unchanged.
- Payload startup/readiness and shutdown/standby timing; command order and what readback or measurement proves powered-on and powered-off states.
- All payload supply paths, including the USB↔RS-422 adapter, so the intended PDU-controlled off state can be verified.
- Timeout, missing readback, payload-not-ready, failed collection and failed retrieval behavior. Agree whether/when power is removed on each failure and how retained data are protected.
- The CDR TCP profile and ground-only launcher have final local native loopback acceptance, including independent file byte/hash checks, fake channel-2 UART RPC, startup-cancellation and legacy regressions. The fake UART/PDU test does not switch real power; the hardware on/off sequence still needs a populated-board, rail/readback and timing record. See the [TCP plan](../planning/CDR_TCP_YAMCS_IMPLEMENTATION_PLAN.md), [runbook](../operations/CDR_TCP.md), and [portable evidence pack](../verification/evidence/n2-cdr-tcp-2026-10-20/README.md).

## Source and evidence boundary

- [PDU v2 ICD](../../external/artemis-pdu/PDU_PROTOCOL_ICD.md) owns wire semantics for the pinned reference.
- [EpsManager](../../ArtemisRpiTeensy_N2/Components/EpsManager/EpsManager.fpp), [EpsDriver_Artemis](../../ArtemisRpiTeensy_N2/Components/EpsDriver_Artemis/EpsDriver_Artemis.fpp) and [topology](../../ArtemisRpiTeensy_N2/ArtemisRpiTeensyDeployment/Top/topology.fpp) own current software wiring.
- [Payload contract](PAYLOAD.md) owns the USB↔RS-422 command/lifecycle and raw-product boundary.

Record exact board/firmware, F′ binary/dictionary, command outcomes, payload rail/readiness observations, retained-product integrity and off-state evidence for the CDR sequence. The current software tests do not establish real-PDU HIL. Hardware operations follow a revision-matched runbook and separate task-specific authorization.
