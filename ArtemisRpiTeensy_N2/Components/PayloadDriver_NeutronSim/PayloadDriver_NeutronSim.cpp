#include "Components/PayloadDriver_NeutronSim/PayloadDriver_NeutronSim.hpp"

#include <cerrno>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <dirent.h>
#include <fcntl.h>
#include <limits>
#include <signal.h>
#include <string>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

namespace Components {

namespace {

constexpr const char* DEFAULT_SIM_ROOT = "../external/payload-neutron-simulation";
constexpr const char* REPO_ROOT_SIM_ROOT = "external/payload-neutron-simulation";
constexpr const char* DEFAULT_CURSOR = "/tmp/neutron_payload_sim_cursor.json";
constexpr const char* DEFAULT_OUTPUT_DIR = "/tmp/neutron_payload_captures";
constexpr const char* DEFAULT_LATEST_PAYLOAD = "/tmp/neutron_payload_captures/latest_payload.bin";
constexpr const char* DEFAULT_STORAGE_ROOT = "/home/pi/artemis/data/science-products";
constexpr const char* ID_HIGH_WATER_FILE = "product-id-high-water";
constexpr const char* PRODUCT_PREFIX = "product_";
constexpr U32 DEFAULT_CAPTURE_SECONDS = 600U;
constexpr U32 HANG_CHILD_SECONDS = 120U;
constexpr U32 MAX_CAPTURE_OUTPUT = 65536U;
constexpr U32 KILL_GRACE_MS = 200U;

std::string getProductStorageRoot() {
    const char* configured = std::getenv("N2_STORAGE_ROOT");
    if ((configured != nullptr) && (configured[0] != '\0')) {
        return std::string(configured);
    }
    return std::string(DEFAULT_STORAGE_ROOT);
}

bool ensureDirectory(const std::string& path) {
    if (path.empty()) {
        return false;
    }
    std::string current;
    std::size_t position = 0U;
    if (path[0] == '/') {
        current = "/";
        position = 1U;
    }
    while (position < path.size()) {
        const std::size_t next = path.find('/', position);
        const std::string part = path.substr(position,
                                             (next == std::string::npos) ? std::string::npos : next - position);
        position = (next == std::string::npos) ? path.size() : next + 1U;
        if (part.empty() || (part == ".")) {
            continue;
        }
        if (!current.empty() && (current.back() != '/')) {
            current += "/";
        }
        current += part;
        const std::size_t separator = current.find_last_of('/');
        const std::string parent = (separator == std::string::npos)
            ? std::string(".")
            : ((separator == 0U) ? std::string("/") : current.substr(0U, separator));
        const bool created = (::mkdir(current.c_str(), 0750) == 0);
        if (!created && (errno != EEXIST)) {
            return false;
        }
        struct stat info {};
        if ((::stat(current.c_str(), &info) != 0) || !S_ISDIR(info.st_mode)) {
            return false;
        }
        if (created) {
            const int parentFd = ::open(parent.c_str(), O_RDONLY);
            if ((parentFd < 0) || (::fsync(parentFd) != 0)) {
                if (parentFd >= 0) {
                    (void)::close(parentFd);
                }
                return false;
            }
            (void)::close(parentFd);
        }
    }
    return true;
}

bool parseProductIdFile(const char* name, U32& productId) {
    const std::size_t prefixLength = std::strlen(PRODUCT_PREFIX);
    const std::size_t nameLength = std::strlen(name);
    const char* suffix = nullptr;
    if (nameLength > prefixLength + 4U &&
        std::strcmp(name + nameLength - 4U, ".bin") == 0) {
        suffix = ".bin";
    } else if (nameLength > prefixLength + 5U &&
               std::strcmp(name + nameLength - 5U, ".meta") == 0) {
        suffix = ".meta";
    }
    if ((suffix == nullptr) || (std::strncmp(name, PRODUCT_PREFIX, prefixLength) != 0)) {
        return false;
    }
    const char* digit = name + prefixLength;
    const char* end = name + nameLength - std::strlen(suffix);
    U64 value = 0U;
    for (; digit < end; ++digit) {
        if ((*digit < '0') || (*digit > '9')) {
            return false;
        }
        value = (value * 10U) + static_cast<U64>(*digit - '0');
        if (value > std::numeric_limits<U32>::max()) {
            return false;
        }
    }
    if (value == 0U) {
        return false;
    }
    productId = static_cast<U32>(value);
    return true;
}

bool readProductIdHighWater(const std::string& path, bool& exists, U32& nextProductId) {
    exists = false;
    std::FILE* file = std::fopen(path.c_str(), "rb");
    if (file == nullptr) {
        return errno == ENOENT;
    }
    exists = true;
    char line[64] = {};
    const bool readOk = (std::fgets(line, sizeof(line), file) != nullptr) &&
                        (std::fgetc(file) == EOF) && !std::ferror(file);
    (void)std::fclose(file);
    if (!readOk || (std::strncmp(line, "N2ID1 ", 6U) != 0)) {
        return false;
    }
    errno = 0;
    char* end = nullptr;
    const unsigned long long value = std::strtoull(line + 6U, &end, 10);
    if ((errno != 0) || (end == line + 6U) || (value > std::numeric_limits<U32>::max())) {
        return false;
    }
    while ((*end == ' ') || (*end == '\t') || (*end == '\r') || (*end == '\n')) {
        ++end;
    }
    if (*end != '\0') {
        return false;
    }
    nextProductId = static_cast<U32>(value);
    return true;
}

bool writeProductIdHighWater(const std::string& root, U32 nextProductId) {
    const std::string markerPath = root + "/" + ID_HIGH_WATER_FILE;
    char contents[64];
    const int length = std::snprintf(contents, sizeof(contents), "N2ID1 %u\n", nextProductId);
    if ((length <= 0) || (static_cast<std::size_t>(length) >= sizeof(contents))) {
        return false;
    }
    std::string temporaryPath;
    int fd = -1;
    for (U32 attempt = 0U; attempt < 8U; ++attempt) {
        temporaryPath = markerPath + ".tmp." + std::to_string(::getpid()) + "." + std::to_string(attempt);
        fd = ::open(temporaryPath.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0640);
        if (fd >= 0) {
            break;
        }
        if (errno != EEXIST) {
            return false;
        }
    }
    if (fd < 0) {
        return false;
    }
    bool ok = true;
    std::size_t written = 0U;
    while (written < static_cast<std::size_t>(length)) {
        const ssize_t count = ::write(fd, contents + written, static_cast<std::size_t>(length) - written);
        if (count < 0) {
            if (errno == EINTR) {
                continue;
            }
            ok = false;
            break;
        }
        if (count == 0) {
            ok = false;
            break;
        }
        written += static_cast<std::size_t>(count);
    }
    ok = ok && (::fsync(fd) == 0);
    if (::close(fd) != 0) {
        ok = false;
    }
    if (!ok || (::rename(temporaryPath.c_str(), markerPath.c_str()) != 0)) {
        (void)::unlink(temporaryPath.c_str());
        return false;
    }
    const int directoryFd = ::open(root.c_str(), O_RDONLY);
    if (directoryFd < 0) {
        return false;
    }
    const bool directorySynced = (::fsync(directoryFd) == 0);
    (void)::close(directoryFd);
    return directorySynced;
}

bool reserveProductId(U32& productIdOut) {
    const std::string root = getProductStorageRoot();
    if (!ensureDirectory(root)) {
        return false;
    }
    const int lockFd = ::open((root + "/product-id.lock").c_str(), O_RDWR | O_CREAT, 0640);
    if (lockFd < 0) {
        return false;
    }
    int lockResult = 0;
    do {
        lockResult = ::flock(lockFd, LOCK_EX);
    } while ((lockResult != 0) && (errno == EINTR));
    if (lockResult != 0) {
        (void)::close(lockFd);
        return false;
    }

    bool markerExists = false;
    U32 markerNext = 1U;
    bool ok = readProductIdHighWater(root + "/" + ID_HIGH_WATER_FILE, markerExists, markerNext);
    U32 highestExistingId = 0U;
    DIR* directory = ok ? ::opendir(root.c_str()) : nullptr;
    if (directory == nullptr) {
        ok = false;
    }
    if (directory != nullptr) {
        struct dirent* entry = nullptr;
        for (;;) {
            errno = 0;
            entry = ::readdir(directory);
            if (entry == nullptr) {
                if (errno != 0) {
                    ok = false;
                }
                break;
            }
            U32 parsedId = 0U;
            if (parseProductIdFile(entry->d_name, parsedId) && (parsedId > highestExistingId)) {
                highestExistingId = parsedId;
            }
        }
        (void)::closedir(directory);
    }
    if (ok && markerExists && (markerNext == 0U)) {
        ok = false;
    }
    if (ok && (highestExistingId == std::numeric_limits<U32>::max())) {
        ok = false;
    }
    U32 nextProductId = markerExists ? markerNext : 1U;
    if (ok && (highestExistingId >= nextProductId)) {
        nextProductId = highestExistingId + 1U;
    }
    if (ok && (nextProductId == 0U)) {
        ok = false;
    }
    if (ok) {
        const U32 followingId = (nextProductId == std::numeric_limits<U32>::max())
            ? 0U
            : nextProductId + 1U;
        ok = writeProductIdHighWater(root, followingId);
        if (ok) {
            productIdOut = nextProductId;
        }
    }
    (void)::flock(lockFd, LOCK_UN);
    (void)::close(lockFd);
    return ok;
}

}  // namespace

PayloadDriver_NeutronSim::PayloadDriver_NeutronSim(const char* const compName)
    : PayloadDriver_NeutronSimComponentBase(compName),
      m_lastDurationSeconds(0),
      m_lastRowsCaptured(0),
      m_lastTotalCounts(0),
      m_lastSaaRows(0),
      m_lastProductBytes(0),
      m_lastExitStatus(0),
      m_lastProductId(0),
      m_lastProductCrc(0),
      m_captureSlotAvailable(true),
      m_availabilityAnnounced(false),
      m_announcedAvailable(false),
      m_captureOutputFd(-1),
      m_captureKillStage(0),
      m_captureProcessStatus(0),
      m_capturePid(0),
      m_captureRequestId(0),
      m_captureGeneration(0),
      m_captureProductId(0U),
      m_captureDurationSeconds(0),
      m_captureTimeoutMs(0),
      m_captureDelayMs(0),
      m_captureFaultMode(Components::PayloadSimulationFault::NORMAL),
      m_captureKind(Components::PayloadOperationKind::CAPTURE),
      m_captureSummary{},
      m_captureOutputBuffer(),
      m_captureOutputTotalBytes(0U),
      m_captureDeadline(),
      m_killDeadline() {}

PayloadDriver_NeutronSim::~PayloadDriver_NeutronSim() {
    if (this->m_capturePid > 0) {
        (void)::kill(this->m_capturePid, SIGKILL);
        int status = 0;
        while (::waitpid(this->m_capturePid, &status, 0) < 0 && errno == EINTR) {
        }
    }
    if (this->m_captureOutputFd >= 0) {
        (void)::close(this->m_captureOutputFd);
        this->m_captureOutputFd = -1;
    }
}

void PayloadDriver_NeutronSim::pingIn_handler(FwIndexType portNum, U32 key) {
    static_cast<void>(portNum);
    this->pingOut_out(0, key);
}

void PayloadDriver_NeutronSim::run_handler(FwIndexType portNum, U32 context) {
    static_cast<void>(portNum);
    static_cast<void>(context);
    if (this->m_capturePid > 0) {
        this->pollCapture();
    }
    const auto now = std::chrono::steady_clock::now();
    for (U32 index = 0U; index < PENDING_REPLY_CAPACITY; ++index) {
        PendingReply& pending = this->m_pendingReplies[index];
        if (pending.valid && (now >= pending.due)) {
            const PendingReply reply = pending;
            pending.valid = false;
            this->emitOperationResult(reply.requestId, reply.generation, reply.kind, reply.state,
                                      reply.literalEcho, reply.productId, reply.productBytes,
                                      reply.sourceKind, reply.sourcePath, reply.sourceCrc,
                                      reply.errorCode, reply.duplicate);
        }
    }
    this->setAvailability(this->m_captureSlotAvailable);
    this->tlmWrite_CaptureSlotAvailable(this->m_captureSlotAvailable);
}

void PayloadDriver_NeutronSim::requestIn_handler(
    FwIndexType portNum,
    U32 requestId,
    U32 generation,
    U32 durationSeconds,
    const Components::PayloadSimulationFault& faultMode,
    U32 delayMs,
    U32 timeoutMs
) {
    static_cast<void>(portNum);
    if (!this->m_captureSlotAvailable || (this->m_capturePid > 0)) {
        const std::string noText;
        this->emitOperationResult(requestId, generation, Components::PayloadOperationKind::CAPTURE,
                                  Components::PayloadOperationState::FAILED, noText, 0U, 0U,
                                  Components::ScienceProductSource::UNKNOWN, noText, 0U, 1U, false);
        return;
    }
    if (durationSeconds == 0U) {
        durationSeconds = DEFAULT_CAPTURE_SECONDS;
    }

    // The manager marks its slot unavailable when it admits this operation.
    // Publish the driver's matching transition before any early failure return.
    this->m_captureSlotAvailable = false;
    this->setAvailability(false);

    if (faultMode == Components::PayloadSimulationFault::FAIL) {
        const std::string noText;
        this->m_lastDurationSeconds = durationSeconds;
        this->m_lastExitStatus = 1U;
        this->tlmWrite_LastDurationSeconds(this->m_lastDurationSeconds);
        this->tlmWrite_LastExitStatus(this->m_lastExitStatus);
        this->log_WARNING_HI_CaptureFailed(durationSeconds, this->m_lastExitStatus);
        this->emitOperationResult(requestId, generation, Components::PayloadOperationKind::CAPTURE,
                                  Components::PayloadOperationState::FAILED, noText, 0U, 0U,
                                  Components::ScienceProductSource::UNKNOWN, noText, 0U, 1U, false);
        this->setAvailability(true);
        return;
    }

    U32 reservedProductId = 0U;
    if (!reserveProductId(reservedProductId)) {
        const std::string noText;
        this->m_lastExitStatus = 128U;
        this->tlmWrite_LastExitStatus(this->m_lastExitStatus);
        this->log_WARNING_HI_CaptureFailed(durationSeconds, this->m_lastExitStatus);
        this->emitOperationResult(requestId, generation, Components::PayloadOperationKind::CAPTURE,
                                  Components::PayloadOperationState::FAILED, noText, 0U, 0U,
                                  Components::ScienceProductSource::UNKNOWN, noText, 0U, 128U, false);
        this->setAvailability(true);
        return;
    }

    this->m_captureRequestId = requestId;
    this->m_captureGeneration = generation;
    this->m_captureProductId = reservedProductId;
    this->m_captureDurationSeconds = durationSeconds;
    this->m_captureTimeoutMs = timeoutMs;
    this->m_captureDelayMs = delayMs;
    this->m_captureFaultMode = faultMode;
    this->m_captureKind = Components::PayloadOperationKind::CAPTURE;
    this->m_captureSummary = CaptureSummary{};
    this->m_captureOutputBuffer.clear();
    this->m_captureOutputTotalBytes = 0U;
    this->m_captureKillStage = 0;
    this->m_captureProcessStatus = 0;
    if (!this->launchCapture(durationSeconds, faultMode, timeoutMs)) {
        const std::string noText;
        this->m_captureSlotAvailable = true;
        this->setAvailability(true);
        this->m_lastExitStatus = 127U;
        this->tlmWrite_LastExitStatus(this->m_lastExitStatus);
        this->log_WARNING_HI_CaptureFailed(durationSeconds, this->m_lastExitStatus);
        this->emitOperationResult(requestId, generation, Components::PayloadOperationKind::CAPTURE,
                                  Components::PayloadOperationState::FAILED, noText, 0U, 0U,
                                  Components::ScienceProductSource::UNKNOWN, noText, 0U, 127U, false);
        this->m_captureProductId = 0U;
    }
}

void PayloadDriver_NeutronSim::passthroughIn_handler(
    FwIndexType portNum,
    U32 requestId,
    U32 generation,
    const Fw::StringBase& literalCommand,
    const Components::PayloadSimulationFault& faultMode,
    U32 delayMs,
    U32 timeoutMs
) {
    static_cast<void>(portNum);
    static_cast<void>(timeoutMs);
    const std::string literal(literalCommand.toChar());
    const std::string noPath;
    Components::PayloadOperationState result = Components::PayloadOperationState::COMPLETED;
    U32 errorCode = 0U;
    bool delayed = false;
    bool duplicate = false;

    switch (faultMode) {
        case Components::PayloadSimulationFault::FAIL:
            result = Components::PayloadOperationState::FAILED;
            errorCode = 1U;
            break;
        case Components::PayloadSimulationFault::NO_RESPONSE:
            return;
        case Components::PayloadSimulationFault::DELAYED_RESPONSE:
            delayed = true;
            break;
        case Components::PayloadSimulationFault::DUPLICATE_RESPONSE:
            duplicate = true;
            break;
        case Components::PayloadSimulationFault::NORMAL:
            break;
        case Components::PayloadSimulationFault::HANG_CAPTURE:
        case Components::PayloadSimulationFault::DRIVER_UNAVAILABLE:
            result = Components::PayloadOperationState::FAILED;
            errorCode = 2U;
            break;
    }

    this->scheduleOrSendReply(requestId, generation, Components::PayloadOperationKind::PASSTHROUGH,
                              result, literal, 0U, 0U,
                              Components::ScienceProductSource::UNKNOWN, noPath, 0U,
                              errorCode, delayed, delayMs, duplicate);
}

bool PayloadDriver_NeutronSim::launchCapture(
    U32 durationSeconds,
    const Components::PayloadSimulationFault& faultMode,
    U32 timeoutMs
) {
    int pipeFd[2] = {-1, -1};
    if (::pipe(pipeFd) != 0) {
        return false;
    }

    std::string root;
    std::string script;
    std::string dataset;
    std::string duration;
    if (faultMode != Components::PayloadSimulationFault::HANG_CAPTURE) {
        root = getSimRoot();
        script = root + "/neutron_payload_sim.py";
        dataset = root + "/neutron_data.csv";
        duration = std::to_string(durationSeconds);
    }

    const pid_t child = ::fork();
    if (child < 0) {
        (void)::close(pipeFd[0]);
        (void)::close(pipeFd[1]);
        return false;
    }
    if (child == 0) {
        (void)::close(pipeFd[0]);
        if (::dup2(pipeFd[1], STDOUT_FILENO) < 0 || ::dup2(pipeFd[1], STDERR_FILENO) < 0) {
            _exit(126);
        }
        (void)::close(pipeFd[1]);
        if (faultMode == Components::PayloadSimulationFault::HANG_CAPTURE) {
            char sleepSeconds[16];
            std::snprintf(sleepSeconds, sizeof(sleepSeconds), "%u", HANG_CHILD_SECONDS);
            char* const argv[] = {const_cast<char*>("sleep"), sleepSeconds, nullptr};
            ::execvp(argv[0], argv);
        } else {
            char* const argv[] = {
                const_cast<char*>("python3"),
                const_cast<char*>(script.c_str()),
                const_cast<char*>("capture"),
                const_cast<char*>("--duration-seconds"),
                const_cast<char*>(duration.c_str()),
                const_cast<char*>("--dataset"),
                const_cast<char*>(dataset.c_str()),
                const_cast<char*>("--cursor"),
                const_cast<char*>(DEFAULT_CURSOR),
                const_cast<char*>("--output-dir"),
                const_cast<char*>(DEFAULT_OUTPUT_DIR),
                const_cast<char*>("--end-policy"),
                const_cast<char*>("wrap"),
                const_cast<char*>("--format"),
                const_cast<char*>("kv"),
                nullptr
            };
            ::execvp(argv[0], argv);
        }
        _exit(127);
    }

    (void)::close(pipeFd[1]);
    const int currentFlags = ::fcntl(pipeFd[0], F_GETFL, 0);
    if ((currentFlags < 0) || (::fcntl(pipeFd[0], F_SETFL, currentFlags | O_NONBLOCK) != 0)) {
        (void)::kill(child, SIGKILL);
        int status = 0;
        while (::waitpid(child, &status, 0) < 0 && errno == EINTR) {
        }
        (void)::close(pipeFd[0]);
        return false;
    }
    this->m_capturePid = child;
    this->m_captureOutputFd = pipeFd[0];
    this->m_captureDeadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeoutMs);
    this->m_lastDurationSeconds = durationSeconds;
    this->tlmWrite_LastDurationSeconds(this->m_lastDurationSeconds);
    return true;
}

