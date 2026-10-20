# N2 Claude Opus 5.5 review and Codex verification — 2026-10-07

> Historical October 7 review, retained October 19. Findings describe that reviewed snapshot, not an assertion of current defects; current decisions are in [development intent](planning/DEVELOPMENT_INTENT.md).

**BLUF:** Opus supports the architecture and the recorded Yamcs ping / nominal stock-file receipt. The setup needs a build-profile guard, narrower browser access, and better run traceability before new mission features depend on it. The recorded PASS remains valid; it is one nominal compatibility run, not repeatability, complete mission integration, or hardware evidence.

## Review provenance and scope

- Requested and reported model: `claude-opus-5-5`; invoked with `--effort high` through the Claude subscription skill (historical host-local path: `/Users/sozodennis/.codex/skills/use-claude-subscription/SKILL.md`).
- Subscription authentication was `claude.ai` / Pro. No Anthropic API credentials were set. Quota preflight passed: session 91% and weekly 32% remaining. No alternate model was used.
- Session: `8dd48119-fdae-4e08-86b4-a403f081c6e1`; approximately nine minutes; completed successfully with no tool permission denials.
- Review was read-only (`Read`, `Glob`, `Grep`); no subagents, service actions, code changes, hardware actions or connector use.
- Reviewed `neutron2-develop`, base `33aef0a186205e27d0a05be5a570614ef223de8c`, plus uncommitted local Yamcs configuration/tooling and dated SDD/intent/plan/evidence documents. Pre-existing Arduino build-script changes were excluded.
- Claude's original advisory report is preserved below. Codex checked the material claims against source and performed only read-only GET/OPTIONS HTTP checks. No fixes, repeat collection runs, rebuilds or shutdowns were performed during this review.

## Verified findings and recommended order

| Priority | Finding / evidence | Disposition and next action |
| --- | --- | --- |
| P2 | **Launcher does not verify local sizing.** `tools/yamcs/local_stack.py:23–30` only checks artifact existence and PING name. Local/RF profiles share the cache and installed paths. | Confirmed. Require dictionary constants / build provenance matching the local profile before launch, and record them. Consider separate build/artifact directories. The installed dictionary currently has COM-related local settings, TM frame 1024 and command/generic string sizes 504; this does not guard a later RF rebuild. |
| P2 | **Any allowed browser origin can read the anonymous local API.** `yamcs/config/etc/yamcs.yaml:6–8` permits `*`; evidence commands use guest. | Confirmed with localhost GET `/api/instances` and OPTIONS `/api/processors/fprime-project/realtime/commands`, both HTTP 200 and `Access-Control-Allow-Origin: *`. Preflight permits POST and content-type. Remove unnecessary CORS or restrict to the Yamcs origin. No cross-origin command was executed; browser private-network controls were not evaluated. This is localhost browser access, not demonstrated Internet exposure. |
| P2 | **Traceability is incomplete.** `local_stack.py:62–71` records binary/dictionary hashes but not source dirty state, script/config/dependency versions or hashes. Diagnostic failures are not all dispositioned in the runbook. | Confirmed. Add an attempt ledger and source/config/tool hashes; retain a reproducible read-only validator. The saved independent recheck is valid historical evidence even though its script is not tracked. Repeated clean-start evidence should follow setup fixes; an arbitrary number of repetitions is not itself acceptance. |
| P3 | **Product command argument is discovered from host disk.** `demo.py:97–113` resolves the simulator's symlink before issuing SendFile. | Confirmed, but qualified: commands and returned observations still travel through Yamcs, and received bytes really came from Yamcs. This limits the claim to a diagnostic/manual transfer; a Yamcs-only operator needs a documented stable reference or product catalog/ID handoff. It does not invalidate stock-transfer compatibility. |
| P3 | **Clock interpretations need investigation.** Recorded Pong generation time is later than reception time; `demo.py:43–46` compares both generation/acquisition to Yamcs command/start time. | Confirmed inconsistency; cause unproven. Current acquisition/reception gates plus token/value checks protect the observed verdict. Generation comparisons across clocks can create misleading results on other targets. Prefer receiver-clock freshness plus operation correlation, and separately diagnose time decoding/synchronization. |
| P3 | **Shutdown/state management can be improved.** Shared lifecycle uses a 3-second termination grace; stop helper does not wait; current.json survives exit; cleanup is invoked twice. | Confirmed source behavior; no database corruption or accidental process kill observed. Use adequate Yamcs shutdown grace, idempotent cleanup, confirmed stop and explicit active/stopped run state. The immediate double close currently catches errors; the concern is robustness, not an observed failure. |
| P3 | **Parser recovery and runtime file permissions are weak.** Python adapter lacks channel/zero-length rejection or partial-frame timeout; run configuration containing the local signing key uses default permissions. | Confirmed static risks. Mirror protocol-validity checks and recovery without reintroducing a radio-derived size policy. Create key-bearing files with restrictive permissions from the start. No key content was read or disclosed during review. |
| P3 | **Portability/reproducibility documentation is unfinished.** Only macOS arm64 has evidence; WSL procedure, dependency integrity hashes and PDU revision preflight are absent. | Confirmed. Keep Linux/WSL unverified until exercised, add its setup path, and validate all required pins. This does not negate the tested macOS setup. |

