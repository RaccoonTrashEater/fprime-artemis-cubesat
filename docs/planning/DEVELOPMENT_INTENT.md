# Neutron 2 development intent — 2026-10-07 (updated 2026-10-08)

**BLUF:** The end-of-October CDR target is a Yamcs-commanded, pass-through science collection through the payload, OBC, SatNOGS, and SDR path, with raw science visible on the ground. The end-of-December FSR adds EPS-controlled payload power, nominal modes, and time-based collection. For software work, proceed **A → C → B**: literal command pass-through, truthful correlated outcomes, then the complete nominal raw-data cycle.

## Current decisions and boundaries

- **Development stage:** Software work only for now. Yamcs is the command and observation interface for local functional scenarios. No RF operation, board bring-up, flashing, deployment, or power switching is authorized by this software task.
- **CDR FlatSat:** The planned OBC is a Raspberry Pi Zero W running F′ as the FlatSat proxy, with the Neutron 2 payload board. The October mission-ops sequence also requires COMMS and the ground SDR. The current software-only stage does not establish those hardware paths.
- **Dedicated ground host (recorded October 8):** Use a separate Raspberry Pi 5 running 64-bit Ubuntu Linux to host Yamcs and connect to the SDR. Students access the web interface through the router's LAN without installing the repo or Yamcs. Start with an appropriately attenuated coax RF connection between SDR and SatNOGS, then transition to antennas. The SDR work is owned by another team member; agree the recovered CCSDS frame/packet handoff to Yamcs. Hardware operation replaces the native F′ simulator and PTY link while retaining the Yamcs and SDR ground services. This is a plan, not deployment or radio acceptance. See the [ground-host plan](../integration/GROUND_HOST.md) and [Yamcs primer](../operations/YAMCS_BASICS.md).
- **CDR mode scope:** Use pass-through commands; no mission modes are required. EPS, scheduling, SOH, and ADCS/geo-based commanding are not required for the October MVP.
- **Payload data:** The payload supplies raw science data. The accepted simulator demo delivers its raw CSV through the software ground path and displays a count-frequency histogram derived from Yamcs-retrieved bytes. This is not a detector-energy histogram. The payload team provides the JAR for actual science viewing. Our FSW scope is opaque raw-file acquisition, integrity, storage, and downlink; its file-transfer boundary remains to be agreed.
- **Ownership:** Dennis owns OBC F′ and Yamcs integration, including the F′ SatNOGS component/driver. Aris owns the payload. Sam and Tierra own SatNOGS firmware and its SPI development/integration. The public payload transport and software contract is not yet confirmed.
- **Historical evidence:** The October 7 local Yamcs ping and manual 26-byte stock FileDownlink retrieval remain recorded in the [local Yamcs runbook](../development/YAMCS_LOCAL_TESTING.md). They are compatibility evidence only; they do not prove the payload command path, raw-data path, SatNOGS/SDR path, or either milestone end to end.
- **Evidence boundary:** Keep source inspection, local Yamcs simulations, target builds, payload/OBC integration, RF/FlatSat demonstration, and flight qualification distinct. Do not promote a simulation or old demo record to hardware acceptance.

## October 2026 CDR MVP

Mission Ops defines this end-to-end sequence:

1. Yamcs issues a pass-through science-collection command.
2. The command travels `Yamcs/ground → SDR → SatNOGS → OBC → payload`.
3. The payload collects for the requested duration and transfers raw science data to the OBC.
4. The OBC returns the raw data through `SatNOGS → SDR → ground/Yamcs`.
5. The operator can inspect the raw science data; ideally, ground software also derives and displays a histogram from the received raw file.

The MVP requires PLD and COMMS, and does not require modes. Mission Ops lists onboard storage/retrieval and file management as a point to confirm with FSW. It has not approved a fallback if the required SatNOGS/SDR hardware path is unavailable. A wired PLD/OBC exercise can provide useful integration evidence, but it is not the specified full-RF CDR acceptance.

## December 2026 FSR target

