# N2 payload integration contract

**Updated October 18, 2026:** Dennis confirmed PLD↔OBC command/telemetry over **USB↔RS-422**. Aris owns the real PLD; Dennis owns the F′/Yamcs side. This selects the connection, not its electrical/protocol details or completed hardware integration. [Current intent](../planning/DEVELOPMENT_INTENT.md) and [completion/storage scope](../verification/COMPLETION_STORAGE.md) are the recorded decisions.

**Milestone allocation:** CDR integrates the real payload with OBC and PDU payload on/off, without COMMS. CDR command/telemetry uses Pi Zero W F′ TCP over the local network to Pi 5 Ubuntu/Yamcs, with operator browsers on the LAN. The stock ComCcsds/TCP and FileDownlink profile passed [native local acceptance](../verification/evidence/n2-cdr-tcp-2026-10-20/README.md); Pi and payload/PDU hardware acceptance remain open. The [canonical CDR plan](../planning/CDR_TCP_YAMCS_IMPLEMENTATION_PLAN.md) owns current transport status. FSR extends this to the complete COMMS/ground chain. Retrieve and retain the raw product before payload power-off; agree readiness and shutdown behavior with PDU integration.

Agree these inputs before implementing the real adapter:

- USB↔RS-422 adapter, USB host placement on the OBC, connector/pinout, electrical/serial settings, duplex/wiring and grounding. No exact adapter or harness is selected here.
- Collection command bytes, duration units and permitted ranges.
- Acceptance, busy, failure, timeout and completion responses; correlation and recovery behavior.
- Whether and how the raw product uses this link; raw-file framing, length/end boundary, retrieval/retry behavior and integrity indicators. Confirm this independently of command/telemetry transport.
- A representative transfer or agreed fixture for interface compatibility testing when integration begins.

FSW acquires, stores and downlinks opaque raw bytes. The payload team's JAR owns actual science interpretation/display. Real samples were not supplied or required for the accepted software-only slice; its synthetic pulse schema is not the payload ICD.

Preserve `MissionApp → ScienceApp → PayloadManager → driver` ownership and serialized admission. Replace the simulated driver below that contract once the public interface is agreed. Do not infer private opcodes or the physical interface from the simulator or older Artemis wiring.
