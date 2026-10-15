# N2 baseline packaging validation — October 14, 2026

These checks exercise the packaged sender-sequence correction after the October 9 acceptance checkpoint. [Source hashes](source-sha256.json) identify the 72 changed/new implementation, test, tool and configuration files included in this snapshot. Historical acceptance is preserved separately in [the October 9 snapshot](../n2-software-2026-10-09/README.md).

- Native default OFF profile built successfully; this is compile evidence only.
- `fprime-util generate --ut -f`, `fprime-util build --ut`, and `fprime-util check --all`: six suites / 34 GTest cases passed. [Suite summary](fprime-ut-check.log), [case details](component-ut-details.log).
- Yamcs Python tests, including the localhost viewer: 21 passed and five subtests passed. [Result](yamcs-python-tests.log).
- Python compile and shell syntax checks passed.
- `tools/yamcs/build_native.sh`: final local-Yamcs ON / arm64 build passed after the UT run. [Build log](yamcs-native-build.log), [artifact hashes](native-artifact-sha256.txt). The final dictionary matches the October 9 dictionary; the binary differs following the sender correction.

The original run directory is `yamcs/run/packaging-checks-20261014-DRiAl2/`. Only selected results are copied here; complete stack logs and runtime state remain local and ignored. Runtime probes use Yamcs commands and returned events/objects against synthetic data and fresh isolated storage. The component/Python tests are separate setup/regression evidence, not hardware acceptance.

Fresh Yamcs runtime results:

| Probe | Result |
| --- | --- |
| [Pass-through](passthrough-acceptance.json) | PASS |
| [Lifecycle](lifecycle-acceptance.json) | PASS, all 31 checks |
| [Pulse/raw-science delivery](pulse-cycle-acceptance.json) | PASS, including independent raw readback |
| [Completion/storage before restart](completion-storage-before-restart.json) | PASS |
| [Completion/storage after restart](completion-storage-after-restart.json) | PASS |

The [final product manifest](completion-storage-final-manifest.json) records restart/product/receipt identity. The other four original October 9 isolated fault scenarios were not replayed during packaging. Runtime JSON retains the original local run paths; its copies above are the portable evidence entry points.

[Validation summary](validation-summary.json) records final results and shutdown observations. The pulse stop command returned 1 because its runner PID was already absent; subsequent process/port checks found the stack stopped. Other runtime diagnostics remain in the local run directory.
