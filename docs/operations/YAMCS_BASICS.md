# Yamcs primer for Neutron 2

**BLUF:** Yamcs decodes telemetry, records events/data, and sends operator commands through a configured link. The existing software demo runs Yamcs and simulated F′ on one host. CDR uses stock ComCcsds/TCP between the Pi Zero W F′ TCP server and the Pi 5 Yamcs tcp-fast-client, with stock FileDownlink for files. Final local native loopback passed both opaque fixtures with independent GET byte/hash checks, disconnect recovery, and 41 fake UART mux channel-2 PDU RPCs; guard tests and legacy Yamcs regressions passed. Pi/hardware acceptance is separate. No network mux is used. Physical UART mux channel 2 remains the Teensy-local PDU RPC path. SatNOGS/SDR/RF is FSR scope. See the [CDR TCP runbook](CDR_TCP.md), [canonical plan](../planning/CDR_TCP_YAMCS_IMPLEMENTATION_PLAN.md), [portable evidence pack](../verification/evidence/n2-cdr-tcp-2026-10-20/README.md), [system architecture](../architecture/SYSTEM_ARCHITECTURE.md), and [development intent](../planning/DEVELOPMENT_INTENT.md).

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
Today: board-free software demo
F′ simulator ⇄ software UART/PTys ⇄ local bridge/helpers
             ⇄ UDP 50000/50001/50002 ⇄ Yamcs + F′ MDB/XTCE ⇄ browser/archive

CDR target (local native loopback and legacy regression PASS)
Pi Zero W: F′ ComCcsds ⇄ stock Drv.TcpServer ⇄ TCP over LAN ⇄ Pi 5: Yamcs tcp-fast-client
           stock FileDownlink uses this same CCSDS/TCP connection
Pi Zero W: F′ ⇄ physical UART mux (channel 2 local RPC) ⇄ satellite Teensy/PDU
```

Use the stock F′ TCP server on the Zero W and tcp-fast-client in the Pi 5 Yamcs ground-only launcher. The ground bridge combines stock TCP/UDP adapters, the TM frame aggregator, PacketBridge, and a small 5 ms UDP pacing wrapper for outgoing TM. ComCcsds carries commands/events/telemetry and stock FileDownlink directly; no source FileDownlink scheduler change or network mux is used. The TCP connection is separate from Yamcs's browser/API port. Keep physical UART mux channel 2 for Teensy-local PDU RPC. CDR retains PDU power on/off. Final local tests passed both fixture transfers with independent byte/hash validation, disconnect recovery and fake PDU RPC; guard tests and the legacy regression passed. SatNOGS/SDR/RF remain future work.

The current local software profile accepts TM frames on UDP `50000`: spacecraft ID `68`, virtual channel `1`, fixed length `1024`, CRC-16. After frame checks and packet extraction, `FprimePacketPreprocessor` and the mission database make F′ packets meaningful to Yamcs. N2 already runs the `fprime-yamcs` integration and helpers. The `fprime-yamcs-tlmchan` helper splits aggregate `Svc.TlmChan` packets into single-record packets and feeds them back through internal UDP `50002`. The exact XTCE is generated at launch from the deployment JSON dictionary. The tracked `yamcs/config/mdb/fprime.xtce.xml` is only a placeholder. These settings describe the software profile; they are not a SatNOGS hardware interface. The selected CDR profile carries ComCcsds directly over the stock TCP connection.

Keep the outer envelope separate from F′ meaning. CCSDS frame processing checks identifiers, length, and CRC, then extracts space packets. F′ command names, event text, and channel values need XTCE generated from the **same deployment build** as the sending F′ executable; a valid frame can still hold undecodable packets if the dictionary is stale. Read the [CCSDS frame-processing guide](https://docs.yamcs.org/yamcs-server-manual/links/ccsds-frame-processing/), [CCSDS packet input stream reference](https://docs.yamcs.org/yamcs-server-manual/links/packet-input-stream/ccsds/), and [MDB guide](https://docs.yamcs.org/yamcs-server-manual/mdb/).

For the future SatNOGS/SDR path, demodulated bytes are not necessarily Yamcs-ready. The ground chain must recover frame synchronization and any required decoding, descrambling, or error correction, then deliver complete frames matching its agreed CCSDS profile. This work is outside CDR. UDP preserves datagram boundaries, while TCP preserves byte order without preserving individual write boundaries; any later stream adapter must therefore handle message boundaries explicitly. See the [SatNOGS integration page](../integration/SATNOGS.md).

## How commands go back

```text
Browser command → realtime processor + MDB encode → tc_realtime
→ UDP 50001 TC frame link → local fprime-yamcs bridge → F′ command dispatcher
F′ app → TM/event response + command-history update → Yamcs streams/archive → browser
```

The current local TC link targets UDP `50001`, spacecraft ID `68`, VC `1`, maximum frame length `1024`, CRC-16; the local host bridge connects it to the software F′ path. For CDR, Yamcs remains on the Pi 5 and F′ runs on the Pi Zero W. The stock tcp-fast-client/TcpServer path carries ComCcsds and FileDownlink and has passed native local acceptance. The local UDP/PTY wiring is not the LAN implementation or hardware acceptance evidence.

## What an operator should verify

For local software use, follow the [runbook](../development/YAMCS_LOCAL_TESTING.md): start the stack, open `http://127.0.0.1:8090`, and select instance `fprime-project` and processor `realtime`. For the planned CDR host, operators use `http://<pi-5-lan-address>:8090`; configure authentication and permissions before LAN access. Inspect link status/counters, fresh telemetry and generation times, events, and command history. `RUNNING` means the instance is running; it does **not** mean a link is connected or receiving fresh packets. The current local server binds only to loopback, so LAN hosting requires a separate ground-host configuration. See the [security guide](https://docs.yamcs.org/yamcs-server-manual/security/).

