#pragma once
#include "FprimeArtemisCore/Components/UHFRadioDriver_RFM23BP/UHFRadioDriver_RFM23BPComponentAc.hpp"

// Keep the Zephyr shim after F Prime to avoid Zephyr EMPTY macro collisions.
#include "BoundedRf22.hpp"
namespace Components {
class UHFRadioDriver_RFM23BP : public UHFRadioDriver_RFM23BPComponentBase {
   public:
    explicit UHFRadioDriver_RFM23BP(const char* name);
    void configure();

   private:
    bool power_handler(FwIndexType, bool enabled) override;
    bool send_handler(FwIndexType, const RadioPacket& packet) override;
    bool receive_handler(FwIndexType, RadioPacket& packet) override;
    RadioStatus status_handler(FwIndexType) override;
    void service();
    void off();
    void rx();
    BoundedRf22 radio;
    RadioState state;
};
}  // namespace Components
