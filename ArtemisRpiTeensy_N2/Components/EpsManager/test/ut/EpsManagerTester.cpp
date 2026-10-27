#include "EpsManagerTester.hpp"

namespace Components {

EpsManagerTester::EpsManagerTester()
    : EpsManagerGTestBase("EpsManagerTester", MAX_HISTORY_SIZE),
      component("EpsManager"),
      m_requests() {
    this->initComponents();
    this->connectPorts();
}

EpsManagerTester::~EpsManagerTester() {
    this->component.deinit();
}

void EpsManagerTester::from_driverRequestOut_handler(
    FwIndexType portNum,
    const Components::EpsRequest& request,
    U8 outputId,
    U8 state,
    U16 durationMs
) {
    static_cast<void>(portNum);
    this->m_requests.push_back(Request{request, outputId, state, durationMs});
    this->pushFromPortEntry_driverRequestOut(request, outputId, state, durationMs);
}

void EpsManagerTester::sendStatus(
    Components::EpsRequest request,
    U8 linkState,
    U8 driverStatus,
    Components::HealthState health
) {
    this->invoke_to_driverStatusIn(
        0,
        health,
        linkState,
        2,
        0x0005,
        0,
        0,
        0,
        0x0F,
        driverStatus,
        0x15,
        request,
        1,
        2,
        3,
        0,
        Fw::String("000000000000"));
    this->component.doDispatch();
}

void EpsManagerTester::testCommandWaitsForTerminalResponseAndBusyDoesNotCompleteIt() {
    this->clearHistory();
    this->m_requests.clear();

    this->sendCmd_SET_EPS_RAIL_STATE(0, 10, 7, 1, 1);
    this->component.doDispatch();
    ASSERT_EQ(this->m_requests.size(), 1U);
    ASSERT_EQ(this->m_requests[0].request, Components::EpsRequest::SET_OUTPUT_STATE);
    ASSERT_EQ(this->m_requests[0].outputId, 7U);
    ASSERT_EQ(this->m_requests[0].state, 1U);
    ASSERT_CMD_RESPONSE_SIZE(0);

    this->invoke_to_run(0, 0);
    this->component.doDispatch();
    ASSERT_EQ(this->m_requests.size(), 1U);

    this->sendCmd_SET_EPS_RAIL_STATE(0, 11, 7, 0, 1);
    this->component.doDispatch();
    ASSERT_CMD_RESPONSE_SIZE(1);
    ASSERT_CMD_RESPONSE(0, EpsManagerComponentBase::OPCODE_SET_EPS_RAIL_STATE, 11, Fw::CmdResponse::BUSY);
    ASSERT_EQ(this->m_requests.size(), 1U);

    this->sendStatus(Components::EpsRequest::SET_OUTPUT_STATE, 1, 0);
    ASSERT_CMD_RESPONSE_SIZE(1);
    this->sendStatus(Components::EpsRequest::SET_OUTPUT_STATE, 2, 0, Components::HealthState::OK);
    ASSERT_CMD_RESPONSE_SIZE(2);
    ASSERT_CMD_RESPONSE(1, EpsManagerComponentBase::OPCODE_SET_EPS_RAIL_STATE, 10, Fw::CmdResponse::OK);
    ASSERT_EQ(this->m_requests.size(), 1U);
}

void EpsManagerTester::testNegativeMalformedAndTimeoutStatusesFailCommand() {
    this->clearHistory();
    this->m_requests.clear();

    this->sendCmd_REQUEST_EPS_DRIVER_INFO(0, 20);
    this->component.doDispatch();
    ASSERT_CMD_RESPONSE_SIZE(0);
    this->sendStatus(Components::EpsRequest::GET_PROTOCOL_INFO, 2, PDU_V2_STATUS_BUSY, Components::HealthState::WARN);
    ASSERT_CMD_RESPONSE_SIZE(1);
    ASSERT_CMD_RESPONSE(0, EpsManagerComponentBase::OPCODE_REQUEST_EPS_DRIVER_INFO, 20,
                        Fw::CmdResponse::EXECUTION_ERROR);

    this->sendCmd_REQUEST_EPS_RAIL(0, 21, 7);
    this->component.doDispatch();
    ASSERT_CMD_RESPONSE_SIZE(1);
    this->sendStatus(Components::EpsRequest::GET_OUTPUT_STATE, 3, 0xFA);
    ASSERT_CMD_RESPONSE_SIZE(2);
    ASSERT_CMD_RESPONSE(1, EpsManagerComponentBase::OPCODE_REQUEST_EPS_RAIL, 21,
                        Fw::CmdResponse::EXECUTION_ERROR);

    this->sendCmd_PING_EPS_DRIVER(0, 22);
    this->component.doDispatch();
    ASSERT_CMD_RESPONSE_SIZE(2);
    this->sendStatus(Components::EpsRequest::PING, 3, LinkCfg::TEENSY_STATUS_TIMEOUT);
    ASSERT_CMD_RESPONSE_SIZE(3);
    ASSERT_CMD_RESPONSE(2, EpsManagerComponentBase::OPCODE_PING_EPS_DRIVER, 22,
                        Fw::CmdResponse::EXECUTION_ERROR);
}

}  // namespace Components
