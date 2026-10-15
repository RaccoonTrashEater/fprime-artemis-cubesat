# N2 hardware integration

**Status:** local software acceptance is complete for the recorded synthetic scenarios. Real PLD acquisition, Pi runtime for the new baseline, SatNOGS host/SPI, SDR handoff and full RF acceptance remain open. These pages record integration inputs, not operating authorization or a hardware runbook.

- [Payload contract needed](PAYLOAD.md): commands, response/lifecycle and raw-file boundary.
- [SatNOGS and SDR contract needed](SATNOGS.md): host packet transport and ground handoff.
- [Dedicated ground-host plan](GROUND_HOST.md): planned Ubuntu Pi 5 and LAN browser operators; not yet deployed.
- Pi Zero W reference procedures: [setup](pi-zero-w/SETUP.md), [native build](pi-zero-w/NATIVE_BUILD.md), [cross-compile](pi-zero-w/CROSS_COMPILE.md), [cross-build handoff](pi-zero-w/CROSS_COMPILE_HANDOFF.md). These describe the Artemis proxy and older target evidence; they do not deploy or validate the new Yamcs baseline.
- [Shared Artemis board/power references](../reference/artemis/README.md).

Keep simulator software acceptance, target build/runtime, wired interface tests, RF/FlatSat acceptance, and flight qualification separate. Each hardware action requires its applicable runbook and task-specific authorization.