void PayloadDriver_NeutronSim::pollCapture() {
    if (this->m_captureOutputFd >= 0) {
        char buffer[1024];
        ssize_t count = 0;
        U32 readBudget = 4096U;
        while ((readBudget > 0U) && ((count = ::read(this->m_captureOutputFd, buffer,
                                              std::min<U32>(sizeof(buffer), readBudget))) > 0)) {
            readBudget -= static_cast<U32>(count);
            this->m_captureOutputTotalBytes += static_cast<U32>(count);
            if (this->m_captureOutputTotalBytes > MAX_CAPTURE_OUTPUT) {
                this->m_captureSummary.exitStatus = 125U;
                (void)::kill(this->m_capturePid, SIGKILL);
                this->m_captureKillStage = 2;
                break;
            }
            if (this->m_captureOutputBuffer.size() + static_cast<std::size_t>(count) > MAX_CAPTURE_OUTPUT) {
                this->m_captureSummary.exitStatus = 125U;
                (void)::kill(this->m_capturePid, SIGKILL);
                this->m_captureKillStage = 2;
                break;
            }
            this->m_captureOutputBuffer.append(buffer, static_cast<std::size_t>(count));
            std::size_t newline = 0;
            while ((newline = this->m_captureOutputBuffer.find('\n')) != std::string::npos) {
                const std::string line = this->m_captureOutputBuffer.substr(0, newline + 1U);
                parseSummaryLine(line, this->m_captureSummary);
                this->m_captureOutputBuffer.erase(0, newline + 1U);
            }
        }
    }

    const auto now = std::chrono::steady_clock::now();
    if ((this->m_captureKillStage == 0) && (now >= this->m_captureDeadline)) {
        (void)::kill(this->m_capturePid, SIGTERM);
        this->m_captureKillStage = 1;
        this->m_killDeadline = now + std::chrono::milliseconds(KILL_GRACE_MS);
    } else if ((this->m_captureKillStage == 1) && (now >= this->m_killDeadline)) {
        (void)::kill(this->m_capturePid, SIGKILL);
        this->m_captureKillStage = 2;
    }

    int processStatus = 0;
    const pid_t waitResult = ::waitpid(this->m_capturePid, &processStatus, WNOHANG);
    if (waitResult == 0) {
        return;
    }
    if ((waitResult < 0) && (errno != ECHILD)) {
        return;
    }
    this->m_captureProcessStatus = processStatus;
    U32 exitStatus = 0U;
    if (waitResult < 0) {
        exitStatus = 127U;
    } else if (WIFEXITED(processStatus)) {
        exitStatus = static_cast<U32>(WEXITSTATUS(processStatus));
    } else {
        exitStatus = 128U;
    }
    if (this->m_captureKillStage > 0) {
        exitStatus = 124U;
    }

    if (this->m_captureOutputFd >= 0) {
        char buffer[1024];
        ssize_t count = 0;
        U32 readBudget = 4096U;
        while ((readBudget > 0U) && ((count = ::read(this->m_captureOutputFd, buffer,
                                              std::min<U32>(sizeof(buffer), readBudget))) > 0)) {
            readBudget -= static_cast<U32>(count);
            this->m_captureOutputTotalBytes += static_cast<U32>(count);
            this->m_captureOutputBuffer.append(buffer, static_cast<std::size_t>(count));
        }
        (void)::close(this->m_captureOutputFd);
        this->m_captureOutputFd = -1;
    }
    if (!this->m_captureOutputBuffer.empty()) {
        parseSummaryLine(this->m_captureOutputBuffer, this->m_captureSummary);
        this->m_captureOutputBuffer.clear();
    }
    this->m_capturePid = 0;
    this->finishCapture(exitStatus, (this->m_captureKillStage > 0) ||
                                      (this->m_captureFaultMode == Components::PayloadSimulationFault::NO_RESPONSE) ||
                                      (this->m_captureFaultMode == Components::PayloadSimulationFault::HANG_CAPTURE));
}

