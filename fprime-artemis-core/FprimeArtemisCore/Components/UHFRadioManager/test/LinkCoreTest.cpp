#include <cassert>
#include <deque>
#include <iostream>
#include <vector>

#include "../LinkCore.hpp"
#include "../TestPacket.hpp"
using namespace RadioLink;
struct Fake : Transport {
    uint32_t time = 0;
    bool acknowledge = false, failSend = false;
    std::deque<Packet> incoming;
    std::vector<Packet> outgoing;
    std::vector<std::vector<uint8_t>> frames;
    uint32_t now() override {
        return time;
    }
    void pause(uint32_t ms) override {
        time += ms;
    }
    static Packet peer(Packet p) {
        p.to = link_protocol::RF_LOCAL_ADDRESS;
        p.from = link_protocol::RF_REMOTE_ADDRESS;
        p.network = link_protocol::RF_NETWORK_ID;
        p.version = link_protocol::RF_PROTOCOL_VERSION;
        return p;
    }
    bool send(const Packet& p) override {
        if (failSend)
            return false;
        outgoing.push_back(p);
        if (acknowledge && p.bytes[2] != 0xFF) {
            Packet ack = peer(p);
            ack.length = 5;
            ack.bytes[2] = 0xFF;
            ack.bytes[3] = p.bytes[2];
            ack.bytes[4] = 0;
            incoming.push_back(ack);
        }
        return true;
    }
    bool receive(Packet& p) override {
        if (incoming.empty())
            return false;
        p = incoming.front();
        incoming.pop_front();
        return true;
    }
    void frame(const uint8_t* p, uint16_t n) override {
        frames.emplace_back(p, p + n);
    }
};
int main() {
    uint8_t data[128];
    for (unsigned i = 0; i < 128; ++i)
        data[i] = i;
    Fake tx;
    LinkCore sender(tx);
    assert(sender.transmit(data, 128, false));
    assert(tx.outgoing.size() == 3);
    // Fixed legacy segment format: A5, msg-id, segment-index, segment-count, chunk-length.
    const uint8_t prefix[] = {0xA5, 0, 0, 3, 44, 0, 1, 2};
    assert(std::memcmp(tx.outgoing[0].bytes, prefix, sizeof(prefix)) == 0);
    for (unsigned i = 0; i < 44; ++i)
        assert(tx.outgoing[0].bytes[5 + i] == i);
    assert(tx.outgoing[0].to == link_protocol::RF_REMOTE_ADDRESS &&
           tx.outgoing[0].from == link_protocol::RF_LOCAL_ADDRESS);
    assert(tx.outgoing[0].network == link_protocol::RF_NETWORK_ID &&
           tx.outgoing[0].version == link_protocol::RF_PROTOCOL_VERSION);
    assert(tx.outgoing[0].length == 49 && tx.outgoing[2].length == 45);
    Fake rx;
    LinkCore receiver(rx);
    for (auto p : tx.outgoing)
        rx.incoming.push_back(Fake::peer(p));
    receiver.poll();
    assert(rx.frames.size() == 1);
    assert(rx.frames[0] == std::vector<uint8_t>(data, data + 128));
    for (auto p : tx.outgoing)
        rx.incoming.push_back(Fake::peer(p));
    receiver.poll();
    assert(rx.frames.size() == 1 && receiver.counters.duplicates == 3);
    Fake partial;
    LinkCore assembling(partial);
    partial.incoming.push_back(Fake::peer(tx.outgoing[0]));
    partial.incoming.push_back(Fake::peer(tx.outgoing[0]));
    partial.incoming.push_back(Fake::peer(tx.outgoing[1]));
    partial.incoming.push_back(Fake::peer(tx.outgoing[2]));
    assembling.poll();
    assert(partial.frames.size() == 1 && assembling.counters.duplicates == 1);
    Fake bench; LinkCore benchLink(bench);
    assert(benchLink.transmit(TEST_PACKET, sizeof(TEST_PACKET), false));
    assert(bench.outgoing.size()==1 && bench.outgoing[0].length==24);
    assert(bench.outgoing[0].bytes[4]==19);
    assert(std::memcmp(bench.outgoing[0].bytes+5,"ARTEMIS-RADIO-TEST\n",19)==0);
    // Lost ACK causes five sends: initial attempt and four retries.
    Fake noAck;
    LinkCore retry(noAck);
    assert(!retry.transmit(data, 1, true));
    assert(noAck.outgoing.size() == 5 && retry.counters.retries == 4 && retry.counters.timeouts == 5);
    Fake acked;
    acked.acknowledge = true;
    LinkCore success(acked);
    assert(success.transmit(data, 128, true));
    assert(success.counters.timeouts == 0 && acked.outgoing.size() == 3);
    // Reject network/address/version mismatches before any ACK or frame delivery.
    Fake bad;
    LinkCore reject(bad);
    Packet p = Fake::peer(tx.outgoing[0]);
    p.network ^= 1;
    bad.incoming.push_back(p);
    p = Fake::peer(tx.outgoing[0]);
    p.to ^= 1;
    bad.incoming.push_back(p);
    p = Fake::peer(tx.outgoing[0]);
    p.version ^= 1;
    bad.incoming.push_back(p);
    reject.poll();
    assert(reject.counters.drops == 3 && bad.outgoing.empty());
    Fake timeout;
    LinkCore timed(timeout);
    timeout.incoming.push_back(Fake::peer(tx.outgoing[0]));
    timed.poll();
    timeout.time = 501;
    timed.poll();
    assert(timed.counters.reassemblyTimeouts == 1);
    timeout.incoming.push_back(Fake::peer(tx.outgoing[1]));
    timed.poll();
    assert(timeout.frames.empty());
    // Timer wrap-around remains valid.
    timeout.time = 0xFFFFFF00U;
    timed.reset();
    timeout.incoming.push_back(Fake::peer(tx.outgoing[0]));
    timed.poll();
    timeout.time += 501;
    timed.poll();
    assert(timed.counters.reassemblyTimeouts == 2);
    // Validate packet lengths and message bounds before touching storage.
    assert(!sender.transmit(data, 0, false));
    assert(!sender.transmit(data, 221, false));
    Fake malformed;
    LinkCore bounded(malformed);
    p = Fake::peer(tx.outgoing[0]);
    p.bytes[4] = 45;
    malformed.incoming.push_back(p);
    bounded.poll();
    assert(bounded.counters.drops == 1);
    Fake failed;
    failed.failSend = true;
    LinkCore hardwareFail(failed);
    assert(!hardwareFail.transmit(data, 128, true));
    assert(hardwareFail.counters.timeouts == 0);
    // A mismatched ACK cannot falsely complete a transmission.
    Fake stale;
    Packet wrongAck = Fake::peer(tx.outgoing[0]);
    wrongAck.length = 5;
    wrongAck.bytes[1] = 99;
    wrongAck.bytes[2] = 0xFF;
    wrongAck.bytes[3] = 0;
    wrongAck.bytes[4] = 0;
    stale.incoming.push_back(wrongAck);
    LinkCore wrong(stale);
    assert(!wrong.transmit(data, 1, true));
    assert(wrong.counters.timeouts == 5);
    std::cout << "LinkCore: segmentation, ACK/retry, duplicate suppression, headers, timeout, wrap-around and bounds "
                 "passed\n";
}
