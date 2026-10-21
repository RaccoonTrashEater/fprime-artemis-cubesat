#include "UartChannelMuxTester.hpp"

namespace Components {

UartChannelMuxTester::UartChannelMuxTester()
    : UartChannelMuxGTestBase("UartChannelMuxTester", MAX_HISTORY_SIZE),
      component("UartChannelMux"),
      m_txFrames(),
      m_ccsdsFrames(),
      m_payloadFrames(),
      m_localFrames() {
    this->initComponents();
    this->connectPorts();
}

UartChannelMuxTester::~UartChannelMuxTester() {
    this->component.deinit();
}

Drv::ByteStreamStatus UartChannelMuxTester::from_drvSendOut_handler(
    FwIndexType portNum,
    Fw::Buffer& fwBuffer
) {
    static_cast<void>(portNum);
    const U8* data = fwBuffer.getData();
    this->m_txFrames.push_back(std::vector<U8>(data, data + fwBuffer.getSize()));
    this->pushFromPortEntry_drvSendOut(fwBuffer);
    return Drv::ByteStreamStatus::OP_OK;
}

void UartChannelMuxTester::from_ccsdsRecvOut_handler(
    FwIndexType portNum,
    Fw::Buffer& fwBuffer,
    const Drv::ByteStreamStatus& status
) {
    static_cast<void>(portNum);
    const U8* data = fwBuffer.getData();
    this->m_ccsdsFrames.push_back(std::vector<U8>(data, data + fwBuffer.getSize()));
    this->pushFromPortEntry_ccsdsRecvOut(fwBuffer, status);
}

void UartChannelMuxTester::from_payloadRecvOut_handler(FwIndexType portNum, Fw::Buffer& fwBuffer) {
    static_cast<void>(portNum);
    const U8* data = fwBuffer.getData();
    this->m_payloadFrames.push_back(std::vector<U8>(data, data + fwBuffer.getSize()));
    this->pushFromPortEntry_payloadRecvOut(fwBuffer);
}

void UartChannelMuxTester::from_localRecvOut_handler(FwIndexType portNum, Fw::Buffer& fwBuffer) {
    static_cast<void>(portNum);
    const U8* data = fwBuffer.getData();
    this->m_localFrames.push_back(std::vector<U8>(data, data + fwBuffer.getSize()));
    this->pushFromPortEntry_localRecvOut(fwBuffer);
}

void UartChannelMuxTester::testWrapsAndRoutesChannelFrames() {
    const U8 payloadBytes[] = {0x4E, 0x32, 0x01, 0x02, 0x03};
    const U8 localBytes[] = {LinkCfg::TEENSY_TARGET_PDU, 0x22, 0x03, 0x00};

    this->clearHistory();
    this->m_txFrames.clear();
    this->m_payloadFrames.clear();
    this->m_localFrames.clear();

    Fw::Buffer payloadBuffer(const_cast<U8*>(payloadBytes), sizeof(payloadBytes));
    this->invoke_to_payloadSendIn(0, payloadBuffer);
#ifdef NEUTRON2_CDR_TCP
    ASSERT_from_drvSendOut_SIZE(0);
    ASSERT_EQ(this->m_txFrames.size(), 0U);
#else
    ASSERT_from_drvSendOut_SIZE(1);
    ASSERT_EQ(this->m_txFrames.size(), 1U);
    ASSERT_EQ(this->m_txFrames[0].size(), sizeof(payloadBytes) + LinkCfg::UART_FRAME_OVERHEAD);
    EXPECT_EQ(this->m_txFrames[0][0], LinkCfg::UART_FRAME_MAGIC_0);
    EXPECT_EQ(this->m_txFrames[0][1], LinkCfg::UART_FRAME_MAGIC_1);
    EXPECT_EQ(this->m_txFrames[0][2], LinkCfg::CHANNEL_PAYLOAD);
    EXPECT_EQ(this->m_txFrames[0][3], sizeof(payloadBytes));
    EXPECT_EQ(this->m_txFrames[0][4], 0U);
    for (FwSizeType i = 0; i < sizeof(payloadBytes); ++i) {
        EXPECT_EQ(this->m_txFrames[0][5 + i], payloadBytes[i]);
    }
#endif

    Fw::Buffer localBuffer(const_cast<U8*>(localBytes), sizeof(localBytes));
    this->invoke_to_localSendIn(0, localBuffer);
#ifdef NEUTRON2_CDR_TCP
    ASSERT_from_drvSendOut_SIZE(1);
    ASSERT_EQ(this->m_txFrames.size(), 1U);
#else
    ASSERT_from_drvSendOut_SIZE(2);
    ASSERT_EQ(this->m_txFrames.size(), 2U);
#endif
    EXPECT_EQ(this->m_txFrames.back()[2], LinkCfg::CHANNEL_TEENSY_LOCAL);
#ifdef NEUTRON2_CDR_TCP
    ASSERT_TLM_FramesTx(0, 1);
#else
    ASSERT_TLM_FramesTx(0, 1);
    ASSERT_TLM_FramesTx(1, 2);
#endif

    const std::vector<U8> localFrame = makeFrame(LinkCfg::CHANNEL_TEENSY_LOCAL, localBytes, sizeof(localBytes));
    const FwSizeType split = 3;
    Fw::Buffer localFramePart0(const_cast<U8*>(localFrame.data()), split);
    Fw::Buffer localFramePart1(
        const_cast<U8*>(localFrame.data() + split),
        static_cast<FwSizeType>(localFrame.size() - split));
    this->invoke_to_drvReceiveIn(0, localFramePart0, Drv::ByteStreamStatus::OP_OK);
    ASSERT_from_localRecvOut_SIZE(0);
    this->invoke_to_drvReceiveIn(0, localFramePart1, Drv::ByteStreamStatus::OP_OK);
    ASSERT_from_localRecvOut_SIZE(1);
    ASSERT_EQ(this->m_localFrames.size(), 1U);
    ASSERT_EQ(this->m_localFrames[0].size(), sizeof(localBytes));
    for (FwSizeType i = 0; i < sizeof(localBytes); ++i) {
        EXPECT_EQ(this->m_localFrames[0][i], localBytes[i]);
    }

    const std::vector<U8> payloadFrame =
        makeFrame(LinkCfg::CHANNEL_PAYLOAD, payloadBytes, sizeof(payloadBytes));
    Fw::Buffer incomingPayload(const_cast<U8*>(payloadFrame.data()), payloadFrame.size());
    this->invoke_to_drvReceiveIn(0, incomingPayload, Drv::ByteStreamStatus::OP_OK);
#ifdef NEUTRON2_CDR_TCP
    ASSERT_from_payloadRecvOut_SIZE(0);
    ASSERT_EQ(this->m_payloadFrames.size(), 0U);
#else
    ASSERT_from_payloadRecvOut_SIZE(1);
    ASSERT_EQ(this->m_payloadFrames.size(), 1U);
    ASSERT_EQ(this->m_payloadFrames[0].size(), sizeof(payloadBytes));
    for (FwSizeType i = 0; i < sizeof(payloadBytes); ++i) {
        EXPECT_EQ(this->m_payloadFrames[0][i], payloadBytes[i]);
    }
#endif
}

void UartChannelMuxTester::testDropsUnconnectedCcsdsReceive() {
    UartChannelMux unconnectedMux("UnconnectedCcsdsMux");
    unconnectedMux.init(static_cast<FwEnumStoreType>(TEST_INSTANCE_ID + 1));

    const U8 ccsdsBytes[] = {0x08, 0x01, 0x02, 0x03};
    const std::vector<U8> ccsdsFrame = makeFrame(LinkCfg::CHANNEL_CCSDS, ccsdsBytes, sizeof(ccsdsBytes));
    Fw::Buffer incoming(const_cast<U8*>(ccsdsFrame.data()), static_cast<FwSizeType>(ccsdsFrame.size()));
    unconnectedMux.get_drvReceiveIn_InputPort(0)->invoke(incoming, Drv::ByteStreamStatus::OP_OK);

    // An unconnected channel-0 output must be rejected cleanly instead of invoking a null port.
    unconnectedMux.deinit();
}

std::vector<U8> UartChannelMuxTester::makeFrame(U8 channel, const U8* payload, FwSizeType size) {
    std::vector<U8> frame;
    frame.reserve(static_cast<std::size_t>(size + LinkCfg::UART_FRAME_OVERHEAD));
    frame.push_back(LinkCfg::UART_FRAME_MAGIC_0);
    frame.push_back(LinkCfg::UART_FRAME_MAGIC_1);
    frame.push_back(channel);
    frame.push_back(static_cast<U8>(size & 0xFFU));
    frame.push_back(static_cast<U8>((size >> 8U) & 0xFFU));
    for (FwSizeType i = 0; i < size; ++i) {
        frame.push_back(payload[i]);
    }
    const U16 crc = crc16Ccitt(payload, size);
    frame.push_back(static_cast<U8>(crc & 0xFFU));
    frame.push_back(static_cast<U8>((crc >> 8U) & 0xFFU));
    return frame;
}

U16 UartChannelMuxTester::crc16Ccitt(const U8* data, FwSizeType size) {
    U16 crc = 0xFFFFU;
    for (FwSizeType i = 0; i < size; ++i) {
        crc ^= static_cast<U16>(data[i]) << 8U;
        for (U8 bit = 0; bit < 8U; ++bit) {
            if ((crc & 0x8000U) != 0U) {
                crc = static_cast<U16>((crc << 1U) ^ 0x1021U);
            } else {
                crc = static_cast<U16>(crc << 1U);
            }
        }
    }
    return crc;
}

}  // namespace Components
