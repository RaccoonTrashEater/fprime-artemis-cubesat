# RadioComms

`FlightControllerDeployment` owns the radio on the Teensy. `RadioComms`
contains `UHFRadioManager` and `UHFRadioDriver_RFM23BP`. Stock
`ComCcsds.FramingSubtopology` supplies CCSDS framing and deframing upstream.
The manager's `Svc.Com` boundary can be reused with another radio driver
implementing the shared ports in `Types/Radio.fpp`.

## Build and select the ground link

macOS, from the repository root:

```sh
. fprime-artemis-core/fprime-venv/bin/activate
cd fprime-artemis-core
fprime-util generate -f -DARTEMIS_GROUND_LINK=RFM23
fprime-util build
```

Use `-DARTEMIS_GROUND_LINK=USB` for the default USB bench path. Windows
F Prime development uses the same commands in WSL2, with its own installed
Zephyr SDK and virtual environment. Do not reuse a macOS build cache in WSL.

USB builds include the radio components for command/telemetry bring-up but
leave the radio in shutdown at boot. Radio uplinks received in USB mode are
counted as drops; they cannot command the spacecraft through this transport.
RFM23 builds enable the radio at boot and use it for ground commanding,
events, and telemetry. USB CDC remains the console; do not mix console output
with the ground RF bytestream. The existing ground Teensy firmware and GDS
`space-packet-space-data-link` framing remain the ground-side interface.

## Operation

- `RadioComms.manager.RADIO_SET_ENABLED(enabled)` queues a request. Command
  `OK` means acceptance; `RadioState` and `RadioPowerChanged` report the
  hardware outcome. Failed enable is retried every five seconds while
  enable remains requested.
- `RADIO_RESET_COUNTERS` resets software link counters. The driver's CRC
  interrupt counter is cumulative for the lifetime of the deployment.
- A missing radio produces `FAULT` without blocking flight-controller boot.
- The manager's power request port is exported for future mission-mode wiring.
  This change does not invent MissionApp's radio policy.
- Powering off the sole RF ground link also removes RF commanding. Restore it
  through an onboard command sequence or use USB for power-cycle testing.

All SPI and RadioHead state access runs on one priority-0, 8 KiB Zephyr worker.
Its GPIO interrupt callback only gives a semaphore. A 10 ms backstop also
services a held-low IRQ. The worker acknowledges health pings, so health
checks measure its progress rather than just the caller's progress. Its
static thread stack is separate from F Prime's dynamic thread pool.

The driver asserts datasheet shutdown before main's USB startup delay,
probes the chip, bounds CHIPRDY
initialization, and applies the legacy 424 MHz / GFSK 125 kbps profile and
external amplifier polarity. It follows RX -> TX -> IDLE -> RX for each send,
with bounded TX completion and RX restoration. The deferred interrupt handler
handles merged preamble/packet-end flags without erasing the received packet.
Manual CS spans register/FIFO transactions; Zephyr does not drive native PCS.

The channel-0 link format remains `A5, message, segment, count, length, data`,
with 44-byte chunks and five-byte ACKs. Network/address/version and asymmetric
ACK policies come from `config/transport_constants.json` and
`config/rf_networks.json`; regenerate with `tools/generate_transport_constants.py`
and check with `tools/check_transport_constants.py`. FC TM frames are 128 B
and link messages are bounded to 220 B. Payload sidecar channel 1 and the old
Pi-local channel 2 RPC are outside this subtopology.

## Host tests

macOS (repository root, with the project virtual environment active):

```sh
. fprime-artemis-core/fprime-venv/bin/activate
cmake -S fprime-artemis-core/FprimeArtemisCore/Components/UHFRadioManager/test -B /tmp/artemis-radio-tests
cmake --build /tmp/artemis-radio-tests
ctest --test-dir /tmp/artemis-radio-tests --output-on-failure
```

Windows developers can use the same commands in WSL2. These tests need only
CMake and a C++14 compiler. They cover segment bytes, 128-byte round trips,
ACK success and exhaustion, duplicate suppression, header rejection,
reassembly timeout, timer wraparound, and bounds. They do not prove RF or SPI
behavior on hardware.

## Bench acceptance still required

1. Boot a USB build with the radio absent; verify sensor/link operation and
   radio OFF/FAULT reporting without an initialization assertion.
2. Compare radio configuration registers with the existing baremetal build
   (status/IRQ registers are destructive reads; exclude them from live dumps).
3. Boot an RFM23 build and use unchanged `GDS_Teensy` to check continuous SoH,
   events, and command responses. Stress uplink while downlink is busy.
4. Use a USB build or onboard sequence for disable/re-enable and unplugged
   radio recovery. Verify buffer usage returns to baseline.

RadioHead 1.112 sources and licence are retained under `lib/RadioHead`.

## USB-controlled TX bench test

1. Build with `ARTEMIS_GROUND_LINK=USB` and connect GDS to the FC USB port.
2. Send `RadioComms.manager.RADIO_SET_ENABLED(true)` and wait for `RadioState=RX`.
3. Send `RadioComms.manager.RADIO_SEND_TEST_PACKET` (no arguments).
4. The worker sends the 19 bytes `ARTEMIS-RADIO-TEST\n` through the normal
   channel-0 segmentation and configured ACK policy. The trailing byte is LF;
   there is no NUL. The RF application packet is 24 bytes: `A5 <message-id>
   00 01 13` followed by that marker. RadioHead addressing is unchanged.
5. `RadioTestPacketResult` includes the command sequence, success, and requested
   byte count. Command OK is issued after successful local TX completion;
   EXECUTION_ERROR means radio disabled, transmission failed, or another test
   request is outstanding. Rejected busy requests do not send a packet.
6. Confirm the exact marker on the ground Teensy's channel-0 USB serial port
   with a raw serial monitor. This marker is not a CCSDS frame and will not
   appear as a decoded GDS event. Close any GDS connection using that same
   ground port before opening the monitor. FC USB GDS remains connected.

The test does not enable the radio automatically and does not alter the
selected ground transport. Its completion never signals ComQueue readiness.
The configured satellite-to-ground channel-0 ACK policy is currently ACK-free,
so local success does not prove reception: check the ground marker separately.
