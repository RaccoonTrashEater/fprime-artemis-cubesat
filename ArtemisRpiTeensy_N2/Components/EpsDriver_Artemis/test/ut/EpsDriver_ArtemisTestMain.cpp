#include "EpsDriver_ArtemisTester.hpp"

TEST(Nominal, TimeoutClearsPendingRequest) {
    Components::EpsDriver_ArtemisTester tester;
    tester.testTimeoutClearsPendingRequest();
}

TEST(Nominal, BusyRequestDoesNotReplacePendingIdentity) {
    Components::EpsDriver_ArtemisTester tester;
    tester.testBusyRequestDoesNotReplacePendingIdentity();
}

TEST(Nominal, OutputReadbackValidationAndBitmapMapping) {
    Components::EpsDriver_ArtemisTester tester;
    tester.testOutputReadbackValidationAndBitmapMapping();
}

TEST(Nominal, LegacyAndExtendedProtocolInfo) {
    Components::EpsDriver_ArtemisTester tester;
    tester.testLegacyAndExtendedProtocolInfo();
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
