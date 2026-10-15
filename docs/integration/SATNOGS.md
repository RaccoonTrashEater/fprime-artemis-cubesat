# N2 SatNOGS and SDR integration contract

**Open interface:** Dennis owns the F′ SatNOGS driver; Sam and Tierra own SatNOGS firmware/SPI integration. See [current intent](../planning/DEVELOPMENT_INTENT.md). The umbrella workspace contains additional SatNOGS design references; this checkout does not depend on their presence to run the local demo.

Agree and identify:

- Exact populated board revision, firmware build and MCU endpoint reached by host SPI.
- SPI mode/clock, chip-select, reset/boot and ready/IRQ signals.
- Controller ownership/arbitration; no shared Pi/Teensy control is assumed.
- TX/RX packet operations, packet boundaries and size limits, queues/backpressure, status/error responses and restart recovery.
- SDR-side handoff to Yamcs: transfer frames versus packets, framing/IDs, and routing for telemetry and raw science.

The host-only UART/frame capacities in `NEUTRON2_LOCAL_YAMCS=ON` are test settings, not an agreed radio contract. Queue/sender completion is not ground receipt. [Independent receipt verification](../verification/COMPLETION_STORAGE.md) remains the acceptance boundary after the physical adapter is added.

Proposed sequence: agree the contract → exercise fake transport cases → authorized wired MCU/SPI tests → integrate the driver and ground handoff → authorized conducted-RF end-to-end tests. Board bring-up and RF operation require separate runbooks and authorization. The [older RFM23BP workflow](../archive/legacy-gds-rfm23bp/README.md) remains comparison evidence only.
