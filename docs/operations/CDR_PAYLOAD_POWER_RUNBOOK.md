# CDR payload power and collection runbook

Draft v0.3 from N2 (application layer), 2026-11-04, for review, matched to `99e1682`. It covers CDR steps 2 to 5 of [DEVELOPMENT_INTENT.md](../planning/DEVELOPMENT_INTENT.md) and [PDU.md](../integration/PDU.md): payload power on, prove it, collect, download, power off, prove it. The check script is [`tools/yamcs/cdr_runbook_check.py`](../../tools/yamcs/cdr_runbook_check.py). Its expected results are at the end of this guide.

Running this switches real power. That needs separate authorization and the EPS owner at the bench. Evidence so far is a laptop rehearsal with a fake PDU and a simulated payload, which is not a hardware result.

## Roles

| Role | Does |
| --- | --- |
| Operator | sends the commands in Yamcs and reads every proof aloud |
| EPS owner | PDU wiring, says "go" before any power command, measures payload power on and off, removes power by hand if needed |
| Payload owner | payload state, warm-up, ready |
| Recorder | times, screenshots, evidence files |

## Values

| Value | Use | Source |
| --- | --- | --- |
| PDU | Artemis PDU v2.2, firmware 2.2.2 | [PDU.md](../integration/PDU.md), `external/artemis-pdu` |
| Payload rail | `RAIL_12V` (`Components.PduSwitchableRail` = 7, the 12 V output) | The ICD names no Artemis PDU rail for the payload, so N2 uses the 12 V output. EPS owner to confirm |
| Rail state | channel `epsManager.Rail12V`: `UNKNOWN`, `OFF`, `ON` or `STALE` | [PDU_READABILITY.md](PDU_READABILITY.md) |
| Freshness | a rail state goes `STALE` after 3 driver ticks with no fresh reading (about 8 s), or at once after a link failure. It is the enable pin, not a measured voltage | [PDU_READABILITY.md](PDU_READABILITY.md) |
| Never command | `RAIL_5V_1` (rail 3, the Pi Zero's own 5 V) and `RAIL_5V_2` (rail 4, Kapton heater). Both are still in the `SET_PDU_RAIL` menu | Artemis 5 V switch list, `Types.fpp` |
| Answer time | a power command finishes within about 4 s (2 driver ticks of 2 s) or fails | `PDU_REQUEST_TIMEOUT_TICKS = 2`, driver on `rateGroup2` |
| Proof limit | 8 s | answer time plus one 2 s status poll |
| Warm-up after power on | 15 s, provisional | payload health starts about 15 s after power-on. Payload owner to confirm |
| Payload ready signal | none in flight code yet | PayloadManager only checks that its driver is idle |
| Capture length | 1 to 120 s | `ScienceApp` |

## Steps

| Step | Send | Proof before moving on | If not |
| --- | --- | --- | --- |
| S0 Start | spacecraft process first, then the ground. Wait for `Event processor running` | `EpsStatusUpdated` events reach Yamcs | F1 |
| S0b Firmware | `epsManager.GET_PDU_INFO` | command completes OK, `PduInfoResult` shows `protocol=2 firmware=2.2.2` and no dirty-build flag. Record the `git=` prefix | other version or dirty build: stop. Binary and dictionary must come from the same build |
| S1 Link | `missionApp.REPORT_MODE` where available, else `missionApp.PING`. Optional: `epsManager.GET_ALL_PDU_RAILS` | `Mission mode is BASE` (or `Pong`) and `OpCodeCompleted`. `DriverLinkState` = 2, `EpsHealthState` OK, `Rail12V` not `ON` | F1. `Rail12V` already `ON`: stop, ask the EPS owner |
| S2 Power on | EPS owner says go. `epsManager.SET_PDU_RAIL` rail `RAIL_12V`, desiredState `ON`, confirmation `CONFIRM` | within 8 s, all three: the command completes OK, `PduRailSetResult rail=RAIL_12V desired=ON readback=ON result=OK`, a fresh `Rail12V` = `ON`. Then the EPS owner's measurement shows the payload powered | `BUSY`: nothing was sent, wait 4 s, send once more. Anything else: F2 |
| S2b Warm-up | wait 15 s (provisional) | payload owner confirms ready | F3 |
| S3 Collect | `scienceApp.SCIENCE_CAPTURE` durationSeconds | `ScienceProductCommitted product=N ...`. Record N | F4 |
| S3b Tidy | `missionApp.ENTER_BASE_MODE` | `ModeChanged` to BASE (`CollectionCancelled ... 0s remaining` is normal) | note it, continue |
| S4 Download | `./tools/yamcs/downlink_stock.sh --product-id N` | helper PASS and an evidence file | F5 |
| S5 Power off | `epsManager.SET_PDU_RAIL` rail `RAIL_12V`, desiredState `OFF`, confirmation `CONFIRM` | within 8 s: the command completes OK, `PduRailSetResult rail=RAIL_12V desired=OFF readback=OFF result=OK`, a fresh `Rail12V` = `OFF`. The EPS owner measures off and confirms no other supply path (the USB to RS-422 adapter is one) | `BUSY`: wait 4 s, send once more. Anything else: F6 |
| S6 Stop | Ctrl-C the ground, then stop the spacecraft process (it needed SIGKILL on 2026-10-20) | evidence saved | none |

S3b is needed because the CDR build has no CommsApp, so nothing moves MissionApp past `SCIENCE_READY`. Without it every later capture logs `ModeUpdateRejected`.

## Reading the power proof

- Read the named result. `PduRailSetResult` names the rail, the state asked for, the readback and `result=OK`. `PduRailSetMismatch` is a failure even though the PDU answered. `PduOperationError` says where a request failed: `DRIVER`, `TEENSY_RPC` or `PDU`.
- `status=0` means the PDU protocol succeeded, not that a rail is off.
- A Yamcs command report alone is not proof. Use the events and a fresh `Rail12V`.
- `CANCEL` is refused without sending anything (`PduCommandRejected`).
- Command OK means the PDU answered and agreed. Busy, timeout, a malformed answer or a PDU refusal give `EXECUTION_ERROR`.
- `BUSY` means the routine status poll was in flight and nothing was sent. Wait, then send once more ([PDU_READABILITY.md](PDU_READABILITY.md)).
- The rail state is the enable pin, not a measured voltage, and not proof that the payload is ready. Physical proof is the EPS owner's measurement or payload telemetry.

## Failure signals

| Signal | Meaning | Action |
| --- | --- | --- |
| `PduRailSetMismatch` | the PDU answered, but the rail is not in the state asked for | F2 (on) or F6 (off), tell the EPS owner |
| `PduOperationError origin=... reason=...` | the request failed in the driver, the Teensy link or the PDU | F2 or F6. Record origin, reason and code |
| `Rail12V` = `STALE` | no fresh reading for about 8 s, or a link failure | do not trust ON or OFF. `epsManager.GET_PDU_RAIL` rail `RAIL_12V` once |
| reply `BUSY` | another EPS request is running, nothing was sent | wait 4 s, resend |
| reply `EXECUTION_ERROR` | no confirmed PDU answer | read `LastDriverStatus`, then F2 or F6 |
| `LastDriverStatus` 249 | readback mismatch | F2 or F6, tell the EPS owner |
| `LastDriverStatus` 250 or 251 | malformed answer payload or frame | F2 or F6 |
| `PduRequestTimedOut ... local request=N` with `PduRequestFailed ... status=3` | no answer within 2 driver ticks | F2 or F6. Match N to `PduRequestQueued` |
| `DriverLinkState` 3 | Teensy, UART or timeout error | F1 |
| failure events stop | `PduRequestFailed` and `PduRequestTimedOut` are throttled to 5 per run | watch `TransportFailureCount` |

## Failure handling (proposal, Mission Ops decides)

| Code | When | Do |
| --- | --- | --- |
| F1 | no answer at S0 or S1, or EPS link not OK | stop, no power commands. EPS owner follows [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| F2 | power on not proven within 8 s | S5, then stop. Record `LastDriverStatus`, `DriverLinkState` and the events |
| F3 | payload not ready after warm-up | S5, then stop |
| F4 | no `ScienceProductCommitted`, or a rejection or failure event | S5, then stop. Keep any stored product |
| F5 | download not PASS | S5 first, then `FileHandling.fileDownlink.Cancel`, wait 3 s, rerun the helper with a new destination. At most 2 tries |
| F6 | power off not proven within 8 s | send off once more. Still on: the EPS owner removes power by hand. Never leave the payload powered unwatched |

## Verification script and expected results

`tools/yamcs/cdr_runbook_check.py` walks S0 to S6 through the Yamcs HTTP API and saves PASS, FAIL or SKIPPED for every step in one JSON evidence file. It only ever commands `RAIL_12V`, refuses rails 3 and 4 before anything is sent, and sends power off on every exit path after a power-on attempt.

Laptop rehearsal, software only (fake PDU `StatefulPdu` from `test_pdu_readability.py`, simulated payload, 127.0.0.1):

```bash
./tools/yamcs/build_cdr_tcp.sh
tools/yamcs/.venv/bin/python tools/yamcs/cdr_runbook_check.py --rehearse-on-laptop
```

Bench, against a stack someone already started, with an operator at the keyboard:

```bash
tools/yamcs/.venv/bin/python tools/yamcs/cdr_runbook_check.py --dictionary <matching dictionary> --allow-power
```

Without `--allow-power` the script sends no EPS command. With it, the operator types `GO` before power on and `READY` after the EPS owner has measured power and the payload owner says ready.

Expected results:

| Step | Laptop rehearsal | Bench |
| --- | --- | --- |
| S0 events flow | PASS | PASS |
| S0b firmware 2.2.2, clean build | PASS | PASS |
| S1 link answered, `DriverLinkState` 2 | PASS | PASS |
| S1b `RAIL_12V` not on | PASS | PASS |
| S2 power on proven | PASS | PASS |
| S2b measured on and ready | SKIPPED, nothing to measure | PASS after the operator types `READY` |
| S3 `ScienceProductCommitted` | PASS | PASS |
| S3b back to BASE | PASS | PASS |
| S4 download, byte for byte | PASS | PASS |
| S5 power off proven | PASS | PASS |
| S6 end state | PASS, every fake rail off | operator confirms |

Last rehearsal: 2026-11-03, `99e1682` with the then-open mode and SOH pull requests merged locally. All steps as above. The real PDU, the real payload, warm-up and ready have not been rehearsed.

## Open items

- Current capacity of the 12 V output.
- Whether rails 3 and 4 should be blocked from mission commands.
- Payload warm-up time and ready signal.
- Mission Ops agreement on F1 to F6, including whether and when power is removed on each failure ([PDU.md](../integration/PDU.md)).
