#include "Components/CommsApp/CommsApp.hpp"

namespace Components {

namespace {
constexpr U32 VERIFIED_DOWNLINK_REJECT_ZERO_TOKEN = 1U;
constexpr U32 VERIFIED_DOWNLINK_REJECT_REUSED_TOKEN = 2U;
constexpr U32 VERIFIED_DOWNLINK_REJECT_TABLE_FULL = 3U;
constexpr U32 VERIFIED_DOWNLINK_REJECT_BUSY = 4U;
constexpr U32 VERIFIED_DOWNLINK_REJECT_NO_PRODUCT = 5U;
constexpr U32 VERIFIED_DOWNLINK_REJECT_NO_STORAGE_ROUTE = 6U;
constexpr U32 VERIFIED_DOWNLINK_REJECT_ROUTE_FAILED = 7U;
constexpr U32 PAYLOAD_DOWNLINK_STATE_ERROR = 4U;

bool isFreshTransferId(U32 candidate, U32 baseline) {
    if ((candidate == 0U) || (candidate > 0xFFU)) {
        return false;
    }
    if (baseline == 0U) {
        return true;
    }
    // Sender transfer IDs are U8 and skip zero. Accept only a forward distance
    // in the unambiguous half of the sequence space; a long gap fails closed.
    const U32 distance = (candidate - baseline) & 0xFFU;
    return (distance > 0U) && (distance < 0x80U);
}
}  // namespace

CommsApp::CommsApp(const char* const compName)
    : CommsAppComponentBase(compName),
      m_linkState(0),
      m_rssiDbm(-120),
      m_rssiPingPending(false),
      m_linkStatusPollPending(false),
      m_pendingProductId(0),
      m_pendingScienceBytes(0),
      m_pendingSourceKind(Components::ScienceProductSource::UNKNOWN),
      m_pendingSourcePath(""),
      m_pendingSourceCrc(0),
      m_linkPollCount(0),
      m_activeDownlinkBytes(0),
      m_activeProductId(0),
      m_activeTransferId(0),
      m_activeSourceCrc(0),
      m_activeVerificationToken(0),
      m_activeTransferWatermark(0),
      m_latestObservedPayloadTransferId(0),
      m_haveObservedPayloadTransferId(false),
      m_verifiedDownlinkTokenCount(0),
      m_verifiedDownlinkTokens{},
      m_lastPayloadDownlinkState(0),
      m_downlinkActive(false) {}

CommsApp::~CommsApp() {}

void CommsApp::pingIn_handler(FwIndexType portNum, U32 key) {
    static_cast<void>(portNum);
    this->pingOut_out(0, key);
}

void CommsApp::run_handler(FwIndexType portNum, U32 context) {
    static_cast<void>(portNum);
    static_cast<void>(context);

    this->requestDriverStatus();
    if (this->isConnected_sohStatusOut_OutputPort(0)) {
        Components::HealthState health = Components::HealthState::UNKNOWN;
        if (this->m_linkState == 2U) {
            health = Components::HealthState::OK;
        } else if ((this->m_linkState == 1U) || (this->m_linkState == 3U)) {
            health = Components::HealthState::WARN;
        } else if (this->m_linkState == 0U) {
            health = Components::HealthState::FAIL;
        }
        this->sohStatusOut_out(0, health, this->m_linkState);
    }

    this->tlmWrite_LinkState(this->m_linkState);
    this->tlmWrite_PendingScienceBytes(this->m_pendingScienceBytes);
    this->tlmWrite_LinkPollCount(this->m_linkPollCount);
    this->tlmWrite_RssiDbm(this->m_rssiDbm);
}

void CommsApp::linkStatusIn_handler(FwIndexType portNum, U32 key) {
    static_cast<void>(portNum);
    const U32 previousLinkState = this->m_linkState;
    this->m_linkState = key;
    if (this->m_linkState != previousLinkState) {
        this->log_ACTIVITY_LO_LinkStateUpdated(this->m_linkState, this->m_rssiDbm);
    }
}

void CommsApp::scienceReadyIn_handler(FwIndexType portNum,
                                          U32 productId,
                                          U32 productBytes,
                                          const Components::ScienceProductSource& sourceKind,
                                          const Fw::StringBase& sourcePath,
                                          U32 sourceCrc) {
    static_cast<void>(portNum);
    this->m_pendingProductId = productId;
    this->m_pendingScienceBytes = productBytes;
    this->m_pendingSourceKind = sourceKind;
    this->m_pendingSourcePath = sourcePath;
    this->m_pendingSourceCrc = sourceCrc;
}

void CommsApp::deliveryDescriptorIn_handler(FwIndexType portNum,
                                            U32 productId,
                                            U32 productBytes,
                                            const Components::ScienceProductSource& sourceKind,
                                            const Fw::StringBase& sourcePath,
                                            U32 sourceCrc) {
    static_cast<void>(portNum);
    this->beginDownlink(productId, productBytes, sourceKind, sourcePath, sourceCrc);
}

void CommsApp::driverStatusIn_handler(FwIndexType portNum, U32 key) {
    static_cast<void>(portNum);
    const U32 previousLinkState = this->m_linkState;
    this->m_linkState = key;
    if ((this->m_linkState != previousLinkState) || this->m_linkStatusPollPending || this->m_rssiPingPending) {
        this->log_ACTIVITY_LO_LinkStateUpdated(this->m_linkState, this->m_rssiDbm);
    }
    this->m_linkStatusPollPending = false;
    if (this->m_rssiPingPending) {
        this->log_ACTIVITY_HI_LinkRssiPing(this->m_linkState, this->m_rssiDbm, this->m_linkPollCount);
        this->m_rssiPingPending = false;
    }
}

void CommsApp::rssiStatusIn_handler(FwIndexType portNum, I32 rssiDbm) {
    static_cast<void>(portNum);
    this->m_rssiDbm = rssiDbm;
}

void CommsApp::payloadDownlinkStatusIn_handler(FwIndexType portNum,
                                                   U32 state,
                                                   U32 transferId,
                                                   U32 productId,
                                                   U32 totalBytes,
                                                   U32 packetsSent,
                                                   U32 totalPackets,
                                                   U32 lastError) {
    static_cast<void>(portNum);
    static_cast<void>(packetsSent);
    static_cast<void>(totalPackets);

    this->m_lastPayloadDownlinkState = state;
    if (isFreshTransferId(transferId, this->m_latestObservedPayloadTransferId)) {
        this->m_latestObservedPayloadTransferId = transferId;
        this->m_haveObservedPayloadTransferId = true;
    }
    if (!this->m_downlinkActive || (productId != this->m_activeProductId)) {
        return;
    }

    if (this->m_activeTransferId == 0U) {
        // Bind only to a new sender sequence. A fresh ERROR is emitted when a
        // request is rejected before DOWNLINKING (for example, a missing file).
        // Old callbacks for the same product cannot terminate a new request.
        if (((state != 1U) && (state != 4U)) ||
            !isFreshTransferId(transferId, this->m_activeTransferWatermark)) {
            return;
        }
        this->m_activeTransferId = transferId;
    } else if (transferId != this->m_activeTransferId) {
        return;
    }

    // Token zero identifies an automatic capture's downlink. The ground
    // verifier also consumes this sender status to report failures explicitly.
    this->logVerifiedDownlinkStatus(this->m_activeVerificationToken, this->m_activeProductId,
                                    this->m_activeDownlinkBytes, this->m_activeSourceCrc,
                                    this->m_activeTransferId, state, lastError, 0U);

    if (state == 2U) {
        this->log_ACTIVITY_HI_DownlinkFinished(totalBytes);
        if (this->isConnected_missionModeOut_OutputPort(0)) {
            this->missionModeOut_out(0, Components::MissionMode::BASE, totalBytes);
        }
        if (this->m_pendingProductId == this->m_activeProductId) {
            this->m_pendingScienceBytes = 0U;
            this->m_pendingProductId = 0U;
            this->m_pendingSourceKind = Components::ScienceProductSource::UNKNOWN;
            this->m_pendingSourcePath = "";
            this->m_pendingSourceCrc = 0U;
        }
        this->m_activeDownlinkBytes = 0;
        this->m_activeProductId = 0U;
        this->m_activeTransferId = 0U;
        this->m_activeSourceCrc = 0U;
        this->m_activeVerificationToken = 0U;
        this->m_activeTransferWatermark = 0U;
        this->m_downlinkActive = false;
    } else if ((state == 3U) || (state == 4U)) {
        this->log_WARNING_LO_DownlinkFailed(state, lastError);
        if (this->isConnected_missionModeOut_OutputPort(0)) {
            this->missionModeOut_out(0, Components::MissionMode::BASE, lastError);
        }
        this->m_activeDownlinkBytes = 0;
        this->m_activeProductId = 0U;
        this->m_activeTransferId = 0U;
        this->m_activeSourceCrc = 0U;
        this->m_activeVerificationToken = 0U;
        this->m_activeTransferWatermark = 0U;
        this->m_downlinkActive = false;
    }
}

void CommsApp::REQUEST_SCIENCE_DOWNLINK_cmdHandler(FwOpcodeType opCode, U32 cmdSeq) {
    if (this->m_pendingScienceBytes == 0U) {
        this->log_WARNING_LO_CommsCommandRejected(1U, 0U);
        this->cmdResponse_out(opCode, cmdSeq, Fw::CmdResponse::VALIDATION_ERROR);
        return;
    }
    const bool started = this->beginDownlink(this->m_pendingProductId,
                                             this->m_pendingScienceBytes,
                                             this->m_pendingSourceKind,
                                             this->m_pendingSourcePath,
                                             this->m_pendingSourceCrc);
    if (started && this->isConnected_downlinkRequestOut_OutputPort(0)) {
        this->downlinkRequestOut_out(0,
                                     this->m_pendingProductId,
                                     this->m_pendingScienceBytes,
                                     this->m_pendingSourceKind,
                                     this->m_pendingSourcePath,
                                     this->m_pendingSourceCrc);
    }
    this->cmdResponse_out(opCode, cmdSeq, started ? Fw::CmdResponse::OK : Fw::CmdResponse::EXECUTION_ERROR);
}

bool CommsApp::beginDownlink(U32 productId,
                             U32 productBytes,
                             const Components::ScienceProductSource& sourceKind,
                             const Fw::StringBase& sourcePath,
                             U32 sourceCrc,
                             U32 verificationToken) {
    if (this->m_downlinkActive) {
        this->log_WARNING_LO_CommsCommandRejected(2U, productId);
        return false;
    }
    if ((productId == 0U) || (productBytes == 0U) ||
        (sourceKind == Components::ScienceProductSource::UNKNOWN) || (sourcePath.length() == 0U)) {
        this->log_WARNING_LO_CommsCommandRejected(1U, productId);
        return false;
    }
    if (!this->isConnected_payloadDownlinkRequestOut_OutputPort(0)) {
        this->log_WARNING_LO_DownlinkFailed(4U, 3U);
        return false;
    }

    this->m_activeDownlinkBytes = productBytes;
    this->m_activeProductId = productId;
    this->m_activeTransferId = 0U;
    this->m_activeSourceCrc = sourceCrc;
    this->m_activeVerificationToken = verificationToken;
    this->m_activeTransferWatermark = this->m_haveObservedPayloadTransferId
        ? this->m_latestObservedPayloadTransferId
        : 0U;
    this->m_downlinkActive = true;
    this->log_ACTIVITY_HI_DownlinkRequested(productBytes);
    if (this->isConnected_missionModeOut_OutputPort(0)) {
        this->missionModeOut_out(0, Components::MissionMode::DOWNLINKING, productBytes);
    }
    this->payloadDownlinkRequestOut_out(0, productId, productBytes, sourceKind, sourcePath, sourceCrc);
    return true;
}

void CommsApp::logVerifiedDownlinkStatus(U32 verificationToken, U32 productId, U32 productBytes,
                                         U32 sourceCrc, U32 transferId, U32 stateValue, U32 lastError,
                                         U32 reasonCode) {
    this->log_ACTIVITY_HI_VerifiedDownlinkStatus(verificationToken, productId, productBytes, sourceCrc,
                                                 transferId, stateValue, lastError, reasonCode);
}

void CommsApp::REQUEST_LINK_STATUS_cmdHandler(FwOpcodeType opCode, U32 cmdSeq) {
    this->m_linkPollCount += 1U;
    this->m_linkStatusPollPending = true;
    this->requestDriverStatus();
    this->cmdResponse_out(opCode, cmdSeq, Fw::CmdResponse::OK);
}

void CommsApp::PING_LINK_RSSI_cmdHandler(FwOpcodeType opCode, U32 cmdSeq) {
    this->m_linkPollCount += 1U;
    this->m_rssiPingPending = true;
    this->requestDriverStatus();
    this->cmdResponse_out(opCode, cmdSeq, Fw::CmdResponse::OK);
}

void CommsApp::VERIFIED_REQUEST_SCIENCE_DOWNLINK_cmdHandler(FwOpcodeType opCode, U32 cmdSeq,
                                                            U32 verificationToken) {
    if (verificationToken == 0U) {
        this->logVerifiedDownlinkStatus(verificationToken, 0U, 0U, 0U, 0U,
                                        PAYLOAD_DOWNLINK_STATE_ERROR, VERIFIED_DOWNLINK_REJECT_ZERO_TOKEN,
                                        VERIFIED_DOWNLINK_REJECT_ZERO_TOKEN);
        this->cmdResponse_out(opCode, cmdSeq, Fw::CmdResponse::VALIDATION_ERROR);
        return;
    }
    for (U32 index = 0U; index < this->m_verifiedDownlinkTokenCount; ++index) {
        if (this->m_verifiedDownlinkTokens[index] == verificationToken) {
            this->logVerifiedDownlinkStatus(verificationToken, 0U, 0U, 0U, 0U,
                                            PAYLOAD_DOWNLINK_STATE_ERROR, VERIFIED_DOWNLINK_REJECT_REUSED_TOKEN,
                                            VERIFIED_DOWNLINK_REJECT_REUSED_TOKEN);
            this->cmdResponse_out(opCode, cmdSeq, Fw::CmdResponse::VALIDATION_ERROR);
            return;
        }
    }
    if (this->m_verifiedDownlinkTokenCount >= VERIFIED_DOWNLINK_TOKEN_CAPACITY) {
        this->logVerifiedDownlinkStatus(verificationToken, 0U, 0U, 0U, 0U,
                                        PAYLOAD_DOWNLINK_STATE_ERROR, VERIFIED_DOWNLINK_REJECT_TABLE_FULL,
                                        VERIFIED_DOWNLINK_REJECT_TABLE_FULL);
        this->cmdResponse_out(opCode, cmdSeq, Fw::CmdResponse::EXECUTION_ERROR);
        return;
    }
    this->m_verifiedDownlinkTokens[this->m_verifiedDownlinkTokenCount++] = verificationToken;

    if (this->m_downlinkActive) {
        this->logVerifiedDownlinkStatus(verificationToken, 0U, 0U, 0U, 0U,
                                        PAYLOAD_DOWNLINK_STATE_ERROR, VERIFIED_DOWNLINK_REJECT_BUSY,
                                        VERIFIED_DOWNLINK_REJECT_BUSY);
        this->cmdResponse_out(opCode, cmdSeq, Fw::CmdResponse::EXECUTION_ERROR);
        return;
    }
    if ((this->m_pendingProductId == 0U) || (this->m_pendingScienceBytes == 0U) ||
        (this->m_pendingSourceKind == Components::ScienceProductSource::UNKNOWN) ||
        (this->m_pendingSourcePath.length() == 0U)) {
        this->logVerifiedDownlinkStatus(verificationToken, 0U, 0U, 0U, 0U,
                                        PAYLOAD_DOWNLINK_STATE_ERROR, VERIFIED_DOWNLINK_REJECT_NO_PRODUCT,
                                        VERIFIED_DOWNLINK_REJECT_NO_PRODUCT);
        this->cmdResponse_out(opCode, cmdSeq, Fw::CmdResponse::VALIDATION_ERROR);
        return;
    }
    if (!this->isConnected_downlinkRequestOut_OutputPort(0)) {
        this->logVerifiedDownlinkStatus(verificationToken, this->m_pendingProductId,
                                        this->m_pendingScienceBytes, this->m_pendingSourceCrc, 0U,
                                        PAYLOAD_DOWNLINK_STATE_ERROR, VERIFIED_DOWNLINK_REJECT_NO_STORAGE_ROUTE,
                                        VERIFIED_DOWNLINK_REJECT_NO_STORAGE_ROUTE);
        this->cmdResponse_out(opCode, cmdSeq, Fw::CmdResponse::EXECUTION_ERROR);
        return;
    }

    const bool started = this->beginDownlink(this->m_pendingProductId,
                                             this->m_pendingScienceBytes,
                                             this->m_pendingSourceKind,
                                             this->m_pendingSourcePath,
                                             this->m_pendingSourceCrc,
                                             verificationToken);
    if (started) {
        // Bind the token and descriptor in component state before either async
        // output can produce a sender status callback.
        this->downlinkRequestOut_out(0, this->m_activeProductId, this->m_activeDownlinkBytes,
                                     this->m_pendingSourceKind, this->m_pendingSourcePath,
                                     this->m_activeSourceCrc);
    } else {
        this->logVerifiedDownlinkStatus(verificationToken, this->m_pendingProductId,
                                        this->m_pendingScienceBytes, this->m_pendingSourceCrc, 0U,
                                        PAYLOAD_DOWNLINK_STATE_ERROR, VERIFIED_DOWNLINK_REJECT_ROUTE_FAILED,
                                        VERIFIED_DOWNLINK_REJECT_ROUTE_FAILED);
    }
    this->cmdResponse_out(opCode, cmdSeq, started ? Fw::CmdResponse::OK : Fw::CmdResponse::EXECUTION_ERROR);
}

void CommsApp::requestDriverStatus() {
    if (this->isConnected_driverRequestOut_OutputPort(0)) {
        const U32 normalizedLink = (this->m_linkState <= 3U) ? this->m_linkState : 0U;
        // Driver poll key contract: 1=down, 2=acquiring, 3=locked, 4=degraded
        this->driverRequestOut_out(0, normalizedLink + 1U);
    }
}

}  // namespace Components
