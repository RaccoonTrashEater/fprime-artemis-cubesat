#include "PayloadDownlinkAppTester.hpp"

TEST(Nominal, FileBackedVariableLengthPackets) {
    Components::PayloadDownlinkAppTester tester;
    tester.testFileBackedVariableLengthPackets();
}

TEST(Nominal, ProgressEventsEveryTenPercent) {
    Components::PayloadDownlinkAppTester tester;
    tester.testProgressEventsEveryTenPercent();
}

TEST(Nominal, QueuesRetryPacketsForScheduledResend) {
    Components::PayloadDownlinkAppTester tester;
    tester.testQueuesRetryPacketsForScheduledResend();
}

TEST(Nominal, DescriptorSnapshotAndExactSourceValidation) {
    Components::PayloadDownlinkAppTester tester;
    tester.testDescriptorSnapshotAndExactSourceValidation();
}

TEST(Nominal, BusyRejectionConsumesTransferIdSequence) {
    Components::PayloadDownlinkAppTester tester;
    tester.testBusyRejectionConsumesTransferIdSequence();
}

TEST(Nominal, TransferIdWrapSkipsZeroAndConsumesFailedRequestOnce) {
    Components::PayloadDownlinkAppTester tester;
    tester.testTransferIdWrapSkipsZeroAndConsumesFailedRequestOnce();
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