void PayloadDriver_NeutronSim::finishCapture(U32 exitStatus, bool suppressResponse) {
    CaptureSummary& summary = this->m_captureSummary;
    summary.exitStatus = exitStatus;
    if ((summary.exitStatus == 0U) &&
        ((summary.outputPath.empty()) || (summary.productBytes == 0U) ||
         !publishLatestCapture(summary.outputPath))) {
        summary.exitStatus = 126U;
    }
    U32 sourceCrc = 0U;
    if ((summary.exitStatus == 0U) && !computeFileCrc16(summary.outputPath, sourceCrc)) {
        summary.exitStatus = 125U;
    }

    const U32 productId = this->m_captureProductId;
    this->m_lastDurationSeconds = this->m_captureDurationSeconds;
    this->m_lastRowsCaptured = summary.rows;
    this->m_lastTotalCounts = summary.totalCounts;
    this->m_lastSaaRows = summary.saaRows;
    this->m_lastProductBytes = summary.productBytes;
    this->m_lastExitStatus = summary.exitStatus;
    this->m_lastProductCrc = sourceCrc;
    if (summary.exitStatus == 0U) {
        this->m_lastProductId = productId;
    }

    this->tlmWrite_LastDurationSeconds(this->m_lastDurationSeconds);
    this->tlmWrite_LastRowsCaptured(this->m_lastRowsCaptured);
    this->tlmWrite_LastTotalCounts(this->m_lastTotalCounts);
    this->tlmWrite_LastSaaRows(this->m_lastSaaRows);
    this->tlmWrite_LastProductBytes(this->m_lastProductBytes);
    this->tlmWrite_LastExitStatus(this->m_lastExitStatus);
    this->tlmWrite_LastProductId(this->m_lastProductId);
    this->tlmWrite_LastProductCrc(this->m_lastProductCrc);

    this->m_captureSlotAvailable = true;
    this->setAvailability(true);
    if (summary.exitStatus == 0U) {
        this->log_ACTIVITY_HI_CaptureComplete(this->m_captureDurationSeconds,
                                              summary.rows, summary.productBytes, productId);
        if (!suppressResponse) {
            this->scheduleOrSendReply(this->m_captureRequestId, this->m_captureGeneration,
                                      Components::PayloadOperationKind::CAPTURE,
                                      Components::PayloadOperationState::COMPLETED, "",
                                      productId, summary.productBytes,
                                      Components::ScienceProductSource::NEUTRON_SIM,
                                      summary.outputPath, sourceCrc, 0U,
                                      this->m_captureFaultMode == Components::PayloadSimulationFault::DELAYED_RESPONSE,
                                      this->m_captureDelayMs,
                                      this->m_captureFaultMode == Components::PayloadSimulationFault::DUPLICATE_RESPONSE);
        }
    } else {
        this->log_WARNING_HI_CaptureFailed(this->m_captureDurationSeconds, summary.exitStatus);
        if (!suppressResponse) {
            this->scheduleOrSendReply(this->m_captureRequestId, this->m_captureGeneration,
                                      Components::PayloadOperationKind::CAPTURE,
                                      Components::PayloadOperationState::FAILED, "", 0U, 0U,
                                      Components::ScienceProductSource::UNKNOWN, "", 0U,
                                      summary.exitStatus, false, 0U, false);
        } else {
            this->log_WARNING_HI_CaptureWorkerReaped(this->m_captureGeneration, summary.exitStatus);
        }
    }
    this->m_captureProductId = 0U;
    this->m_captureKillStage = 0;
}

