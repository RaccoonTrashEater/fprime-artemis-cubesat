#pragma once
#include <cstring>

#include "LinkConstants.hpp"
namespace RadioLink {
struct Packet {
    uint8_t bytes[49] = {};
    uint8_t length = 0, to = 0, from = 0, network = 0, version = 0;
};
class Transport {
   public:
    virtual ~Transport() = default;
    virtual uint32_t now() = 0;
    virtual void pause(uint32_t ms) = 0;
    virtual bool send(const Packet&) = 0;
    virtual bool receive(Packet&) = 0;
    virtual void frame(const uint8_t*, uint16_t) = 0;
};
struct Counters {
    uint32_t tx = 0, rx = 0, retries = 0, timeouts = 0, drops = 0, duplicates = 0, reassemblyTimeouts = 0;
};
class LinkCore {
   public:
    explicit LinkCore(Transport& transport) : io(transport) {}
    Counters counters;
    void reset() {
        active = false;
        seen = false;
        length = 0;
    }
    void poll() {
        expire();
        Packet p;
        // Bound a pass so RX cannot starve shutdown or pending TX.
        for (unsigned i = 0; i < 16 && io.receive(p); ++i)
            process(p);
    }
    bool transmit(const uint8_t* data, uint16_t size, bool ackRequired = link_protocol::RF_TX_ACK_REQUIRED_CCSDS) {
        if (!data || !size || size > link_protocol::FRAME_MAX_PAYLOAD)
            return false;
        const uint8_t msg = nextMessage++, count = (size + 43) / 44;
        for (uint8_t segment = 0; segment < count; ++segment) {
            Packet p;
            address(p);
            const uint16_t offset = segment * 44;
            const uint8_t n = size - offset > 44 ? 44 : size - offset;
            p.length = n + 5;
            p.bytes[0] = 0xA5;
            p.bytes[1] = msg;
            p.bytes[2] = segment;
            p.bytes[3] = count;
            p.bytes[4] = n;
            std::memcpy(p.bytes + 5, data + offset, n);
            bool success = false;
            for (unsigned attempt = 0; attempt <= link_protocol::RF_ACK_RETRIES; ++attempt) {
                if (!io.send(p))
                    return false;
                ++counters.tx;
                if (!ackRequired) {
                    success = true;
                    break;
                }
                const uint32_t start = io.now();
                while (uint32_t(io.now() - start) < link_protocol::RF_ACK_TIMEOUT_MS) {
                    Packet rx;
                    if (io.receive(rx)) {
                        if (validHeader(rx) && rx.length == 5 && rx.bytes[0] == 0xA5 && rx.bytes[1] == msg &&
                            rx.bytes[2] == 0xFF && rx.bytes[3] == segment && rx.bytes[4] == 0) {
                            success = true;
                            break;
                        }
                        process(rx);
                    }
                    io.pause(1);
                }
                if (success)
                    break;
                ++counters.timeouts;
                if (attempt < link_protocol::RF_ACK_RETRIES)
                    ++counters.retries;
            }
            if (!success)
                return false;
            if (segment + 1 < count) {
                const uint32_t start = io.now();
                while (uint32_t(io.now() - start) < link_protocol::RF_INTER_SEGMENT_GAP_MS) {
                    poll();
                    io.pause(1);
                }
            }
        }
        return true;
    }

   private:
    Transport& io;
    uint8_t nextMessage = 0, message = 0, expected = 0, total = 0, lastMessage = 0;
    uint16_t length = 0;
    uint32_t lastTime = 0;
    bool active = false, seen = false;
    uint8_t buffer[link_protocol::FRAME_MAX_PAYLOAD] = {};
    static void address(Packet& p) {
        p.to = link_protocol::RF_REMOTE_ADDRESS;
        p.from = link_protocol::RF_LOCAL_ADDRESS;
        p.network = link_protocol::RF_NETWORK_ID;
        p.version = link_protocol::RF_PROTOCOL_VERSION;
    }
    static bool validHeader(const Packet& p) {
        return link_protocol::classifyRfHeader(p.to, p.from, p.network, p.version) ==
               link_protocol::RfHeaderStatus::ACCEPT;
    }
    void expire() {
        if (active && uint32_t(io.now() - lastTime) > link_protocol::RF_REASSEMBLY_TIMEOUT_MS) {
            active = false;
            length = 0;
            ++counters.reassemblyTimeouts;
        }
    }
    void ack(uint8_t msg, uint8_t segment) {
        if (!link_protocol::RF_RX_ACK_REQUIRED_CCSDS)
            return;
        Packet p;
        address(p);
        p.length = 5;
        p.bytes[0] = 0xA5;
        p.bytes[1] = msg;
        p.bytes[2] = 0xFF;
        p.bytes[3] = segment;
        p.bytes[4] = 0;
        if (io.send(p))
            ++counters.tx;
    }
    void process(const Packet& p) {
        expire();
        if (!validHeader(p) || p.length < 5 || p.length > 49 || p.bytes[0] != 0xA5) {
            ++counters.drops;
            return;
        }
        ++counters.rx;
        const uint8_t msg = p.bytes[1], seg = p.bytes[2], count = p.bytes[3], n = p.bytes[4];
        if (seg == 0xFF)
            return;
        if (!count || count > 5 || seg >= count || !n || n > 44 || p.length != 5 + n) {
            ++counters.drops;
            return;
        }
        if (!active && seen && msg == lastMessage) {
            ++counters.duplicates;
            ack(msg, seg);
            return;
        }
        if (active && msg == message && count == total && seg < expected) {
            ++counters.duplicates;
            ack(msg, seg);
            return;
        }
        if (!active || message != msg || total != count || expected != seg) {
            active = false;
            length = 0;
            if (seg != 0) {
                ++counters.drops;
                return;
            }
            active = true;
            message = msg;
            total = count;
            expected = 0;
        }
        if (length + n > sizeof(buffer)) {
            active = false;
            ++counters.drops;
            return;
        }
        std::memcpy(buffer + length, p.bytes + 5, n);
        length += n;
        ++expected;
        lastTime = io.now();
        ack(msg, seg);
        if (expected == total) {
            active = false;
            seen = true;
            lastMessage = msg;
            io.frame(buffer, length);
        }
    }
};
}  // namespace RadioLink