The FSR FlatSat adds PLD, OBC, EPS, COMMS, and ground. Starting in Base Mode, Yamcs schedules a collection-mode transition for time X. The command arrives through `SDR → SatNOGS → OBC`; F′ executes it at the scheduled time, powers the payload through EPS, and transitions the payload to acquisition. After the requested duration, the payload enters standby and the OBC commands processing mode to retrieve the raw data. F′ then returns to Base Mode and powers the payload off. The science product is downlinked through SatNOGS and SDR to Yamcs/ground.

Required FSR behavior is nominal modes, the listed subsystems, and time-based collection. Minimal SOH display is desirable. If additional scope is possible, SAFE is the highest-priority extra mode among SAFE, LEOPS, and EE&CO. ADCS, geo-based commanding, and HIL D2S2 depend on hardware availability and rank below the core FSR sequence.

## Software slice A: literal pass-through first

The first authorized implementation slice is a synthetic Yamcs-to-F′ pass-through against a simulated payload facade:

`Yamcs dummy command → F′ facade unchanged → simulated payload response → correlated Yamcs observation`

The facade must preserve the supplied literal command bytes/string without interpreting private opcode meaning. Use a dummy string in simulation; do not invent or issue a real payload opcode. Show the returned outcome correlated to the request in Yamcs. Use consistent F′ types and framework framing; do not add a test-tool length policy that conflicts with the actual F′ buffer configuration.

This proves only the public software seam. It does not define the real payload protocol or prove the physical payload interface. Preserve the existing `MissionApp → ScienceApp → PayloadManager → driver` ownership pattern unless source evidence demonstrates a need to change it; do not create a second mission authority.

**October 8 implementation/evidence:** `payloadManager.SYNTHETIC_PASSTHROUGH(requestId, literalCommand)` forwards to the simulated driver and returns a correlated `SyntheticPassthroughResponse` with status `SIMULATED_ECHOED`. Yamcs verified exact 59-byte and 128-byte ASCII literals; mode stayed BASE. This bounded facade uses a 128-byte printable-ASCII demo contract, distinct from Aris's unresolved protocol. See the [confirmed A operator walkthrough](../operations/walkthroughs/PASSTHROUGH.md). Slices C and B were accepted later for the local software profile; see their separate records below and in the [gap plan](SDD_GAP_PLAN.md).

The [A walkthrough](../operations/walkthroughs/PASSTHROUGH.md) documents slice A only. Its screenshots were captured after Yamcs acceptance; it does not document the later C/B flows or establish payload hardware, RF, or full CDR acceptance.

## Software slice C: serialized outcomes and recovery (accepted for local software scope)

`PayloadManager` is the sole admission and serialization point for every payload operation: literal pass-through, the current capture request, and any legacy or scheduled capture entry. All routes must enter the same arbiter before dispatching to a driver. Permit one in-flight operation. Any competing valid request gets `BUSY` without driver dispatch, including a request that reuses the active external request ID. Zero synthetic request IDs or explicit legacy collection IDs, empty literals, and invalid durations get `INVALID`; a missing/unavailable driver gets `DRIVER_UNAVAILABLE` without dispatch.

Every admitted request carries a Yamcs-visible request ID and an internal operation generation. A valid request that reuses an active request ID gets `BUSY` like any other competing request. Synthetic request IDs and explicit legacy collection IDs must be nonzero; duration-only commands allocate IDs internally, and `requestIn(0, duration)` requests allocation. Empty literals and invalid durations get `INVALID`. If a caller reuses an ID after completion, the new generation keeps it distinct from old callbacks. Emit `ACCEPTED` once dispatch begins, then exactly one terminal outcome for that request/generation. Admission rejections use generation zero and return their outcome without `ACCEPTED`. Ignore duplicate callbacks, callbacks after a terminal outcome, and callbacks whose generation is stale. A repeated request ID must not let an older response complete a newer operation.