void PayloadDriver_NeutronSim::scheduleOrSendReply(
    U32 requestId,
    U32 generation,
    const Components::PayloadOperationKind& kind,
    const Components::PayloadOperationState& state,
    const std::string& literalEcho,
    U32 productId,
    U32 productBytes,
    const Components::ScienceProductSource& sourceKind,
    const std::string& sourcePath,
    U32 sourceCrc,
    U32 errorCode,
    bool delayed,
    U32 delayMs,
    bool duplicate
) {
    if (delayed) {
        PendingReply* pendingSlot = nullptr;
        for (U32 index = 0U; index < PENDING_REPLY_CAPACITY; ++index) {
            if (!this->m_pendingReplies[index].valid) {
                pendingSlot = &this->m_pendingReplies[index];
                break;
            }
        }
        if (pendingSlot == nullptr) {
            this->emitOperationResult(requestId, generation, kind,
                                      Components::PayloadOperationState::FAILED, "", 0U, 0U,
                                      Components::ScienceProductSource::UNKNOWN, "", 0U, 3U, false);
            return;
        }
        *pendingSlot = PendingReply{
            true, requestId, generation, kind, state, literalEcho,
            productId, productBytes, sourceKind, sourcePath, sourceCrc,
            errorCode, std::chrono::steady_clock::now() + std::chrono::milliseconds(delayMs), duplicate
        };
        return;
    }
    this->emitOperationResult(requestId, generation, kind, state, literalEcho,
                              productId, productBytes, sourceKind, sourcePath,
                              sourceCrc, errorCode, duplicate);
}

