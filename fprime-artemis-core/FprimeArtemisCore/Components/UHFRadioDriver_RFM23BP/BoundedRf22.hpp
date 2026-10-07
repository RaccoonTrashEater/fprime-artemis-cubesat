#pragma once
#include <RH_RF22.h>
class BoundedRf22 : public RH_RF22 {
   public:
    using RH_RF22::setThisAddress;
    void serviceInterrupt() {
        handleInterrupt();
    }
    void recoverTransmit() {
        setModeIdle();
        resetFifos();
        clearTxBuf();
        clearRxBuf();
    }
    uint32_t crcErrors() const {
        return _zephyrCrcErrors;
    }
    bool receiveBounded(uint8_t* bytes, uint8_t* len) {
        if (_bufLen > 49) {
            ++_rxBad;
            clearRxBuf();
            return false;
        }
        return recv(bytes, len);
    }
    BoundedRf22(uint8_t slave_select_pin, uint8_t interrupt_pin, RHGenericSPI& spi)
        : RH_RF22(slave_select_pin, interrupt_pin, spi) {}

    // RadioHead uses the same _buf/_bufLen storage for transmit and receive, but
    // setModeRx() leaves the completed TX length behind. If the preamble
    // interrupt is delayed or missed, the next packet is either rejected as
    // shorter than that stale TX length or accepted with stale TX bytes prefixed.
    // Re-arm RX from a known-empty software/FIFO/interrupt state after every TX.
    void restartReceiveClean() {
        setModeIdle();
        resetRxFifo();
        (void)spiRead(RH_RF22_REG_03_INTERRUPT_STATUS1);
        (void)spiRead(RH_RF22_REG_04_INTERRUPT_STATUS2);
        clearRxBuf();
        setModeRx();
    }

    // A maximum 49-byte application packet occupies just under 4 ms at
    // 125 kbps once the RadioHead framing bytes are included. Defer normal
    // queued TX for 6 ms after a detected preamble so setModeTx() cannot clear a
    // command that is still arriving. Immediate ACKs run only after packet-valid.
    bool receiveInProgress(uint32_t now_ms) {
        static constexpr uint32_t RX_PACKET_GUARD_MS = 6U;
        const uint32_t last_preamble_ms = getLastPreambleTime();
        return mode() == RHModeRx && last_preamble_ms != 0U && (now_ms - last_preamble_ms) < RX_PACKET_GUARD_MS;
    }

    bool initBounded(uint16_t chip_ready_timeout_ms) {
        if (chip_ready_timeout_ms == 0 || !RHSPIDriver::init()) {
            return false;
        }

        int interrupt_number = digitalPinToInterrupt(_interruptPin);
        if (interrupt_number == NOT_AN_INTERRUPT) {
            return false;
        }
#ifdef RH_ATTACHINTERRUPT_TAKES_PIN_NUMBER
        interrupt_number = _interruptPin;
#endif
        spiUsingInterrupt(interrupt_number);

        _mode = RHModeInitialising;
        reset();
        _deviceType = spiRead(RH_RF22_REG_00_DEVICE_TYPE);
        if (_deviceType != RH_RF22_DEVICE_TYPE_RX_TRX && _deviceType != RH_RF22_DEVICE_TYPE_TX) {
            return false;
        }

        spiWrite(RH_RF22_REG_07_OPERATING_MODE1, RH_RF22_SWRES);
        const uint32_t chip_ready_start_ms = millis();
        while ((spiRead(RH_RF22_REG_04_INTERRUPT_STATUS2) & RH_RF22_ICHIPRDY) == 0) {
            if ((millis() - chip_ready_start_ms) >= chip_ready_timeout_ms) {
                return false;
            }
            yield();
        }

        pinMode(_interruptPin, INPUT);
        spiWrite(RH_RF22_REG_05_INTERRUPT_ENABLE1, RH_RF22_ENTXFFAEM | RH_RF22_ENRXFFAFULL | RH_RF22_ENPKSENT |
                                                       RH_RF22_ENPKVALID | RH_RF22_ENCRCERROR | RH_RF22_ENFFERR);
        spiWrite(RH_RF22_REG_06_INTERRUPT_ENABLE2, RH_RF22_ENPREAVAL);

        if (_myInterruptIndex == 0xff) {
            if (_interruptCount >= RH_RF22_NUM_INTERRUPTS) {
                return false;
            }
            _myInterruptIndex = _interruptCount++;
        }
        _deviceForInterrupt[_myInterruptIndex] = this;
        if (_myInterruptIndex == 0) {
            attachInterrupt(interrupt_number, isr0, FALLING);
        } else if (_myInterruptIndex == 1) {
            attachInterrupt(interrupt_number, isr1, FALLING);
        } else if (_myInterruptIndex == 2) {
            attachInterrupt(interrupt_number, isr2, FALLING);
        } else {
            return false;
        }

        setModeIdle();
        clearTxBuf();
        clearRxBuf();
        spiWrite(RH_RF22_REG_7D_TX_FIFO_CONTROL2, RH_RF22_TXFFAEM_THRESHOLD);
        spiWrite(RH_RF22_REG_7E_RX_FIFO_CONTROL, RH_RF22_RXFFAFULL_THRESHOLD);
        spiWrite(RH_RF22_REG_30_DATA_ACCESS_CONTROL,
                 RH_RF22_ENPACRX | RH_RF22_ENPACTX | RH_RF22_ENCRC | (_polynomial & RH_RF22_CRC));
        spiWrite(RH_RF22_REG_32_HEADER_CONTROL1, RH_RF22_BCEN_HEADER3 | RH_RF22_HDCH_HEADER3);
        spiWrite(RH_RF22_REG_33_HEADER_CONTROL2, RH_RF22_HDLEN_4 | RH_RF22_SYNCLEN_2);
        setPreambleLength(8);
        uint8_t sync_words[] = {0x2d, 0xd4};
        setSyncWords(sync_words, sizeof(sync_words));
        setPromiscuous(false);
        setFrequency(434.0f, 0.05f);
        setModemConfig(FSK_Rb2_4Fd36);
        setGpioReversed(false);
        setTxPower(RH_RF22_TXPOW_8DBM);
        return true;
    }
};
