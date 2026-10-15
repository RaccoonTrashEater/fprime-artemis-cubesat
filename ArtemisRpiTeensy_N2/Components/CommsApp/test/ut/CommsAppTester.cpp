#include "CommsAppTester.hpp"

namespace Components {

CommsAppTester::CommsAppTester()
    : CommsAppGTestBase("CommsAppTester", MAX_HISTORY_SIZE),
      component("CommsApp") {
    this->initComponents();
    this->connectPorts();
}

CommsAppTester::~CommsAppTester() {
    this->component.deinit();
}

void CommsAppTester::testRejectsDownlinkWithoutScience() {
    this->clearHistory();

    this->sendCmd_REQUEST_SCIENCE_DOWNLINK(0, 0);
    this->component.doDispatch();

    ASSERT_CMD_RESPONSE_SIZE(1);
    ASSERT_CMD_RESPONSE(0, CommsAppComponentBase::OPCODE_REQUEST_SCIENCE_DOWNLINK, 0,
                        Fw::CmdResponse::VALIDATION_ERROR);
    ASSERT_EVENTS_CommsCommandRejected_SIZE(1);
    ASSERT_EVENTS_CommsCommandRejected(0, 1, 0);
    ASSERT_EVENTS_DownlinkFailed_SIZE(0);
    ASSERT_from_downlinkRequestOut_SIZE(0);
    ASSERT_from_payloadDownlinkRequestOut_SIZE(0);
    ASSERT_from_missionModeOut_SIZE(0);
}

void CommsAppTester::testRequestsScienceDownlinkAndCompletionClearsState() {
    this->clearHistory();

    Fw::String sourcePath("/tmp/science.bin");
    this->invoke_to_scienceReadyIn(0, 7, 128, Components::ScienceProductSource::NEUTRON_SIM, sourcePath, 0x1234);
    this->component.doDispatch();
    this->sendCmd_REQUEST_SCIENCE_DOWNLINK(0, 0);
    this->component.doDispatch();

    ASSERT_CMD_RESPONSE_SIZE(1);
    ASSERT_CMD_RESPONSE(0, CommsAppComponentBase::OPCODE_REQUEST_SCIENCE_DOWNLINK, 0,
                        Fw::CmdResponse::OK);
    ASSERT_EVENTS_DownlinkRequested_SIZE(1);
    ASSERT_EVENTS_DownlinkRequested(0, 128);
    ASSERT_from_missionModeOut_SIZE(1);
    ASSERT_from_missionModeOut(0, Components::MissionMode::DOWNLINKING, 128);
    ASSERT_from_downlinkRequestOut_SIZE(1);
    ASSERT_from_downlinkRequestOut(0, 7, 128, Components::ScienceProductSource::NEUTRON_SIM, sourcePath, 0x1234);
    ASSERT_from_payloadDownlinkRequestOut_SIZE(1);
    ASSERT_from_payloadDownlinkRequestOut(0, 7, 128, Components::ScienceProductSource::NEUTRON_SIM, sourcePath, 0x1234);

    this->invoke_to_payloadDownlinkStatusIn(0, 1, 1, 7, 128, 0, 4, 0);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 2, 1, 7, 128, 4, 4, 0);
    this->component.doDispatch();

    ASSERT_EVENTS_DownlinkFinished_SIZE(1);
    ASSERT_EVENTS_DownlinkFinished(0, 128);
    ASSERT_from_missionModeOut_SIZE(2);
    ASSERT_from_missionModeOut(1, Components::MissionMode::BASE, 128);

    this->sendCmd_REQUEST_SCIENCE_DOWNLINK(0, 1);
    this->component.doDispatch();
    ASSERT_CMD_RESPONSE_SIZE(2);
    ASSERT_CMD_RESPONSE(1, CommsAppComponentBase::OPCODE_REQUEST_SCIENCE_DOWNLINK, 1,
                        Fw::CmdResponse::VALIDATION_ERROR);
}

void CommsAppTester::testDownlinkFailureReturnsBase() {
    this->clearHistory();

    Fw::String sourcePath("/tmp/science.bin");
    this->invoke_to_scienceReadyIn(0, 8, 64, Components::ScienceProductSource::TEST, sourcePath, 0x55);
    this->component.doDispatch();
    this->sendCmd_REQUEST_SCIENCE_DOWNLINK(0, 0);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 1, 2, 8, 64, 0, 2, 0);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 3, 2, 8, 64, 1, 2, 99);
    this->component.doDispatch();

    ASSERT_EVENTS_DownlinkFailed_SIZE(1);
    ASSERT_EVENTS_DownlinkFailed(0, 3, 99);
    ASSERT_from_missionModeOut_SIZE(2);
    ASSERT_from_missionModeOut(1, Components::MissionMode::BASE, 99);
}

