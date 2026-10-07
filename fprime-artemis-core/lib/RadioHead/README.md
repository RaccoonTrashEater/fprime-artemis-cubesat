# RadioHead 1.112 subset
Copied from the Teensy Arduino core 1.62.0 RadioHead distribution. Original
copyright notices and GPLv3/commercial licence are retained in LICENSE and
source headers. Only the RF22 driver and its base classes are compiled.
Project changes: platform 22 includes RhZephyr.hpp; merged preamble/packet-end
interrupts do not erase a completed RX buffer; CRC interrupt counts are retained
in a protected 32-bit counter. RHSPIDriver.h includes RHGenericSPI instead of
the Arduino hardware SPI header. RHHardwareSPI1 is replaced by
RhZephyrSPI on lpspi3. No Arduino runtime is linked.
