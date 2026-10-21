# CDR TCP / stock FileDownlink local acceptance — October 20, 2026

**PASS: native F′ and real Yamcs over loopback, with a fake PTY/PDU.** This validates the direct ComCcsds/TCP profile and stock FileDownlink. No network mux was added. Physical UART mux channel 2 remains independent for Teensy/PDU RPC. It does not establish Pi runtime, payload hardware, electrical integration or CDR hardware acceptance.

Use the [current plan](../../../planning/CDR_TCP_YAMCS_IMPLEMENTATION_PLAN.md) and [operator runbook](../../../operations/CDR_TCP.md). The [acceptance record](acceptance.json) preserves original Yamcs command/event records, independently received file hashes, and binary/dictionary identity. Runtime paths in those records are provenance; full logs and received bytes remain under the ignored `yamcs/run/` directories.

| Local check | Result |
| --- | --- |
| Actual F′ TCP server → stock ground TCP/CCSDS bridge → Yamcs PING/Pong | PASS, fresh correlated response |
| Supplied config/SOH CSV | PASS, 729 bytes; independent Yamcs GET equals source bytes and SHA-256 |
| Supplied raw-science CSV | PASS, 606273 bytes; independent Yamcs GET equals source bytes and SHA-256 |
| Fake UART/PDU | PASS before a TCP client, during the large transfer (15 completed RPCs), and while disconnected; only channel 2, zero fake-PDU errors |
| TCP fragmentation and mid-transfer close | PASS; interrupted object absent, fresh PING and new SendFile succeed after reconnect; interrupted object still absent after recovery |
| Missing source | PASS negative case: FileOpenError and no received object; helper reports FAIL |
| Retained-product helper | PASS; fresh SELECT_PRODUCT metadata → stock SendFile → independent bytes/hash |
| Unsupported automatic-delivery commands | Both reject with VALIDATION_ERROR before capture/token allocation in CDR; collection-only SCIENCE_CAPTURE still passes |
| Startup cancellation | PASS; SIGINT while starting stops both owned process groups in 0.444 seconds; [record](startup-cancellation.json) |
| Existing local Yamcs demo | [Passthrough PASS](legacy-passthrough.json), [pulse collection/downlink/readback PASS](legacy-pulse-cycle.json) |

The samples retain their supplied filenames and exact bytes; [fixture identities](fixture-manifest.json) match the checked-in opaque fixtures. The small sample needs at least 2 stock data packets; the large sample needs at least 1215 at the configured maximum of 499 payload bytes per packet. No payload decoder, detector calibration or real payload capture is claimed.

The stock unpaced ground bridge lost large-file UDP datagrams in an earlier local attempt. The final bridge reuses the packaged stock TCP client, TM-frame aggregator, UDP adapter and PacketBridge; a small UDP wrapper enforces a 5 ms gap without catch-up bursts. FileDownlink itself remains stock. No framework/dependency or host-wide socket setting was changed. The [ground manifest](ground-manifest.json) records both processes and the cadence. This is a tested local default; Pi 5 behavior remains to be measured. Stock transfer provides no selective resume/retransmission guarantee; operators must verify receipt and issue a fresh transfer after interruption.

Build and targeted test evidence:

- Native CDR build: PASS; native local-Yamcs profile rebuild and runtime regressions: PASS. [Summary and profile settings](validation-summary.json).
- Before publication, the unchanged satellite Teensy firmware compiled successfully with the repository build script. [Compile log](teensy-prepush-build.log). No flashing or hardware operation was performed.
- [ScienceApp CDR](scienceapp-cdr-ut.log): 9/9; [UART mux CDR](uart-mux-cdr-ut.log): 2/2; [ScienceApp legacy](scienceapp-legacy-ut.log): 10/10.
- [Ground tools](ground-tools-ut.log): 17/17, including pacing, cancellation, owned-group cleanup, profile validation and integrity checks.
- [Profile guard checks](profile-guards.json): the UART simulator launcher rejects CDR artifacts, and the CDR executable rejects TCP port zero before startup.
- UART unit tests emitted stale coverage-file merge warnings after passing. These logs provide test outcomes, not coverage measurements.
- [Source hashes](source-sha256.json) bind the implementation/tests/fixtures/configuration to this result. The pinned F′ submodule is unchanged.
- [Attempt ledger](attempt-ledger.json) retains earlier failures and both passing runs. The canonical acceptance JSON is the final run after the command-rejection and startup-cancellation fixes.

Separate remaining gates: ARMv6 Zero W build/runtime, Pi 5 installation and LAN, real payload USB↔RS-422 and raw-file boundary, and real Teensy/PDU power-on/readiness/collection/power-off. SatNOGS/SDR/RF stays outside CDR. No commit, push, target deployment, flashing or hardware operation was performed for this acceptance.
