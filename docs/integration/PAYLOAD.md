# N2 payload integration contract

**Open interface:** Aris owns the real PLD; Dennis owns the F′/Yamcs side. [Current intent](../planning/DEVELOPMENT_INTENT.md) and [completion/storage scope](../verification/COMPLETION_STORAGE.md) are the recorded decisions.

Agree these inputs before implementing the real adapter:

- Physical interface and electrical/transport settings.
- Collection command bytes, duration units and permitted ranges.
- Acceptance, busy, failure, timeout and completion responses; correlation and recovery behavior.
- Raw-file framing, length/end boundary, retrieval/retry behavior and integrity indicators.
- A representative transfer or agreed fixture for interface compatibility testing when integration begins.

FSW acquires, stores and downlinks opaque raw bytes. The payload team's JAR owns actual science interpretation/display. Real samples were not supplied or required for the accepted software-only slice; its synthetic pulse schema is not the payload ICD.

Preserve `MissionApp → ScienceApp → PayloadManager → driver` ownership and serialized admission. Replace the simulated driver below that contract once the public interface is agreed. Do not infer private opcodes or the physical interface from the simulator or older Artemis wiring.
