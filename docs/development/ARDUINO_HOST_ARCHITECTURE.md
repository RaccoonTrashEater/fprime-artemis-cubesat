# Arduino builds: Mac, Linux and Windows

The host computer can be ARM or x86. The firmware target stays **Teensy 4.1 (ARM)** either way.

## Normal builds

From the repo root:

```sh
./ArtemisTeensy_N2_Baremetal/tools/arduino-cli/build.sh
./GDS_Teensy/tools/arduino-cli/build.sh
```

| Computer | What the scripts use |
| --- | --- |
| Apple Silicon Mac | ARM64 Arduino CLI, preferring `/opt/homebrew/bin/arduino-cli` |
| Intel Mac | Arduino CLI on `PATH` |
| Linux ARM or x86 | Native Linux Arduino CLI on `PATH` |
| Windows | Run inside WSL with Linux Arduino CLI; native PowerShell/CMD is not supported by these scripts |

The scripts set the correct workspace/config and compile with `--clean`. They do not flash a board. A normal build updates/downloads board packages as needed.

## Switching ARM/Intel on a Mac

Default to the matching native CLI. To check a particular installation:

```sh
# Apple Silicon / ARM Homebrew
arch -arm64 /opt/homebrew/bin/arduino-cli version

# Intel Homebrew (also usable on Apple Silicon with Rosetta)
arch -x86_64 /usr/local/bin/arduino-cli version
```

Both examples require that executable to be installed. To intentionally build with Intel tools on Apple Silicon, temporarily change the build script's `ARDUINO_CLI` array to the Intel prefix above, e.g. `ARDUINO_CLI=(/usr/bin/arch -x86_64 /usr/local/bin/arduino-cli)`. Keep personal path changes local. The default scripts deliberately select ARM64 on Apple Silicon.

On Linux/WSL, install the CLI for that Linux host's CPU and put it on `PATH`; the Mac `arch` commands do not apply. Do not copy `.arduino15` or build caches between different hosts.

If you see `bad CPU type in executable` or `Exec format error`, run `file` on the exact failing executable. Arduino CLI, the compiler and cached `ctags` can have different architectures; `--clean` does not fix a mismatched helper.

Windows/WSL full builds are not yet validated. See [Windows setup](WINDOWS_WSL.md). This guide concerns Teensy builds; [F′/Yamcs setup](BUILD_AND_TEST.md) is separate.
