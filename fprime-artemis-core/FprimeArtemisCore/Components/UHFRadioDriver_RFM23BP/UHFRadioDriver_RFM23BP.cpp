#include "UHFRadioDriver_RFM23BP.hpp"

#include <zephyr/drivers/gpio.h>

#include "../UHFRadioManager/LinkConstants.hpp"
bool rhBusReady();
bool rhInstallIrq();
bool rhBusFailed();
namespace Components {
UHFRadioDriver_RFM23BP::UHFRadioDriver_RFM23BP(const char* name)
    : UHFRadioDriver_RFM23BPComponentBase(name), radio(38, 40, hardware_spi), state(RadioState::OFF) {}
void UHFRadioDriver_RFM23BP::configure() {
    pinMode(37, OUTPUT);
    digitalWrite(37, HIGH);
    pinMode(38, OUTPUT);
    digitalWrite(38, HIGH);
    pinMode(30, OUTPUT);
    pinMode(31, OUTPUT);
    digitalWrite(30, LOW);
    digitalWrite(31, LOW);
}
void UHFRadioDriver_RFM23BP::off() {
    configure();
    state = RadioState::OFF;
}
void UHFRadioDriver_RFM23BP::service() {
    if (state == RadioState::OFF || state == RadioState::FAULT)
        return;
    // Backstop is bounded even if a disconnected/stuck IRQ reads low forever.
    for (unsigned i = 0; i < 8 && digitalRead(40) == LOW; ++i)
        radio.serviceInterrupt();
}
void UHFRadioDriver_RFM23BP::rx() {
    digitalWrite(30, LOW);
    digitalWrite(31, HIGH);
    k_busy_wait(300);
    radio.restartReceiveClean();
    state = RadioState::RX;
}
bool UHFRadioDriver_RFM23BP::power_handler(FwIndexType, bool enabled) {
    service();
    if (enabled && state == RadioState::RX && !rhBusFailed())
        return true;
    off();
    if (!enabled)
        return true;
    if (!rhBusReady() || !rhInstallIrq()) {
        state = RadioState::FAULT;
        return false;
    }
    k_msleep(50);
    digitalWrite(37, LOW);
    k_msleep(50);
    pinMode(40, INPUT);
    const uint8_t first = radio.spiRead(RH_RF22_REG_00_DEVICE_TYPE);
    k_msleep(1);
    if (first != RH_RF22_DEVICE_TYPE_RX_TRX || first != radio.spiRead(RH_RF22_REG_00_DEVICE_TYPE) ||
        !radio.initBounded(100) || !radio.setFrequency(424.0f)) {
        off();
        state = RadioState::FAULT;
        return false;
    }
    radio.setThisAddress(link_protocol::RF_LOCAL_ADDRESS);
    radio.setModemConfig(RH_RF22::GFSK_Rb125Fd125);
    radio.spiWrite(RH_RF22_REG_58_CHARGE_PUMP_CURRENT_TRIMMING, 0xC0);
    radio.setTxPower(RH_RF22_RF23BP_TXPOW_30DBM);
    rx();
    if (rhBusFailed()) {
        off();
        state = RadioState::FAULT;
        return false;
    }
    return true;
}
bool UHFRadioDriver_RFM23BP::send_handler(FwIndexType, const RadioPacket& packet) {
    service();
    if (state != RadioState::RX || packet.get_length() == 0 || packet.get_length() > 49)
        return false;
    const uint32_t guard = millis();
    while (radio.receiveInProgress(millis()) && millis() - guard < 8) {
        k_msleep(1);
        service();
    }
    // Do not overwrite an unread uplink with the shared RadioHead TX buffer.
    if (radio.available())
        return false;
    radio.setHeaderTo(packet.get_to());
    radio.setHeaderFrom(packet.get_from());
    radio.setHeaderId(packet.get_network());
    radio.setHeaderFlags(packet.get_version(), 0xFF);
    uint8_t bytes[49];
    for (unsigned i = 0; i < packet.get_length(); ++i)
        bytes[i] = packet.get_bytes()[i];
    digitalWrite(30, HIGH);
    digitalWrite(31, LOW);
    k_busy_wait(300);
    state = RadioState::TX;
    bool ok = radio.send(bytes, packet.get_length());
    const uint32_t start = millis();
    while (ok && radio.mode() == RHGenericDriver::RHModeTx && millis() - start < 500) {
        k_msleep(1);
        service();
    }
    ok = ok && radio.mode() != RHGenericDriver::RHModeTx && !rhBusFailed();
    if (!ok)
        radio.recoverTransmit();
    radio.setModeIdle();
    state = RadioState::IDLE;
    rx();
    return ok;
}
bool UHFRadioDriver_RFM23BP::receive_handler(FwIndexType, RadioPacket& packet) {
    service();
    if (state != RadioState::RX || !radio.available())
        return false;
    uint8_t bytes[49], n = sizeof(bytes);
    if (!radio.receiveBounded(bytes, &n))
        return false;
    RadioBytes data;
    for (unsigned i = 0; i < n; ++i)
        data[i] = bytes[i];
    packet = RadioPacket(data, n, radio.headerTo(), radio.headerFrom(), radio.headerId(), radio.headerFlags());
    return true;
}
RadioStatus UHFRadioDriver_RFM23BP::status_handler(FwIndexType) {
    service();
    return RadioStatus(state, radio.lastRssi(), radio.crcErrors());
}
}  // namespace Components
