#ifndef SMPLTREK_EMULATOR_SDCARD_H
#define SMPLTREK_EMULATOR_SDCARD_H
#include <array>
#include <cstdint>
#include <deque>
#include <vector>

struct SdReply {
    bool responds = false, long_response = false, write = false, multiple = false;
    std::array<uint32_t, 4> words{}; // R2 bits 127:0, least-significant word first; R1/R3/R6/R7 in word 0.
    std::vector<uint8_t> data;
    uint32_t address = 0;
};
struct SdCommand { uint64_t cycle; uint32_t command, argument, response, state, responds, long_response; };
// An explicitly limited SD 2.0 standard-capacity card. Native SD mode, byte addressing.
class SdCard {
    bool app = false;
    std::array<uint32_t, 4> cid{}, csd{};
    uint32_t status() const;
public:
    std::vector<uint8_t> image;
    uint32_t state = 0, width = 1;
    uint64_t commands = 0, bytes_read = 0, bytes_written = 0;
    static constexpr size_t TRACE = 65536;
    std::deque<SdCommand> trace;     // the latest TRACE commands, oldest first
    uint64_t logged = 0;             // commands ever added to trace
    void load(const uint8_t *data, uint32_t size);
    SdReply command(uint32_t index, uint32_t argument, uint64_t cycle);
    void prepare_blocks(SdReply &reply, uint32_t count);
    void finish(const SdReply &reply, uint32_t offset, uint32_t size);
};
#endif