void PayloadDriver_NeutronSim::emitOperationResult(
    U32 requestId,
    U32 generation,
    const Components::PayloadOperationKind& kind,
    const Components::PayloadOperationState& state,
    const std::string& literalEcho,
    U32 productId,
    U32 productBytes,
    const Components::ScienceProductSource& sourceKind,
    const std::string& sourcePath,
    U32 sourceCrc,
    U32 errorCode,
    bool duplicate
) {
    const Fw::String echo(literalEcho.c_str());
    const Fw::String path(sourcePath.c_str());
    this->operationResponseOut_out(0, requestId, generation, kind, state, echo,
                                  productId, productBytes, sourceKind, path, sourceCrc, errorCode);
    if (duplicate) {
        this->operationResponseOut_out(0, requestId, generation, kind, state, echo,
                                      productId, productBytes, sourceKind, path, sourceCrc, errorCode);
    }
}

void PayloadDriver_NeutronSim::setAvailability(bool available) {
    this->m_captureSlotAvailable = available;
    if (!this->isConnected_availabilityOut_OutputPort(0)) {
        return;
    }
    if (this->m_availabilityAnnounced && (this->m_announcedAvailable == available)) {
        return;
    }
    this->availabilityOut_out(0, available);
    this->m_availabilityAnnounced = true;
    this->m_announcedAvailable = available;
}

