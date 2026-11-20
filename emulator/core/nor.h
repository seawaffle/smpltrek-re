#ifndef SMPLTREK_EMULATOR_NOR_H
#define SMPLTREK_EMULATOR_NOR_H
#include <array>
#include <cstdint>
#include <unordered_map>
#include <vector>

// Generic 16 MiB, 24-bit-address SPI NOR profile. The identification and configuration bytes are those both
// devices of the unit returned (bench M1, step C1); the part's exact suffix is unknown.
class Nor {
    std::unordered_map<uint32_t, std::array<uint8_t, 4096>> pages;
    int command = -1;
    uint32_t address = 0, address_bytes = 0, position = 0;
    bool wel = false, ignored = false;
    std::vector<uint8_t> payload;
    struct Operation { int command = -1; uint32_t address = 0; std::vector<uint8_t> data; uint64_t end = UINT64_MAX; } operation;
    void store(uint32_t offset, uint8_t value);
public:
    uint64_t commands = 0, bytes_read = 0, programs = 0, erases = 0;
    uint8_t configuration = 0x07;   // answer to 15; device 0 of the unit reads 0F
    uint8_t at(uint32_t offset) const;
    void load(uint32_t offset, const uint8_t *data, uint32_t size);
    void advance(uint64_t cycle);
    uint8_t exchange(uint8_t byte, uint64_t cycle);
    void deselect(uint64_t cycle);
    uint32_t status() const { return (operation.command >= 0 ? 1 : 0) | (wel ? 2 : 0); }
};
#endif