Only a successful capture whose product descriptor/data pass validation may be forwarded to `ScienceApp` or stored. A successful literal pass-through is a command result and creates no capture/product record. `FAILED`, `TIMED_OUT`, `BUSY`, `INVALID`, `DRIVER_UNAVAILABLE`, stale, and duplicate results must never announce a completed collection or create a science product/storage record. Command acceptance remains distinct from operation completion.

Bound simulated capture child execution. On capture timeout or `HANG_CAPTURE`, the manager reports one `TIMED_OUT`; the driver terminates and reaps its child. Driver availability remains false until reap, preventing a new capture from overlapping the old child. A subsequent normal request must complete after availability returns.

Fault injection is local-profile-only through Yamcs command `CONFIGURE_SIMULATION`. It selects one fixture for the next admitted operation, then returns to `NORMAL`; the unavailable fixture is consumed by its simulated rejection. Supported fixtures are `NORMAL`, `FAIL`, `NO_RESPONSE`, `DELAYED_RESPONSE`, `DUPLICATE_RESPONSE`, `HANG_CAPTURE`, and `DRIVER_UNAVAILABLE`. A configured delay can complete normally or deliver a callback after the deadline, allowing the late response to be observed and ignored after `TIMED_OUT`. These controls model software tests, not payload protocol behavior. The command is rejected when the local profile is OFF.

