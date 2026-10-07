#include "RhZephyr.hpp"

#include <RHGenericSPI.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/init.h>
namespace {
const gpio_dt_spec selectPin = GPIO_DT_SPEC_GET(DT_NODELABEL(rfm23), select_gpios);
const gpio_dt_spec irqPin = GPIO_DT_SPEC_GET(DT_NODELABEL(rfm23), irq_gpios);
const gpio_dt_spec rxPin = GPIO_DT_SPEC_GET(DT_NODELABEL(rfm23), rx_on_gpios);
const gpio_dt_spec txPin = GPIO_DT_SPEC_GET(DT_NODELABEL(rfm23), tx_on_gpios);
const gpio_dt_spec sdnPin = GPIO_DT_SPEC_GET(DT_NODELABEL(rfm23), sdn_gpios);
const gpio_dt_spec* pin(uint8_t p) {
    switch (p) {
        case 38:
            return &selectPin;
        case 40:
            return &irqPin;
        case 30:
            return &rxPin;
        case 31:
            return &txPin;
        case 37:
            return &sdnPin;
        default:
            return nullptr;
    }
}
// Assert shutdown before main's USB startup delay and before any F Prime task.
int safeOffAtBoot() {
    if (gpio_is_ready_dt(&sdnPin))
        (void)gpio_pin_configure_dt(&sdnPin, GPIO_OUTPUT_ACTIVE);
    if (gpio_is_ready_dt(&selectPin))
        (void)gpio_pin_configure_dt(&selectPin, GPIO_OUTPUT_INACTIVE);
    if (gpio_is_ready_dt(&rxPin))
        (void)gpio_pin_configure_dt(&rxPin, GPIO_OUTPUT_INACTIVE);
    if (gpio_is_ready_dt(&txPin))
        (void)gpio_pin_configure_dt(&txPin, GPIO_OUTPUT_INACTIVE);
    return 0;
}
SYS_INIT(safeOffAtBoot, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);
class RhZephyrSPI : public RHGenericSPI {
   public:
    bool failed = false;
    void begin() override {}
    void end() override {}
    uint8_t transfer(uint8_t value) override {
        static const spi_dt_spec bus = SPI_DT_SPEC_GET(DT_NODELABEL(rfm23), SPI_WORD_SET(8) | SPI_TRANSFER_MSB, 0);
        uint8_t result = 0;
        spi_buf tx = {&value, 1}, rx = {&result, 1};
        spi_buf_set txs = {&tx, 1}, rxs = {&rx, 1};
        if (spi_transceive_dt(&bus, &txs, &rxs) != 0)
            failed = true;
        return result;
    }
} spi;
}  // namespace
RHGenericSPI& hardware_spi = spi;
bool rhBusReady() {
    spi.failed = false;
    return device_is_ready(DEVICE_DT_GET(DT_BUS(DT_NODELABEL(rfm23)))) && gpio_is_ready_dt(&selectPin) &&
           gpio_is_ready_dt(&irqPin) && gpio_is_ready_dt(&rxPin) && gpio_is_ready_dt(&txPin) &&
           gpio_is_ready_dt(&sdnPin);
}
bool rhBusFailed() {
    return spi.failed;
}
void pinMode(uint8_t p, uint8_t mode) {
    const auto* spec = pin(p);
    if (spec && gpio_pin_configure_dt(spec, mode == INPUT ? GPIO_INPUT : GPIO_OUTPUT) != 0)
        spi.failed = true;
}
void digitalWrite(uint8_t p, uint8_t value) {
    const auto* spec = pin(p);
    // RadioHead uses electrical HIGH/LOW, not DT logical active/inactive.
    if (spec && gpio_pin_set_raw(spec->port, spec->pin, value) != 0)
        spi.failed = true;
}
int digitalRead(uint8_t p) {
    const auto* spec = pin(p);
    return spec ? gpio_pin_get_raw(spec->port, spec->pin) : -1;
}

namespace {
K_SEM_DEFINE(radioEvent, 0, 1);
gpio_callback radioCallback;
bool callbackInstalled = false;
void radioIrq(const device*, gpio_callback*, uint32_t) {
    k_sem_give(&radioEvent);
}
}  // namespace
void rhWake() {
    k_sem_give(&radioEvent);
}
void rhWait() {
    k_sem_take(&radioEvent, K_MSEC(10));
}
bool rhInstallIrq() {
    if (!callbackInstalled) {
        if (gpio_pin_configure_dt(&irqPin, GPIO_INPUT) != 0)
            return false;
        gpio_init_callback(&radioCallback, radioIrq, BIT(irqPin.pin));
        if (gpio_add_callback(irqPin.port, &radioCallback) != 0)
            return false;
        callbackInstalled = true;
    }
    return gpio_pin_interrupt_configure_dt(&irqPin, GPIO_INT_EDGE_TO_ACTIVE) == 0;
}