std::string PayloadDriver_NeutronSim::getSimRoot() {
    const char* root = std::getenv("NEUTRON_PAYLOAD_SIM_ROOT");
    if ((root == nullptr) || (root[0] == '\0')) {
        const std::string defaultDataset = std::string(DEFAULT_SIM_ROOT) + "/neutron_data.csv";
        if (::access(defaultDataset.c_str(), R_OK) == 0) {
            return DEFAULT_SIM_ROOT;
        }
        const std::string repoRootDataset = std::string(REPO_ROOT_SIM_ROOT) + "/neutron_data.csv";
        if (::access(repoRootDataset.c_str(), R_OK) == 0) {
            return REPO_ROOT_SIM_ROOT;
        }
        return DEFAULT_SIM_ROOT;
    }
    return root;
}

void PayloadDriver_NeutronSim::parseSummaryLine(const std::string& line, CaptureSummary& summary) {
    const std::size_t separator = line.find('=');
    if (separator == std::string::npos) {
        return;
    }
    const std::string key = line.substr(0, separator);
    std::string value = line.substr(separator + 1U);
    while (!value.empty() &&
           ((value.back() == '\n') || (value.back() == '\r') || (value.back() == ' ') || (value.back() == '\t'))) {
        value.pop_back();
    }
    if (key == "rows") {
        summary.rows = parseU32(value);
    } else if (key == "total_counts") {
        summary.totalCounts = parseU32(value);
    } else if (key == "saa_rows") {
        summary.saaRows = parseU32(value);
    } else if (key == "output_bytes") {
        summary.productBytes = parseU32(value);
    } else if (key == "output_path") {
        summary.outputPath = value;
    }
}