**October 8 C acceptance:** the local Yamcs lifecycle run passed all 31 checks, including serialized admission, terminal outcomes, fault injection, stale/duplicate-response handling, bounded child cleanup, and recovery. The A regression also passed, and all 8 ScienceApp unit tests passed. Exact run artifacts and binary/dictionary hashes are recorded in the [SDD gap plan](SDD_GAP_PLAN.md#slice-c-acceptance-record-2026-10-08). This C result covers the local software profile only; B has its own later acceptance record. Neither establishes payload hardware, RF, or CDR acceptance.

Use the [lifecycle operator walkthrough](../operations/walkthroughs/LIFECYCLE.md) and reproducible [lifecycle runner](../../tools/yamcs/lifecycle.sh). The walkthrough records local C scope; it does not establish B or hardware/RF acceptance.

## Payload and product contract still needed

**October 8 follow-up authorized:** extend the accepted B software path with a KISS synthetic pulse fixture. Generate fake raw ADC pulses, deliver them through the existing storage/channel-1/Yamcs receipt path, and derive waveform, integrated-charge spectrum, and PSD density plots on the ground. Label all views SIMULATED; defer figure of merit and real calibration. The count-CSV profile remains a regression baseline. See the [synthetic pulse implementation plan](../verification/SYNTHETIC_PULSE_ACCEPTANCE.md); local software acceptance passed on October 8, including independent Yamcs raw readback/plot calculations, packet recovery, and browser download. See the [accepted operator pictures](../operations/walkthroughs/PULSE_SCIENCE.md).

Aris's payload board is expected to produce raw science data. The exact collection command, duration units, transport, response semantics, raw-data framing/file boundary, and completion/integrity indicators remain unconfirmed. Do not assume the older USB-to-RS-422 proposal is the current physical interface. Keep Aris's private protocol/encoding out of mission logic and expose only an agreed public interface.

The local ground viewer parses the accepted simulator CSV schema (`t_s,counts,flag`) from Yamcs-retrieved raw bytes and displays a count-frequency histogram. This is a software demonstration of ground-side processing, not a detector-energy histogram or a validated science product. The payload team's JAR owns real science interpretation/display. Real raw samples will not be supplied for this software work; the FSW file-transfer contract remains open.

## Validation and integration sequence

All board-free functional acceptance is commanded and observed through Yamcs. A build or service-start result is setup evidence, not mission acceptance. Implement and validate the software slices in this order:

1. **A — pass-through:** Yamcs sends a synthetic literal string to a simulated payload facade; Yamcs shows the unchanged value at the facade and a correlated response.
2. **C — truthful outcomes (PASS, local software scope):** Yamcs lifecycle probe passed all 31 checks. The A regression passed and ScienceApp unit tests passed 8/8. See the evidence record in the gap plan. Source/build checks remain separate from these functional results.
3. **B — nominal raw-data cycle (PASS, local software scope):** `scienceApp.COLLECT_AND_DOWNLINK(durationSeconds)` automatically collects simulator data, validates/stores the product, sends immutable bytes on custom channel 1, reconstructs them independently at the local ground adapter, then uploads and reads back the raw object through Yamcs. The verified receipt carries run/product/transfer identity, byte count, CRC16, and SHA-256. The viewer derives a count-frequency histogram from the received simulator CSV. See the [B acceptance record](SDD_GAP_PLAN.md#slice-b-acceptance-record-2026-10-08) and [B operator walkthrough with screenshots](../operations/walkthroughs/RAW_CYCLE.md). This does not implement Aris's real command or raw-data contract.
4. **CDR integration:** substitute the real payload and Pi Zero W interfaces, then the required SatNOGS/SDR path. Record wired and full-RF evidence separately. Do not claim CDR acceptance from the local simulation.
5. **FSR extension:** add the agreed Base/collection/processing transitions, time-based execution, EPS payload power control, and return to Base; then validate the complete scheduled flow through Yamcs.

## Open decisions and questions

1. **Payload command and transport:** What exact public pass-through command syntax and duration units should F′ send? What electrical/software transport does the PLD expose to the Pi, and what readiness/response signals does Aris's interface provide?
2. **Aris production lifecycle:** The local C contract defines request ID/generation, `ACCEPTED`, and one terminal result (`COMPLETED`, `BUSY`, `INVALID`, `DRIVER_UNAVAILABLE`, `FAILED`, or `TIMED_OUT`). Confirm which of these the real Aris interface can report, its collection-start/progress/cancel behavior, and its real operation deadline and late-response rules before substituting the payload driver.
3. **Raw product boundary:** How does the payload delimit a raw product and identify its collection? What format, expected size/range, timestamp, and integrity indicator are available? Who finalizes the file on the OBC?
4. **Ground delivery:** The local software receiver and Yamcs receipt are accepted, but which interface carries and reconstructs science bytes across the real SatNOGS/SDR path? What constitutes verified operator receipt there? Does Mission Ops require onboard persistence/file management for CDR?
5. **SatNOGS integration:** What SPI contract, pin/reset mapping, host endpoint, framing, throughput, and firmware readiness are Sam/Tierra establishing? How will Dennis's F′ driver and the firmware endpoint be exercised together?
6. **Science view (resolved October 9):** use the payload team's supplied JAR for actual science viewing. FSW acquires/stores/downlinks opaque raw bytes. The local synthetic viewer remains a regression fixture; real sample files will not be supplied for this work.
7. **Scheduled FSR behavior:** Is time X absolute UTC or a relative delay? What clock-validity, restart, lost-link, cancellation, and persistence rules apply? What are the agreed mode names and payload-ready/EPS sequencing signals?
8. **Milestone fallback:** If SatNOGS/SDR cannot be demonstrated by end of October, what evidence—if any—will Mission Ops accept as an approved fallback? No fallback is currently recorded.

Record answers with an owner and date. Until then, use synthetic commands and payload data in software simulations and leave physical transport assumptions open.

## October 9 scope update and next authorized slices

Dennis authorized **D: Yamcs completion verification** and **E: durable raw-product storage/restart recovery**, with functional testing through Yamcs. See the [implementation and acceptance plan](../verification/COMPLETION_STORAGE.md). Real payload samples will not be supplied for this work. The payload team provides the science-viewing JAR; our FSW scope is acquiring, storing, and downlinking opaque raw science bytes. Existing synthetic plots remain test fixtures. SatNOGS/SDR is being developed by another team. Public payload/transport integration remains a separate interface boundary, not a prerequisite for completing D/E using synthetic files.


October 9 software acceptance: completion verification and durable raw storage/restart recovery passed through Yamcs (six scenarios plus A/C/B and pulse regressions). See the [D/E implementation and acceptance record](../verification/COMPLETION_STORAGE.md). This is host-native synthetic raw-byte evidence, with actual payload viewing owned by the supplied JAR and SatNOGS/SDR owned by the other team.
