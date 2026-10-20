# N2 SatNOGS and SDR integration contract

**Updated October 19, 2026:** Dennis owns the F′ SatNOGS driver and Yamcs integration; Sam and Zach handle SatNOGS firmware/SPI and SDR. Pi Zero W is the selected SPI controller; a custom SatNOGS-specific F′ radio-driver component will own the host interface. Its implementation and packet/firmware contract remain open. See [current intent](../planning/DEVELOPMENT_INTENT.md). The umbrella workspace contains additional SatNOGS design references; this checkout does not depend on their presence to run the local demo.

**Milestone allocation revised October 18:** SatNOGS/SPI, SDR and end-to-end Yamcs ground delivery are FSR integration work. CDR intentionally demonstrates payload + PDU without the COMMS stack.

## Selected FSR path — Dennis, October 19

Pi Zero W SPI breakout → 6-pin Molex-to-PC104 harness → separately powered SatNOGS-COMMS v0.3.2 PHASMA PC104 → SMA/coax UHF RF → USRP B200 → USB → Pi 5 Ubuntu/Yamcs → LAN operator browser. UHF is the selected band, not UART; S-band is not assumed. This is real conducted RF. Sam/Zach own demodulation and the matching RF arrangement; its detailed setup is outside this document.

Agree and identify:

- Exact populated board revision, firmware build and MCU endpoint reached by host SPI.
- SPI mode/clock, chip-select, reset/boot and ready/IRQ signals.
- Pi Zero W is SPI controller; six-pin harness pinout and reference/power-sequencing details remain TBD. No shared Pi/Teensy radio control is assumed.
- TX/RX packet operations, packet boundaries and size limits, queues/backpressure, status/error responses and restart recovery.
- USRP B200 SDR-side software handoff to Yamcs: transfer frames versus packets, framing/IDs, and routing for telemetry and raw science.

The host-only UART/frame capacities in `NEUTRON2_LOCAL_YAMCS=ON` are test settings, not an agreed radio contract. Queue/sender completion is not ground receipt. [Independent receipt verification](../verification/COMPLETION_STORAGE.md) remains the acceptance boundary after the physical adapter is added.

Proposed sequence: agree the contract → exercise fake transport cases → authorized wired MCU/SPI tests → integrate the driver and ground handoff → authorized conducted-RF end-to-end tests. Board bring-up and RF operation require separate runbooks and authorization. The [older RFM23BP workflow](../archive/legacy-gds-rfm23bp/README.md) remains comparison evidence only.