bool PayloadDriver_NeutronSim::publishLatestCapture(const std::string& outputPath) {
    struct stat info {};
    if ((::stat(outputPath.c_str(), &info) != 0) || !S_ISREG(info.st_mode) || (info.st_size <= 0)) {
        return false;
    }
    (void)::unlink(DEFAULT_LATEST_PAYLOAD);
    return (::symlink(outputPath.c_str(), DEFAULT_LATEST_PAYLOAD) == 0);
}

bool PayloadDriver_NeutronSim::computeFileCrc16(const std::string& outputPath, U32& crcOut) {
    std::FILE* file = std::fopen(outputPath.c_str(), "rb");
    if (file == nullptr) {
        return false;
    }
    U16 crc = 0xFFFFU;
    int value = 0;
    while ((value = std::fgetc(file)) != EOF) {
        crc ^= static_cast<U16>(static_cast<U8>(value)) << 8U;
        for (U8 bit = 0; bit < 8U; bit++) {
            crc = ((crc & 0x8000U) != 0U)
                ? static_cast<U16>((crc << 1U) ^ 0x1021U)
                : static_cast<U16>(crc << 1U);
        }
    }
    const bool readOk = !std::ferror(file);
    (void)std::fclose(file);
    if (!readOk) {
        return false;
    }
    crcOut = static_cast<U32>(crc);
    return true;
}

U32 PayloadDriver_NeutronSim::parseU32(const std::string& value) {
    char* end = nullptr;
    const unsigned long parsed = std::strtoul(value.c_str(), &end, 10);
    if ((end == value.c_str()) || (parsed > std::numeric_limits<U32>::max())) {
        return std::numeric_limits<U32>::max();
    }
    return static_cast<U32>(parsed);
}

}  // namespace Components