## Qualifications to Claude's recommendations

1. **Do not prohibit all ARM targets.** Native Apple Silicon is the tested host. A guard should distinguish hardware/cross-deployment configuration from authorized native simulation; a blanket ARM prohibition would break this setup.
2. `fprime-util generate -f` explicitly purges its cache (verified from the installed tool's help). Thus a normal forced regeneration can select the default OFF profile; plain `build` keeps the cached ON value. The shared-artifact hazard is real. No regeneration was run for this review.
3. **FPP declaration sizes and onboard command parsing are distinct.** FileDownlink declares `string size 100` in `Svc/FileDownlink/Commands.fppi`, but its generated handler uses `Fw::CmdStringArg`; `Fw/Cmd/CmdString.hpp` sizes that storage from `FW_CMD_STRING_MAX_SIZE`, and `StringBase::deserializeFrom` validates against that capacity. There is no separate declared-100 check in the inspected handler. Ground dictionary/encoding and later component conversions may constrain use separately. Claude's statement that the onboard parser necessarily enforces the smaller of declared size and framework size is not established by this code.
4. **504 is configured capacity, not tested payload length.** The actual SendFile source argument was 86 bytes. Maximum-length and multi-argument combinations were not exercised. One 504-byte argument plus its two-byte length consumes the entire 506-byte argument buffer.
5. **Text preservation is not arbitrary binary preservation.** The intended literal opcode is text; future facade planning must define encoding and NUL/terminator behavior before choosing a string/byte-array contract. Do not infer a binary requirement or invent a new radio limit.
6. Broad CORS/authentication concerns are implementation findings. The SDD's single-authority wording does not alone establish a particular local login policy; decide that explicitly before real/private command material or hardware is introduced.
7. Raw command-history persistence is distinct from hiding private driver implementation. Current tests are synthetic. Decide whether real literal opcode arguments may be archived before real-driver integration.

## Diagnostic attempt ledger recovered during verification

| Run | Recorded result / disposition |
| --- | --- |
| `20261007-091554` | Ping passed; stock-file probes failed under legacy RF sizing (128-byte TC frame, then 40-byte onboard command string). These motivated the local profile. |
| `20261007-093330` | Initial CollectionCount freshness failure while app startup preceded usable ground telemetry. Ground-first startup was added; no receipt proof. |
| `20261007-094001` | Ping/configure event not received with an experimental uplink TC parser. It was replaced with unchanged-byte forwarding plus UART envelope. Cause is the recorded integration diagnosis, not replay proof against an archived script. |
| `20261007-094530` | Corrected adapter ping passed; no collection/receipt claim. |
| `20261007-095557` | Local-profile ping passed. Two probes failed: unchanged CollectionCount was incorrectly required newer than CONFIGURE; then an intermediate COLLECTING parameter was read before SCIENCE_READY arrived. Probe checks were corrected; native binary/dictionary were unchanged. |
| `20261007-100058` | Clean-start ping, one simulated collection and manual stock FileDownlink receipt passed with the corrected probe; independent read-only recheck passed. |

## Evidence conclusion

Codex recomputed the current artifact hashes and confirmed both match the passing manifest:

- Executable: `f887a737e10b2031af90996bc031aa34117d1dbe3c5159c9d7a37800a13f11a8`.
- Dictionary: `afd872e2c34ecfb16d0c9d842da9852b44becef981d525ea54767092d969b13b`.
- Passing run: `yamcs/run/20261007-100058/`; ping token `10071601`; product ID 1; independently retrieved 26-byte file with SHA-256 `210b3f4e188414be78fe12ff01285d994a0e5e88f0a6cd125c7f6648204fbc20` and source CRC 45394.

Both reviewers support these narrow claims. Neither treats them as complete mission integration, repeated-run reliability, maximum-capacity testing, post-change OFF-build proof, or hardware verification.

## Plan assessment and next slice

Keep the current application → manager → driver architecture and a single mode authority. After the local setup findings above are addressed, the next authorized-by-future-request mission slice is one synthetic literal-string command delivered unchanged to a simulated Aris-owned facade, with correlated outcome and driver-unavailable behavior observable through Yamcs. Correct the known false-success capture path before relying on negative collection scenarios. Then integrate validated product handoff into the already proven stock-file plumbing and define verified receipt/retention.

The seven-mode flight design, real payload driver, radio/EPS, iOBC, time/resource measurements and flight requirement closure remain later gates. Questions remain in [the intent document](planning/DEVELOPMENT_INTENT.md#open-decisions-and-questions). No code fixes were made by this review.

## Original Claude advisory report

The report below is preserved for audit. Its recommendations are advisory; the dispositions and corrections above take precedence. An unrelated connector-authorization footer was omitted.

# Independent review: N2 local F′–Yamcs setup and planning (base `33aef0a`, branch `neutron2-develop`)

**Model:** the caller asked for Claude Opus 5.5 at high effort. This session reports model ID `claude-opus-5-5`. I can't see the effort setting from inside the session.

**Method:** read-only. I ran no commands, edited no files and delegated nothing. Plan mode asked for a plan file, but you prohibited edits and no Write tool was available, so this review is the only output. I did not recompute the SHA-256 values; I compared them against the manifests only. I did not open the run copies of `yamcs.yaml` (they hold the signing key) or anything in the `.venv` trees.

---

## A. Defects in the authorized local setup (highest priority first)

None of these breaks the recorded pass. Items 1–4 should still be fixed before the next slice depends on this setup.

### 1. [Medium] The launcher runs whatever build is installed, and both build modes share one build cache
- **Evidence:**
  - `tools/yamcs/local_stack.py:23-30` checks only that `missionApp.PING` exists in the dictionary.
  - `tools/yamcs/build_native.sh:33-34` runs `fprime-util generate -f -DNEUTRON2_LOCAL_YAMCS=ON` in the default cache (`build-fprime-automatic-native`), which installs to the same `build-artifacts/Darwin/…` path as the normal AGENTS.md flow.
  - Yamcs is hard-wired to `frameLength: 1024` (`yamcs/config/etc/yamcs.fprime-project.yaml:68`).
- **Consequence:**
  - If someone runs the normal `fprime-util generate -f && fprime-util build` after `build_native.sh`, the installed binary becomes the RF MVP build (128-byte telemetry frames, 96-byte buffers, 40-byte command strings). `run.sh` would still start, then telemetry would fail silently or commands would get FORMAT_ERROR.
  - The reverse also happens: running only `fprime-util build` keeps the option ON in the cache.
  - Nothing stops a cross-build with the option ON. A Pi built that way would send 1031-byte UART frames to a Teensy that accepts 220.
- **Fix:**
  - In `local_stack.py`, refuse to start unless the dictionary constants read `ComCfg.TmFrameFixedSize == 1024` and `FW_CMD_STRING_MAX_SIZE == 504`. Both are present in the generated dictionary, around lines 1743 and 1803. Record them in the manifest.
  - In `ArtemisRpiTeensy_N2/CMakeLists.txt`, stop the build with `FATAL_ERROR` if `NEUTRON2_LOCAL_YAMCS` is ON while cross-compiling or targeting ARM.
  - Optionally give local mode its own build and install directory.

### 2. [Medium] The Yamcs API is open to any web page, with no login
- **Evidence:**
  - `yamcs/config/etc/yamcs.yaml:6-8` sets `cors: allowOrigin: "*"`.
  - The evidence shows every command running as `"username": "guest"` (for example `ping-10071601.json:12`).
  - Command history is recorded (`yamcs.fprime-project.yaml:16`).
- **Consequence:** any page open in a local browser can read the archive and command history, and can probably issue commands. That contradicts the SDD's "only one command authority" rule (SDD §6.5, `.md:892-893`). Once Slice 1 sends literal opcode strings, it also exposes them.
  - **Uncertainty:** I did not check at runtime how Yamcs answers the browser's CORS preflight request.
- **Fix:** delete the `cors` block (the Yamcs web UI is served from the same origin) or restrict it to `http://127.0.0.1:8090`. Decide on Yamcs authentication before any non-synthetic string or hardware is attached.

### 3. [Medium] The evidence record leaves out failed attempts, and runs aren't fully traceable
- **Evidence:** the runbook (`N2_YAMCS_LOCAL_TESTING_2026-10-07.md:79-83`) mentions only run `091554` and the passing run `100058`. The ignored run directories also contain:
  - **`093330`:** FAIL, "No fresh acquired …CollectionCount".
  - **`094001`:** FAIL, "No Yamcs event matching 'CaptureDurationConfigured' within 30s". This one is unexplained.
  - **`094530`:** manifest only, no evidence files.
  - **`095557`:** same binary hash (`f887…`) and dictionary hash (`afd8…`) as the final pass, with two FAIL probes:
    - `fa3ec936b332`: CollectionCount freshness.
    - `b92686118789`: "Capture did not reach SCIENCE_READY". The current `demo.py` no longer contains this message, so the probe script was changed after this run.
  - The manifest (`local_stack.py:62-69`) records no git SHA, dirty-state flag, probe-script hash, tool versions or config hash. The plan's own evidence rule requires these (`N2_SDD_GAP…:90`).
  - `readonly-rest-verification.json` was produced by a validator that isn't committed, so it can't be regenerated.
- **Consequence:** the final PASS is one sample, taken after probe revisions on the same binary. The PASS itself is valid; its repeatability is not shown.
- **Fix:**
  - Add a ledger of every attempt with its disposition (probe bug or system fault) to the runbook.
  - Rerun the final probe on three or more fresh stacks.
  - Add the git SHA, dirty flag, script hashes and `pip freeze` hash to the manifest.
  - Commit the read-only validator or drop that claim.

### 4. [Medium-Low] The file path sent in the test command was read from the local disk, not from Yamcs
- **Evidence:**
  - `demo.py:97-113` resolves `/tmp/neutron_payload_captures/latest_payload.bin` on the host filesystem and sends the resolved `/private/tmp/…csv` path as the `SendFile` argument.
  - No event or telemetry exposes the product path. It exists only in the internal port type (`Components/Types/Types.fpp:46-51`) and in `StorageManager` member state.
- **Consequence:** the command did travel through Yamcs, but an operator using only Yamcs could not have built that argument. The "86-byte path" is a side effect of macOS resolving `/tmp` to `/private/tmp`.
- **Fix:** command the documented stable symlink path (50 bytes, which still exceeds 40), or expose a product reference through Yamcs. Read the source file only after receipt, and only for comparison.

### 5. [Low-Medium] Freshness checks compare two different clocks, and the timestamps run backwards
- **Evidence:**
  - Pong `generationTime` is 20:01:16.831, but `receptionTime` is 20:01:16.196 (`ping-10071601.json:76-77`). An event can't be generated after it was received.
  - The same pattern appears at `collection-…json:95-96` and `:215-216`.
  - F′ timestamps consistently read about 1.00 s after the Yamcs command's `generationTime`.
  - `demo.py:43-46` compares the F′ generation time against the Yamcs command time.
- **Consequence:** today the offset makes the freshness gate more permissive than the runbook (`:73`) says. On a Pi without clock sync it could fail or pass incorrectly. The token and value checks still protect the current verdicts.
  - **Uncertainty:** I don't know the root cause. It could be how the converter decodes F′ time.
- **Fix:** gate freshness on Yamcs `receptionTime`/`acquisitionTime` plus value or token correlation. Investigate the time decoding before running on the Pi.

### 6. [Low] Shutdown and lifecycle gaps
- **Shutdown is too abrupt for a database that persists across runs.** The Yamcs process group gets 3 s after SIGTERM, then SIGKILL (`ArtemisRpiTeensy_N2/tools/local_emulation_loop.py:635-642`). The Yamcs data directory (`yamcs/data`) is shared by every run (`local_stack.py:77`).
- **`stop.py` doesn't confirm shutdown.** It sends SIGINT and returns immediately, without waiting for the process to exit or for ports to free (`stop.py:17`).
- **A stale state file is left behind.** `yamcs/run/current.json` is never cleared (`local_stack.py:71`), so later smoke runs could write evidence into a dead run's directory.
- **`shutdown()` runs twice.** Once from `loop.run`'s `finally` and again from `local_stack.py:82-85`, which closes the PTY file descriptors twice.
- **PTYs aren't set to raw mode.** The slave PTYs are never set raw (`local_emulation_loop.py:452-458`), so bytes written before a child opens its end go through echo/cooked mode.
- **`stop.py` breaks on symlinked checkout paths.** Its path match (`stop.py:15`) compares a resolved path with `run.sh`'s unresolved `pwd`.
- **Fix:**
  - Give Yamcs a longer grace period (about 20 s).
  - Make `shutdown()` safe to call twice.
  - Have `stop.sh` wait for the process to exit and the ports to free.
  - Mark or remove `current.json` on exit.
  - Call `tty.setraw` on both PTY slaves.

### 7. [Low] The Python UART parser is less strict than the C++ one
- **Evidence:** `tools/yamcs/local_link.py:46-65` doesn't reject bad channels or zero length the way `UartChannelMux.cpp:126-151` does, and it has no timeout.
- **Consequence:** a false magic-byte match with a large length field stalls downlink until up to 64 KiB arrives. The risk is low on a lossless PTY.
- **Fix:** mirror the C++ checks and resync one byte at a time on a bad header.

### 8. [Low] Signing-key file is briefly readable by others
- **Evidence:** `local_stack.py:45-47` writes the key and only then changes it to mode 0600. `:50-55` copies the plaintext key into each retained run's `config/etc/yamcs.yaml` with default permissions.
- **Fix:** create the file with `os.open(..., 0o600)` and tighten permissions on the run copy.

### 9. [Low] Reproducibility and platform documentation
- **Lock file:** `requirements.lock` has no hashes and was resolved only on macOS arm64 (`:1`).
- **Windows/WSL:** the WSL developer path required by the intent (`N2_DEVELOPMENT_INTENT…:72`) and the AGENTS.md platform policy is not documented.
- **Stale runbook wording:** "currently local and uncommitted" (runbook `:29`) will be wrong once this is committed.
- **Unchecked submodule:** `build_native.sh` checks the F′ SHA but not `external/artemis-pdu`.

### 10. [Low] Wording and citation accuracy
- **Runbook `:43` is misleading.** "Individual FPP command declarations also have their own string storage sizes" suggests those sizes apply on board. In fact, the generated handlers read every string argument into `Fw::CmdStringArg` (`FileDownlinkComponentAc.cpp:2671`). The on-board limit is therefore the smaller of the declared size and `FW_CMD_STRING_MAX_SIZE`. This is also why the 48-byte path got FORMAT_ERROR under the 40-byte setting; the runbook's claim at `:81` is correct.
- **Gap-plan citations are slightly off:**
  - `topology.fpp` "171–192" should be 171–183.
  - "114–122" should be 114–116.
  - SDD requirement FSW-015 also covers raw command forwarding for EPS, ADCS, OBC and COMMS (SDD `.md:1663-1669`). The plan's trace maps it to the payload only.

### What I checked and found consistent
- **Command buffer sizes:** the communication buffer is 512 bytes. The command-argument buffer is 512 − 4 (opcode) − 2 (packet descriptor) = 506. The command-string limit is 506 − 2 (length prefix) = 504. This satisfies the framework's compile-time checks at `FPrimeBasicTypes.hpp:39,50`.
  - `FW_FIXED_LENGTH_STRING_SIZE = 504` is *required* by the `:39` check. Saying so in the runbook would explain why it was changed.
- **Dictionary values:** the dictionary confirms 504, 504 and 1024.
- **Local framing settings match Yamcs:**
  - The local config inherits the framework defaults: 1024-byte telemetry frames, spacecraft ID 0x44 (68), virtual channel 1, CRC16. These match the Yamcs telemetry link settings.
  - The largest possible command frame is 6 + 512 + 5 + 2 = 525 bytes, under Yamcs's command `maxFrameLength` of 1024.
- **Buffers fit:** the ComCcsds buffer pools are 2048 bytes, enough for 1024-byte telemetry frames and 525-byte command frames.
- **UART mux sizing:**
  - With the option ON, the mux holds 65535 + 7 bytes, which covers a 1031-byte frame.
  - With it OFF, the sizes are identical to the previous 220/227.
  - The option is passed into F′'s internal sub-build (`cmake/sub-build/sub-build.cmake:96-114`).
  - No framework submodule files were changed.
- **Wire bytes decode correctly:**
  - The PING record decodes to opcode `0x10006001` and token `0x0099AE31`.
  - The SendFile record decodes to string lengths `0x0056` (86) and `0x0019` (25).
  - The recorded `binary` field has a zero packet-length field, so it shows the bytes *before* Yamcs post-processing. Don't cite it as on-wire proof.

---

## B. Future mission-feature gaps that are already documented (not new defects)

I confirmed these against the source; the plan's citations are accurate:
- On failure, the simulated driver sends a zero-byte UNKNOWN product (`PayloadDriver_NeutronSim.cpp:82-85`). ScienceApp still increments the collection count and announces SCIENCE_READY (`ScienceApp.cpp:102-110`).
- StorageManager announces "stored" unconditionally (`StorageManager.cpp:74-89`).
- The custom downlink app marks DONE once the end packet is sent, with no receipt check (`PayloadDownlinkApp.cpp:174-186`).
- The downlink command sends the product without any mode-admission check (`CommsApp.cpp:134-163`).
- Still planned:
  - the channel-1 science route
  - the opaque command facade
  - negative and recovery cases
  - the receipt and retention policy
  - return to standby
  - hardware verification

These are acknowledged as planned work in the gap plan and the runbook (`:95`).

---

## C. Are the acceptance claims supported?

| Claim | Verdict |
| --- | --- |
| Ping PASS (run `100058`) | **Supported.** Yamcs command record plus a Pong event matched on token and type. |
| Nominal collection + stock FileDownlink receipt PASS | **Supported for one run.** The Yamcs GET bytes match the source SHA-256 `210b3f4e…` and CRC 45394, and the source was not copied into the bucket. Repeatability is not shown (A3). The command argument came from the local disk (A4). |
| Read-only recheck | The JSON supports it, but the tool that produced it isn't committed. |
| "OFF preserves RF MVP" | **Supported by code inspection only.** No post-change OFF build or transport-constants check is recorded. |
| 504-byte command-string capacity | **Supported by the dictionary, not by any test.** Nothing exercised a string longer than 86 bytes or at the 504 limit. |
| Binary/dictionary hashes | They match the manifest. I did not recompute them. |

---

## D. Is the plan a good path forward?

**Yes.** The plan reuses `MissionApp → ScienceApp → PayloadManager → driver` and puts the opaque facade below the manager contract. It ranks failure truthfulness as the top correctness gap. It keeps local, real-payload, radio and flight evidence separate. Its traceability to the SDD is honest: conceptual traces only, not requirement closure.

**Change first:**
1. Fix A1–A4 now. These fall within the authorized local tooling and configuration work.
2. Before Slice 1, add these to the plan:
   - **F′ strings can't carry arbitrary bytes.** A `string` argument is NUL-terminated text, and Yamcs encodes it as UTF-8. Opcodes containing `0x00` or non-text bytes can't pass through "unchanged". Decide between `string size N` and a byte array.
   - **Size budget:** a 504-byte string uses 504 + 2 bytes, the entire 506-byte argument buffer. The facade command then has no room for other arguments at maximum length.
   - **Plaintext persistence:** Yamcs command history (`yamcs.fprime-project.yaml:16`) and the evidence writers (`smoke.py:76`, `demo.py:71,82,112`) store full arguments in plaintext. Require synthetic strings only, plus redaction in the tools.

**Next bounded slice** (needs your authorization; only planning is approved for mission/payload features):
- Slice 1: a single-argument opaque-string command reaches a labelled simulator unchanged, with a correlated result returned through Yamcs, and the "driver unavailable" case is rejected without executing.
- Bundle in the small fix that stops counting failed captures as products (`ScienceApp.cpp:102`), so the negative Yamcs scenarios mean something.

---

## E. Decisions still open (owner: you, or the named subsystem lead)
1. Is the SDD v4.0 PDF and its extracted markdown (a CDR deliverable) approved for committing to the `hsfl` GitHub repo?
2. Opcode string: maximum length, encoding, NUL/binary policy, and argument type. (Aris/you)
3. Whether literal strings may be logged, archived in Yamcs and written to evidence files.
4. A separate build and install directory for local mode, or keep the shared cache and add the guard only.
5. Whether to enable local Yamcs authentication, and when.
6. How a Yamcs-only operator learns which product to request (path, catalog ID, or a fixed symlink).
7. Return to standby after capture, or stay in SCIENCE_READY until downlink.
