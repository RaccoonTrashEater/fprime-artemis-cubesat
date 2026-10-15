# N2 synthetic pulse science demo — October 8, 2026

**KISS:** make fake detector pulses, deliver their raw samples through the working Yamcs demo, and plot waveform, spectrum, and PSD on the ground. Dennis authorized implementation on October 8. **Status: implemented and accepted in the local software profile; goal complete.**

1. Generate two synthetic pulse populations with different decay tails, varied heights, and baseline noise. Use a repeatable seed and two events per simulated exposure second. Capture duration describes synthetic exposure, not wall-clock acquisition.
2. Store/downlink the versioned raw samples through the existing F′ product descriptor, custom channel-1 receiver, and verified Yamcs raw object/receipt. Keep the count-CSV profile for A/C/B regression.
3. Derive waveform, integrated-charge spectrum, and pulse-shape discrimination (PSD) density plots from independently received raw data. Clearly label all three SIMULATED. Keep figure of merit, detector calibration, physical energy units, and real PLD decoding deferred.
4. Confirm the complete flow using Yamcs commands and returned events/telemetry before taking operator screenshots. Verify raw identity/size/CRC/SHA and compare plots against independently downloaded samples; exercise packet-loss/corruption recovery and failed/invalid captures.

## Bounded simulator contract

`n2-pulses-v1` is a demonstration JSON schema, not Aris's ICD. It contains `simulated=true`, exposure duration, deterministic seed, ADC resolution, sample interval, integration gates, and events with ID/timestamp/channel plus 64 integer ADC samples. There are 2 events per exposure second (2–240 events for the existing 1–120-second command range). The two pulse populations are synthetic waveform shapes, not validated neutron/gamma classifications. Truth labels are not supplied to the ground plots.

For the initial fixture: sample interval 10 ns, 12-bit ADC, first 8 samples for baseline, total integration samples `[8,64)`, tail integration `[20,64)`. Subtract the baseline and clamp negative residuals to zero. Ground computes total charge, tail charge, and `PSD = tail / total`. Spectrum axes use ADC-sample area and event count; PSD uses integrated charge versus dimensionless ratio, with color representing event count. No keV, MeV, flux, or detector-performance claims.

Charge integration and pulse-shape ratios are conventional analysis methods; gate values and pulse parameters here are fixture assumptions. [CAEN explanation](https://edu.caen.it/experiments/implementing-a-pulse-shape-discriminator-psd-based-on-ratio-between-areas/).

## Files and local setup

- Generator: `tools/yamcs/pulse_sim/neutron_payload_sim.py`.
- Ground analysis/viewer: `tools/yamcs/pulse_analysis.py` and `science_viewer.py`.
- Launcher: `./tools/yamcs/run_pulses.sh`; ordinary `run.sh` retains the count-CSV profile.
- Acceptance: `./tools/yamcs/pulse_cycle.sh` on a fresh otherwise idle pulse stack.

The pulse profile uses 32 data packets per one-second tick in `NEUTRON2_LOCAL_YAMCS=ON`; the normal count-CSV and OFF/hardware profile retain one packet per tick. This is laptop demo pacing, not an RF throughput result. File validation/snapshotting, packet CRC, retries, raw-file integrity checks, and source retention remain required. No modes, schedules, EPS, board actions, or physical RF operation are added.

## Next real-data inputs

**October 9 scope update:** no real payload sample file will be supplied for this work. Actual science viewing uses the payload team's provided JAR. Onboard FSW acquires, stores, and downlinks the raw file as opaque bytes; a real waveform parser, calibration, and FOM implementation are outside our scope. The public acquisition/file-transfer contract still needs agreement for later hardware substitution. The existing Pi Zero W and SatNOGS SPI/SDR integration tasks remain separate. The [user-provided reference screenshot](images/n2-pulse-science-2026-10-08/expected-science-display.png) establishes desired views, not those numerical contracts. It is a reference image, not a screenshot of this demo.

## Acceptance evidence

The first automated run, `yamcs/run/20261008-143626/pulse-cycle-d7ef4045fd96.json`, passed at 14:39:34 HST. Independent raw readback and plot calculations passed, including recovery of one dropped and one corrupted packet. The subsequent browser replay exposed a JavaScript string escaping error in the page, despite valid API results. The HTML string was corrected and its script passed `node --check`; final acceptance and screenshots use a fresh run after that correction. Preliminary captures are retained separately and are excluded from the final operator guide.

Validation before final replay: native ON build; six F′ component suites with 31 cases; 16 ground Python cases and five generator cases. After the page fix, the seven pulse-analysis and four viewer cases passed again in the project Python environment. The default system Python lacked `pyserial`; that failed test invocation was an environment mismatch, then repeated using `tools/yamcs/.venv/bin/python`.

The count-CSV regression run `yamcs/run/20261008-143103/` passed A, all 31 C lifecycle checks, and B (`raw-cycle-3c14d3b21839.json`). An earlier B attempt correctly rejected a stack that had not settled to idle BASE; its failed record is retained. These regressions used the same native binary/dictionary as the pulse demo. The later page escaping repair changes rendering only.

Final repaired acceptance: `yamcs/run/20261008-144213/pulse-cycle-fc3dff12dcdd.json` — **PASS**. Current-run A also passed (`passthrough-ec29f0f5dfea.json`). The browser replay independently downloaded product 3 and matched the receipt; waveform selection and all three rendered plots were verified. See the [accepted operator walkthrough with seven pictures](N2_PULSE_SCIENCE_OPERATOR_WALKTHROUGH_2026-10-08.md) for product hashes, build/dictionary identity, timing, and repeat instructions. The real PLD parser/calibration and Pi/SatNOGS/SDR hardware gates remain open.
