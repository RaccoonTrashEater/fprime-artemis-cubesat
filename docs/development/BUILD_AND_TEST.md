# Build and test N2 software

For a developer running the current local Yamcs stack, follow [the detailed runbook](YAMCS_LOCAL_TESTING.md). For mission ops, use [local setup](../operations/LOCAL_SETUP.md) once and [the daily quickstart](../operations/QUICKSTART.md) thereafter.

## Local Yamcs profile

From the repository root after the runbook prerequisites and submodules are installed:

```sh
./tools/yamcs/bootstrap.sh
./tools/yamcs/build_native.sh
./tools/yamcs/run_pulses.sh
```

The build script explicitly selects `NEUTRON2_LOCAL_YAMCS=ON`. A plain native generate can select the default OFF/RF sizing. The host artifact must not be deployed as a hardware binary. Stop with `./tools/yamcs/stop.sh` or Ctrl+C in the foreground launcher.

## Regression checks

From `ArtemisRpiTeensy_N2`, with `fprime-venv` activated:

```sh
fprime-util generate --ut -f
fprime-util build --ut
fprime-util check --all
```

Re-run `./tools/yamcs/build_native.sh` from the repository root after UTs before a Yamcs replay: UT and native installs share an ignored artifact directory. Use [the detailed runbook](YAMCS_LOCAL_TESTING.md) for the serialized Yamcs probes and [completion/storage acceptance](../verification/COMPLETION_STORAGE.md) for isolated restart/fault scenarios. No concurrent operator commands during a probe.

`tools/validate_local.sh` and the [older local emulation runbook](../archive/legacy-gds-rfm23bp/NEUTRON2_LOCAL_EMULATION_RUNBOOK.md) cover the historical GDS comparison workflow, not acceptance of the current SatNOGS/SDR hardware path.

[Windows/WSL notes](WINDOWS_WSL.md) · [Component starters](COMPONENT_STARTERS.md) · [Timing and scheduling](TIME_AND_SCHEDULING.md) · [Developer troubleshooting](TROUBLESHOOTING.md)
