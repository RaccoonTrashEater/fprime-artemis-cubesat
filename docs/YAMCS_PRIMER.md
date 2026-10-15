# Yamcs primer for Neutron 2

**BLUF:** Yamcs is the ground-side server that turns received spacecraft data into named telemetry and events, records it, and sends operator commands back through a configured link. In N2 today, Yamcs talks to a host-run F′ simulator through software pseudo-terminals and a local bridge. That proves a software path; it does not prove the radio, SDR, OBC, payload, or flight link. See the [local Yamcs runbook](N2_YAMCS_LOCAL_TESTING_2026-10-07.md), [system architecture](SYSTEM_ARCHITECTURE.md), [development intent](N2_DEVELOPMENT_INTENT_2026-10-07.md), and [ground-host plan](N2_YAMCS_GROUND_HOST_PLAN_2026-10-08.md).

Yamcs is a server with a browser interface and API. It manages data links, interprets traffic using a mission database, routes commands, and provides live and archived data. See the [Yamcs overview](https://docs.yamcs.org/yamcs-server-manual/general/), [web interface guide](https://docs.yamcs.org/yamcs-server-manual/web-interface/), and [data-link guide](https://docs.yamcs.org/yamcs-server-manual/links/).

## A few terms

| Term | Meaning |
| --- | --- |
| Server | Yamcs process that hosts links, mission data, processing, APIs, and storage. |
| Browser | Operator UI served by Yamcs; users of a hosted UI do not need the source repository. |
| Instance | Named mission configuration inside Yamcs; N2 uses `fprime-project`. |
| Processor | A live or replay processing context within an instance; N2 uses `realtime`. |
| MDB | Mission Database: definitions Yamcs uses to interpret telemetry and encode commands. |
| XTCE | XML exchange format for mission definitions; N2's runtime XTCE is generated from the matching F′ dictionary. |
| Link | Configured connection that receives telemetry or sends commands to an external endpoint. |
| Stream | Typed flow of telemetry packets, commands, events, parameters, or command history inside Yamcs. |
| Packet | Bounded application data unit. An F′ telemetry packet is carried inside a CCSDS space packet. |
| Frame | Link-layer unit carrying space packets or parts of packets. The current software profile uses fixed 1024-byte TM frames and a maximum TC frame length of 1024 bytes. |
| Parameter | Named, typed value decoded from telemetry, such as a mode or counter. |
| Event | Timestamped report or state transition, such as a command response or operation result. |
| Archive | Persistent record of telemetry, events, alarms, and command history for later review. |
| Command history | Record of each uplink command and its processing and acknowledgement status. |

## How telemetry reaches a screen

```text
Today: F′ simulator on host
F′ app ⇄ software UART/PTys ⇄ existing fprime-yamcs bridge/helpers
     ⇄ UDP 50000: complete TM frames ⇄ Yamcs frame/link processing
     ⇄ tm_realtime stream ⇄ F′ MDB/XTCE decode ⇄ parameters, events, archive, browser
                                      └─ UDP 50002 helper packets re-enter tm_realtime

Intended ground path:
OBC running F′ → RF → SDR/ground services → complete CCSDS frames or packets → Yamcs
operator browser → Yamcs command processing → SDR/ground services → RF → OBC
```

The current profile accepts TM frames on UDP `50000`: spacecraft ID `68`, virtual channel `1`, fixed length `1024`, CRC-16. After frame checks and packet extraction, `FprimePacketPreprocessor` and the mission database make F′ packets meaningful to Yamcs. N2 already runs the `fprime-yamcs` integration and helpers; an SDR delivering compatible frame/packet bytes does not require a new custom decoder just because it is an SDR. Its `fprime-yamcs-tlmchan` helper splits aggregate `Svc.TlmChan` packets into single-record packets and feeds them back through internal UDP `50002`. The exact XTCE is generated at launch from the deployment JSON dictionary. The tracked `yamcs/config/mdb/fprime.xtce.xml` is only a placeholder. These settings describe the simulator profile, not an accepted SatNOGS hardware interface.

Keep the outer envelope separate from F′ meaning. CCSDS frame processing checks identifiers, length, and CRC, then extracts space packets. F′ command names, event text, and channel values need XTCE generated from the **same deployment build** as the sending F′ executable; a valid frame can still hold undecodable packets if the dictionary is stale. Read the [CCSDS frame-processing guide](https://docs.yamcs.org/yamcs-server-manual/links/ccsds-frame-processing/), [CCSDS packet input stream reference](https://docs.yamcs.org/yamcs-server-manual/links/packet-input-stream/ccsds/), and [MDB guide](https://docs.yamcs.org/yamcs-server-manual/mdb/).

An SDR producing demodulated bytes has not necessarily produced Yamcs-ready input. The ground chain must recover frame synchronization and any required decoding, descrambling, or error correction, then deliver complete frames matching the configured CCSDS profile. For a UDP frame link, send complete frames as datagrams. If a TCP source instead supplies a consecutive byte stream of CCSDS space packets, configure a packet input stream such as Yamcs's standard `CcsdsPacketInputStream`, which finds packet boundaries from each six-byte primary header. UDP preserves datagram boundaries, but the sender must put the expected complete frame or packet in each datagram. TCP preserves byte order without preserving individual write boundaries.

## How commands go back

```text
Browser command → realtime processor + MDB encode → tc_realtime
→ UDP 50001 TC frame link → local fprime-yamcs bridge → F′ command dispatcher
F′ app → TM/event response + command-history update → Yamcs streams/archive → browser
```

The current TC link targets UDP `50001`, spacecraft ID `68`, VC `1`, maximum frame length `1024`, CRC-16; the host bridge connects it to the software F′ UART path. Later, Yamcs should connect to the SDR ground services while the OBC runs F′. Yamcs stays on the ground and the OBC replaces the local simulator as spacecraft endpoint. The UDP/PTY wiring is not an SDR interface specification or proof of this replacement.

## What an operator should verify

For local software use, follow the [runbook](N2_YAMCS_LOCAL_TESTING_2026-10-07.md): start the stack, open `http://127.0.0.1:8090`, and select instance `fprime-project` and processor `realtime`. Inspect link status/counters, fresh telemetry and generation times, events, and command history. `RUNNING` means the instance is running; it does **not** mean a link is connected or receiving fresh packets. The local server binds only to loopback. A remotely reachable UI needs authentication and permissions; Yamcs security is not enabled by default. See the [security guide](https://docs.yamcs.org/yamcs-server-manual/security/) before exposing a server.

Treat the stages separately: Yamcs queue acceptance, transmission, F′ command acknowledgement, payload-operation admission, and payload-operation result can each describe different progress. In N2, `PayloadOperationStatus` reports admitted operations as `ACCEPTED`, followed by the correlated terminal outcome. Successful **operation completion** requires the matching success result; a transport acknowledgement or command-history update alone does not prove the operation worked. **Independent file receipt** requires reconstructed received bytes with confirmed identity, size, and integrity. The current stock-file diagnostic retrieves those bytes from Yamcs's `fprimeFilesIn` bucket; a future science transport may use another agreed mechanism. These are separate evidence gates in the local runbook, not synonyms.

The current simulation has no automatic private science-format parser or histogram generation in Yamcs. A received file or opaque payload remains bytes unless a defined decoder/product pipeline is added and validated. The current simulated F′ app can be replaced later by F′ on the OBC, with Yamcs and the SDR ground services staying on the ground; the exact SDR-to-Yamcs link contract and hardware behavior still require their own integration evidence.

## First troubleshooting checks

- **Instance says RUNNING, screen is quiet:** inspect TM link state/counters and confirm fresh packet reception. Then verify the incoming datagrams are complete 1024-byte frames with spacecraft `68`, VC `1`, and valid CRC-16.
- **Frames arrive, but parameters/events are absent or wrong:** verify packet extraction/APIDs and that the generated XTCE dictionary came from the same F′ build. For channel telemetry, confirm `fprime-yamcs-tlmchan` is running and UDP `50002` is available.
- **Commands leave Yamcs, but F′ does not respond:** inspect the TC link and UDP `50001`, then confirm the matching F′ command appears in command history and inspect returned events/telemetry. A sent command is not proof of completion.
- **SDR shows demodulated traffic, but Yamcs sees no frames:** check synchronization and frame recovery at the ground-service boundary before debugging MDB decoding.
