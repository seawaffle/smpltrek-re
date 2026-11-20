#include "nor.h"
#include <cstdio>
#include <stdexcept>

uint8_t Nor::at(uint32_t offset) const {
    auto page = pages.find((offset & 0xffffff) / 4096);
    return page == pages.end() ? 255 : page->second[offset & 4095];
}
void Nor::store(uint32_t offset, uint8_t value) {
    offset &= 0xffffff;
    auto [page, inserted] = pages.try_emplace(offset / 4096);
    if (inserted) page->second.fill(255);
    page->second[offset & 4095] = value;
}
void Nor::load(uint32_t offset, const uint8_t *data, uint32_t size) {
    if (uint64_t(offset) + size > 0x1000000) throw std::runtime_error("SPI NOR backing range exceeds 16 MiB");
    if (command >= 0 || operation.command >= 0) throw std::runtime_error("SPI NOR backing load during a transaction");
    for (uint32_t i = 0; i < size; i++) if (data[i] != 255 || at(offset + i) != 255) store(offset + i, data[i]);
}
void Nor::advance(uint64_t cycle) {
    if (operation.command < 0 || cycle < operation.end) return;
    if (operation.command == 2) {
        uint32_t page = operation.address & ~255u;
        for (uint32_t i = 0; i < operation.data.size(); i++) {
            uint32_t target = page | ((operation.address + i) & 255);
            store(target, at(target) & operation.data[i]);
        }
        programs++;
    } else {
        uint32_t length = operation.command == 0x20 ? 4096 : operation.command == 0x52 ? 32768 : 65536;
        uint32_t begin = operation.address & ~(length - 1);
        for (uint32_t offset = begin; offset < begin + length; offset += 4096) pages.erase(offset / 4096);
        erases++;
    }
    operation = Operation{}; wel = false;
}
uint8_t Nor::exchange(uint8_t byte, uint64_t cycle) {
    advance(cycle);
    if (command < 0) {
        switch (byte) {
        case 3: case 5: case 6: case 4: case 2: case 0x20: case 0x52: case 0xd8: case 0x9f: case 0x15: break;
        default: {
            char text[100]; std::snprintf(text, sizeof text, "unimplemented SPI NOR command 0x%02x", byte);
            throw std::runtime_error(text);
        }
        }
        command = byte; address = address_bytes = position = 0; payload.clear(); commands++;
        ignored = operation.command >= 0 && command != 5;
        return 255;
    }
    if (ignored) return 255;
    if (command == 5) return uint8_t(status());
    if (command == 0x15) return configuration;
    if (command == 0x9f) { constexpr uint8_t id[] = {0xc2, 0x20, 0x18}; return id[position++ % 3]; }
    if (command == 6 || command == 4) { position++; return 255; } // extra clocks invalidate WREN/WRDI
    if (address_bytes < 3) { address = (address << 8) | byte; address_bytes++; return 255; }
    if (command == 3) { bytes_read++; return at(address + position++); }
    if (command == 2) {
        if (payload.size() == 256) throw std::runtime_error("SPI NOR page program longer than 256 bytes is not implemented");
        payload.push_back(byte);
    } else position++; // erase requires CS rising immediately after its 24-bit address
    return 255;
}
void Nor::deselect(uint64_t cycle) {
    advance(cycle);
    if (command >= 0 && !ignored) {
        if (command == 6 && !position) wel = true;
        else if (command == 4 && !position) wel = false;
        else if (wel && !position && address_bytes == 3 && (command == 2 || command == 0x20 || command == 0x52 || command == 0xd8)) {
            if (command != 2 || !payload.empty()) {
                // Deterministic functional profile, not measured device program/erase timings.
                uint64_t latency = command == 2 ? 372000 : command == 0x20 ? 18600000 : command == 0x52 ? 74400000 : 148800000;
                operation = Operation{command, address, payload, cycle + latency};
            }
        }
    }
    command = -1; payload.clear(); ignored = false;
}