Treat the stages separately: Yamcs queue acceptance, transmission, F′ command acknowledgement, payload-operation admission, and payload-operation result can each describe different progress. In N2, `PayloadOperationStatus` reports admitted operations as `ACCEPTED`, followed by the correlated terminal outcome. Successful **operation completion** requires the matching success result; a transport acknowledgement or command-history update alone does not prove the operation worked. **Independent file receipt** requires the ground file bytes to match the source size and hash. For FileDownlink, command-OK, `FileSent`, or local buffer return is not proof of receipt; a missing or partial ground file fails. Inspect `FileOpenError` when source opening fails because the default command response can mask it.

The current simulation has no automatic private science-format parser or histogram generation in Yamcs. A received file or opaque payload remains bytes unless a defined decoder/product pipeline is added and validated. The simulated F′ app is planned to move to the Pi Zero W while Yamcs stays on the Pi 5. SatNOGS, SDR ground services, and RF links are later integration work. See the [CDR TCP/Yamcs plan](../planning/CDR_TCP_YAMCS_IMPLEMENTATION_PLAN.md) for the stock link and local acceptance sequence.

## First troubleshooting checks

- **Local instance says RUNNING, screen is quiet:** inspect TM link state/counters and confirm fresh packet reception. For the local UDP profile, verify complete 1024-byte frames with spacecraft `68`, VC `1`, and valid CRC-16.
- **Frames arrive, but parameters/events are absent or wrong:** verify packet extraction/APIDs and that the generated XTCE dictionary came from the same F′ build. For channel telemetry, confirm `fprime-yamcs-tlmchan` is running and UDP `50002` is available.
- **Commands leave Yamcs, but F′ does not respond:** inspect the TC link and UDP `50001`, then confirm the matching F′ command appears in command history and inspect returned events/telemetry. A sent command is not proof of completion.
- **CDR Pi 5 cannot connect to the Zero W:** check the LAN route, Zero W stock TCP server listener/address/port, tcp-fast-client status and reconnect behavior, then check Yamcs's CCSDS link. Keep channel-2 RPC on the physical UART mux.
- **Future SDR shows demodulated traffic, but Yamcs sees no frames:** check synchronization and frame recovery at the ground-service boundary before debugging MDB decoding.