void CommsAppTester::testIgnoresPayloadStatusWhenInactive() {
    this->clearHistory();

    this->invoke_to_payloadDownlinkStatusIn(0, 2, 1, 7, 128, 4, 4, 0);
    this->component.doDispatch();

    ASSERT_EVENTS_DownlinkFinished_SIZE(0);
    ASSERT_EVENTS_DownlinkFailed_SIZE(0);
    ASSERT_from_missionModeOut_SIZE(0);
}

void CommsAppTester::testOldCompletionCannotFinishNewProductAndNewPendingSurvives() {
    this->clearHistory();
    Fw::String oldPath("/tmp/older-science.bin");
    Fw::String newPath("/tmp/newer-science.bin");
    this->invoke_to_scienceReadyIn(0, 7U, 128U, Components::ScienceProductSource::TEST, oldPath, 0x11U);
    this->component.doDispatch();
    this->sendCmd_REQUEST_SCIENCE_DOWNLINK(0, 0);
    this->component.doDispatch();
    ASSERT_CMD_RESPONSE(0, CommsAppComponentBase::OPCODE_REQUEST_SCIENCE_DOWNLINK, 0, Fw::CmdResponse::OK);

    // This stale terminal has the same product but belongs to an older transfer.
    this->invoke_to_payloadDownlinkStatusIn(0, 2U, 1U, 7U, 128U, 4U, 4U, 0U);
    this->component.doDispatch();
    ASSERT_EVENTS_DownlinkFinished_SIZE(0);

    this->invoke_to_scienceReadyIn(0, 8U, 256U, Components::ScienceProductSource::TEST, newPath, 0x22U);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 1U, 2U, 7U, 128U, 0U, 4U, 0U);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 2U, 2U, 7U, 128U, 4U, 4U, 0U);
    this->component.doDispatch();
    ASSERT_EVENTS_DownlinkFinished_SIZE(1);
    ASSERT_from_missionModeOut(1, Components::MissionMode::BASE, 128U);

    this->sendCmd_REQUEST_SCIENCE_DOWNLINK(0, 1);
    this->component.doDispatch();
    ASSERT_CMD_RESPONSE(1, CommsAppComponentBase::OPCODE_REQUEST_SCIENCE_DOWNLINK, 1, Fw::CmdResponse::OK);
    ASSERT_from_payloadDownlinkRequestOut_SIZE(2);
    ASSERT_from_payloadDownlinkRequestOut(1, 8U, 256U, Components::ScienceProductSource::TEST, newPath, 0x22U);
}

void CommsAppTester::testAutomaticDeliveryUsesSharedDownlinkGate() {
    this->clearHistory();
    Fw::String path("/tmp/automatic-science.bin");
    this->invoke_to_deliveryDescriptorIn(0, 17U, 64U, Components::ScienceProductSource::NEUTRON_SIM, path, 0xAAU);
    this->component.doDispatch();
    ASSERT_from_payloadDownlinkRequestOut_SIZE(1);
    ASSERT_from_payloadDownlinkRequestOut(0, 17U, 64U, Components::ScienceProductSource::NEUTRON_SIM, path, 0xAAU);
    ASSERT_from_missionModeOut(0, Components::MissionMode::DOWNLINKING, 64U);

    this->invoke_to_deliveryDescriptorIn(0, 18U, 128U, Components::ScienceProductSource::NEUTRON_SIM, path, 0xBBU);
    this->component.doDispatch();
    ASSERT_from_payloadDownlinkRequestOut_SIZE(1);

    this->invoke_to_payloadDownlinkStatusIn(0, 1U, 9U, 17U, 64U, 0U, 2U, 0U);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 2U, 9U, 17U, 64U, 2U, 2U, 0U);
    this->component.doDispatch();
    ASSERT_EVENTS_DownlinkFinished_SIZE(1);
    ASSERT_from_missionModeOut(1, Components::MissionMode::BASE, 64U);
}

