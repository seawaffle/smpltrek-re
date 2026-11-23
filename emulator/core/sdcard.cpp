#include "sdcard.h"
#include <algorithm>
#include <bit>
#include <stdexcept>
#include <string>

namespace {
void field(std::array<uint32_t, 4> &words, unsigned low, unsigned bits, uint32_t value) {
    for (unsigned bit = 0; bit < bits; bit++)
        if (value & (1u << bit)) words[(low + bit) / 32] |= 1u << ((low + bit) % 32);
}
void crc(std::array<uint32_t, 4> &words) {
    unsigned value = 0;
    for (int bit = 127; bit >= 8; bit--) {
        unsigned feedback = (value >> 6) ^ (words[bit / 32] >> (bit % 32));
        value = (value << 1) & 127;
        if (feedback & 1) value ^= 9;
    }
    words[0] |= value * 2 + 1;
}
}
void SdCard::load(const uint8_t *data, uint32_t size) {
    if (commands) throw std::runtime_error("SD backing must be loaded before card commands");
    if (!data || size < 2 * 1024 * 1024 || size > 1024 * 1024 * 1024 || !std::has_single_bit(size))
        throw std::runtime_error("SDSC backing must be a power-of-two size from 2 MiB to 1 GiB");
    image.assign(data, data + size); state = 0; width = 1; app = false;
    bytes_read = bytes_written = 0; trace.clear();
    cid = {0x0101ab00, 0x31100000, 0x534d504c, 0x45454d53}; crc(cid);
    csd = {};
    field(csd, 112, 8, 0x0e); field(csd, 96, 8, 0x32); // TAAC, 25 MHz transfer speed
    field(csd, 84, 12, 0x5b5); field(csd, 80, 4, 9);   // command classes, 512-byte read blocks
    uint32_t blocks = size / 512, mult = 0;
    while ((blocks >> (mult + 2)) > 4096) mult++;
    field(csd, 62, 12, (blocks >> (mult + 2)) - 1); field(csd, 47, 3, mult);
    field(csd, 46, 1, 1); field(csd, 39, 7, 127); // erase block fields; erase commands remain unsupported
    field(csd, 26, 3, 2); field(csd, 22, 4, 9); crc(csd);
}
uint32_t SdCard::status() const { return (state << 9) | ((state == 3 || state == 4) ? 256 : 0); }
SdReply SdCard::command(uint32_t index, uint32_t argument, uint64_t cycle) {
    SdReply out;
    if (image.empty()) return out;
    bool application = app && index != 0; app = false; commands++; // GO_IDLE always resets the protocol
    out.responds = index != 0; out.words[0] = status();
    auto illegal = [&] { out.words[0] = status() | (1u << 22); };
    if (application && index != 55) {
        switch (index) {
        case 41:
            if (state > 1) { illegal(); break; }
            if (argument & 0x00ff8000) state = 1;
            out.words[0] = 0x00ff8000 | (state == 1 ? 0x80000000 : 0); break;
        case 6:
            if (state != 4) { illegal(); break; }
            if (argument != 0 && argument != 2) throw std::runtime_error("unsupported SD bus width");
            width = argument == 2 ? 4 : 1; break;
        case 23: if (state != 4) illegal(); break; // pre-erase hint; single-block programming is supported
        case 51:
            if (state != 4) { illegal(); break; }
            out.data = {2, 5, 0, 0, 0, 0, 0, 0}; state = 5; break; // SCR: SD 2.0, 1/4-bit widths
        default: throw std::runtime_error("unsupported SD application command " + std::to_string(index));
        }
    } else switch (index) {
    case 0: state = 0; width = 1; break;
    case 1: case 5: out.responds = false; break; // SD memory card does not answer MMC/SDIO probes
    case 8:
        if ((argument & 0xf00) != 0x100) out.responds = false;
        else out.words[0] = argument & 0xfff;
        break;
    case 2:
        if (state != 1) { out.responds = false; break; }
        state = 2; out.long_response = true; out.words = cid; break;
    case 3:
        if (state != 2 && state != 3) { illegal(); break; }
        state = 3; out.words[0] = 0x10000 | status(); break; // fixed RCA = 1
    case 6: {
        if (state != 4) { illegal(); break; }
        // SWITCH_FUNC check/switch status: only default functions are supported.
        // High-speed and other requested nondefault functions report selection 0xF.
        out.data.resize(64); out.data[1] = 1;
        for (unsigned group = 1; group <= 6; group++) {
            out.data[15 - 2 * group] = 1; // function-0 support bitmap, big endian
            unsigned requested = (argument >> ((group - 1) * 4)) & 15;
            unsigned selected = requested == 0 || requested == 15 ? 0 : 15;
            out.data[16 - (group - 1) / 2] |= selected << ((group % 2) ? 0 : 4);
        }
        state = 5; break;
    }
    case 7:
        if (argument != 0x10000) { state = 3; out.responds = false; break; }
        if (state != 3 && state != 4) { illegal(); break; }
        state = 4; break;
    case 9: case 10:
        if (argument != 0x10000 || (state != 3 && state != 4)) { out.responds = false; break; }
        out.long_response = true; out.words = index == 9 ? csd : cid; break;
    case 12: state = 4; out.words[0] = status(); break;
    case 13:
        if (argument != 0x10000) out.responds = false;
        break;
    case 16:
        if (state != 4) illegal();
        else if (argument != 512) out.words[0] |= 1u << 29;
        break;
    case 17: case 18: case 24: case 25:
        if (state != 4) { illegal(); break; }
        if (argument & 511) { out.words[0] |= 1u << 30; break; }
        if (uint64_t(argument) + 512 > image.size()) { out.words[0] |= 1u << 31; break; }
        out.address = argument; out.write = index == 24 || index == 25;
        out.multiple = index == 18 || index == 25; out.data.resize(512);
        if (!out.write) std::copy_n(image.begin() + argument, 512, out.data.begin());
        state = out.write ? 6 : 5; break;
    case 23: case 58: illegal(); break;
    case 55: // The RCA is 0 until CMD3 publishes one (idle, ready and ident); a card answers no other.
        if (argument >> 16 != (state < 3 ? 0u : 1u)) { out.responds = false; break; }
        app = true; out.words[0] |= 32; break;
    default: throw std::runtime_error("unsupported SD command " + std::to_string(index));
    }
    trace.push_back({cycle, index + (application && index != 55 ? 64u : 0u), argument, out.words[0], state});
    if (trace.size() > 128) trace.pop_front();
    return out;
}
void SdCard::prepare_blocks(SdReply &reply, uint32_t count) {
    if (!count || uint64_t(reply.address) + uint64_t(count) * 512 > image.size())
        throw std::runtime_error("SD multiblock range exceeds private media");
    reply.data.resize(count * 512);
    if (!reply.write) std::copy_n(image.begin() + reply.address, reply.data.size(), reply.data.begin());
}
void SdCard::finish(const SdReply &reply, uint32_t offset, uint32_t size) {
    if (reply.write) {
        std::copy_n(reply.data.begin() + offset, size, image.begin() + reply.address + offset);
        bytes_written += size;
    } else bytes_read += size;
    state = reply.multiple ? (reply.write ? 6 : 5) : 4;
}
