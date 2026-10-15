# N2 local Yamcs setup

One-time setup for the local synthetic demo. The accepted `neutron2-develop` software baseline is currently local and unpublished; these clone commands will work for teammates after that branch is pushed. Until then, use a checkout provided by the maintainer.

## Requirements and platform status

- Git access to the Artemis CubeSat Kit repository and its submodules.
- Python 3.11.
- A native C++ compiler/build toolchain supported by F′.
- macOS Apple Silicon is the validated host. Windows F′ development uses WSL, but this local Yamcs stack has not been validated under WSL. Native PowerShell/CMD builds are not the documented path; see [Windows/WSL status](../development/WINDOWS_WSL.md).

The Yamcs web UI and science viewer bind to loopback (`127.0.0.1`). This setup is for a browser on the same computer as the emulation. A Windows browser on another machine cannot connect to it as configured; network access needs a separately configured shared host.

## Clone and prepare

After `neutron2-develop` is published, clone it and initialize the two required submodules:

```sh
git clone --branch neutron2-develop \
  https://github.com/hsfl/fprime-artemis-cubesat.git neutron_2
cd neutron_2
git submodule update --init --recursive \
  ArtemisRpiTeensy_N2/lib/fprime external/artemis-pdu
```

From the repository root, create the isolated Yamcs and F′ Python environments, install pinned Yamcs dependencies, and build the local F′ configuration:

```sh
./tools/yamcs/bootstrap.sh
./tools/yamcs/build_native.sh
```

Build once after setup; rebuild only after changing software or configuration. For detailed build behavior and developer probes, see [Yamcs local testing](../development/YAMCS_LOCAL_TESTING.md).

## Start the demo

```sh
./tools/yamcs/run_pulses.sh
```

Leave the terminal open. Open [Yamcs](http://127.0.0.1:8090) and select `fprime-project` / `realtime`. The ground science viewer is at [http://127.0.0.1:8063](http://127.0.0.1:8063). For the operator steps, see [Quickstart](QUICKSTART.md).

The launcher runs Yamcs, the native F′ application, software-only communication links, and a simulated payload on the same computer. It is not a hardware or RF test.