void CommsAppTester::testBusyRejectionSequenceAllowsSubsequentDownlinks() {
    this->clearHistory();
    Fw::String firstPath("/tmp/first-science.bin");
    Fw::String secondPath("/tmp/second-science.bin");
    Fw::String thirdPath("/tmp/third-science.bin");

    this->invoke_to_scienceReadyIn(0, 7U, 128U, Components::ScienceProductSource::TEST, firstPath, 0x11U);
    this->component.doDispatch();
    this->sendCmd_REQUEST_SCIENCE_DOWNLINK(0, 0);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 1U, 1U, 7U, 128U, 0U, 4U, 0U);
    this->component.doDispatch();

    // Replay the sender sequence asserted in PayloadDownlinkAppTester:
    // active ID 1, busy rejection ID 2, then active ID 1 completes unchanged.
    this->invoke_to_payloadDownlinkStatusIn(0, 4U, 2U, 8U, 64U, 0U, 0U, 12U);
    this->component.doDispatch();
    ASSERT_EVENTS_DownlinkFinished_SIZE(0);
    ASSERT_EVENTS_DownlinkFailed_SIZE(0);
    this->invoke_to_payloadDownlinkStatusIn(0, 2U, 1U, 7U, 128U, 4U, 4U, 0U);
    this->component.doDispatch();
    ASSERT_EVENTS_DownlinkFinished_SIZE(1);

    this->invoke_to_scienceReadyIn(0, 8U, 256U, Components::ScienceProductSource::TEST, secondPath, 0x22U);
    this->component.doDispatch();
    this->sendCmd_REQUEST_SCIENCE_DOWNLINK(0, 1);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 1U, 3U, 8U, 256U, 0U, 8U, 0U);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 2U, 3U, 8U, 256U, 8U, 8U, 0U);
    this->component.doDispatch();
    ASSERT_EVENTS_DownlinkFinished_SIZE(2);

    // A third product can be admitted and completed after the consumed busy ID.
    this->invoke_to_scienceReadyIn(0, 9U, 64U, Components::ScienceProductSource::TEST, thirdPath, 0x33U);
    this->component.doDispatch();
    this->sendCmd_REQUEST_SCIENCE_DOWNLINK(0, 2);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 1U, 4U, 9U, 64U, 0U, 2U, 0U);
    this->component.doDispatch();
    this->invoke_to_payloadDownlinkStatusIn(0, 2U, 4U, 9U, 64U, 2U, 2U, 0U);
    this->component.doDispatch();
    ASSERT_EVENTS_DownlinkFinished_SIZE(3);
    ASSERT_CMD_RESPONSE_SIZE(3);
    ASSERT_CMD_RESPONSE(2, CommsAppComponentBase::OPCODE_REQUEST_SCIENCE_DOWNLINK, 2,
                        Fw::CmdResponse::OK);
    ASSERT_from_payloadDownlinkRequestOut_SIZE(3);
    ASSERT_from_payloadDownlinkRequestOut(1, 8U, 256U, Components::ScienceProductSource::TEST,
                                          secondPath, 0x22U);
    ASSERT_from_payloadDownlinkRequestOut(2, 9U, 64U, Components::ScienceProductSource::TEST,
                                          thirdPath, 0x33U);
}

void CommsAppTester::testDriverStatusPollingAndRssiPing() {
    this->clearHistory();

    this->sendCmd_REQUEST_LINK_STATUS(0, 0);
    this->component.doDispatch();
    ASSERT_CMD_RESPONSE_SIZE(1);
    ASSERT_from_driverRequestOut_SIZE(1);
    ASSERT_from_driverRequestOut(0, 1);

    this->invoke_to_driverStatusIn(0, 2);
    this->component.doDispatch();
    ASSERT_EVENTS_LinkStateUpdated_SIZE(1);
    ASSERT_EVENTS_LinkStateUpdated(0, 2, -120);

    this->invoke_to_rssiStatusIn(0, -72);
    this->component.doDispatch();
    this->sendCmd_PING_LINK_RSSI(0, 1);
    this->component.doDispatch();
    ASSERT_CMD_RESPONSE_SIZE(2);
    ASSERT_from_driverRequestOut_SIZE(2);
    ASSERT_from_driverRequestOut(1, 3);

    this->invoke_to_driverStatusIn(0, 3);
    this->component.doDispatch();
    ASSERT_EVENTS_LinkStateUpdated_SIZE(2);
    ASSERT_EVENTS_LinkStateUpdated(1, 3, -72);
    ASSERT_EVENTS_LinkRssiPing_SIZE(1);
    ASSERT_EVENTS_LinkRssiPing(0, 3, -72, 2);
}

void CommsAppTester::testRunPublishesHealthFromLinkState() {
    this->clearHistory();

    this->invoke_to_linkStatusIn(0, 0);
    this->component.doDispatch();
    this->invoke_to_run(0, 0);
    this->component.doDispatch();
    ASSERT_from_sohStatusOut_SIZE(1);
    ASSERT_from_sohStatusOut(0, Components::HealthState::FAIL, 0);
    ASSERT_from_driverRequestOut_SIZE(1);
    ASSERT_from_driverRequestOut(0, 1);

    this->invoke_to_linkStatusIn(0, 1);
    this->component.doDispatch();
    this->invoke_to_run(0, 0);
    this->component.doDispatch();
    ASSERT_from_sohStatusOut_SIZE(2);
    ASSERT_from_sohStatusOut(1, Components::HealthState::WARN, 1);

    this->invoke_to_linkStatusIn(0, 2);
    this->component.doDispatch();
    this->invoke_to_run(0, 0);
    this->component.doDispatch();
    ASSERT_from_sohStatusOut_SIZE(3);
    ASSERT_from_sohStatusOut(2, Components::HealthState::OK, 2);
}

}  // namespace Components
