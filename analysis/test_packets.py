"""packets and init_data checks. Run: python3 -B -m unittest discover -s analysis -v

The corpus tests need the official updates in firmware/ (not tracked) and skip when they are absent.
"""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import init_data
import memory_map
import packets

SMPLTREK = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"
LOFI = ROOT / "firmware/lofi12/Lofi-12XT_v1.5.205.zip"


def image(*packets_words):
    """memory_map.Image of consecutive 8-word fetch packets at 0x1000."""
    data = b"".join(struct.pack("<8I", *words) for words in packets_words)
    return memory_map.Image([(0x1000, data)])


class FetchPacketTests(unittest.TestCase):
    def test_no_header_uses_bit_0_of_each_word(self):
        img = image([1, 0, 1, 1, 0, 0, 0, 0])
        units = packets.fetch_packet(img, 0x1004)
        self.assertEqual([(a, s) for a, s, _ in units], [(0x1000 + 4 * i, 4) for i in range(8)])
        self.assertEqual([p for _, _, p in units], [1, 0, 1, 1, 0, 0, 0, 0])
        self.assertIsNone(packets.header_of(img, 0x1000))

    def test_header_layout_and_p_bits(self):
        # word 1 compact (layout bit 22); half-word p-bits: hw2 = 1, hw3 = 0; 32-bit words keep bit 0.
        header = 0xE0000000 | (1 << 22) | (1 << 2)
        img = image([1, 0, 0, 0, 1, 0, 0, header])
        units = packets.fetch_packet(img, 0x1000)
        self.assertEqual([(a, s, p) for a, s, p in units][:4],
                         [(0x1000, 4, 1), (0x1004, 2, 1), (0x1006, 2, 0), (0x1008, 4, 0)])
        self.assertEqual(len(units), 8)  # 6 words + 2 halves; the header word is not an instruction

    def test_prot_bit(self):
        self.assertTrue(packets.protected(0xE0100000))
        self.assertFalse(packets.protected(0xE0000000))
        self.assertFalse(packets.protected(None))

    def test_execute_packet_crosses_fetch_packets(self):
        img = image([0, 0, 0, 0, 0, 0, 0, 1], [0, 0, 0, 0, 0, 0, 0, 0])
        eps = packets.execute_packets(img, 0x1018, 0x1024)
        self.assertEqual(eps[0], [0x1018])
        self.assertEqual(eps[1], [0x101C, 0x1020])


# The corpus tests decode code with tools/tic6x objdump (tools/toolchain/build_tic6x_binutils.sh).
OBJDUMP_OK = (Path(__file__).resolve().parents[1] / "tools/tic6x/bin/tic6x-elf-objdump").exists()


@unittest.skipUnless(SMPLTREK.exists() and LOFI.exists() and OBJDUMP_OK, "official updates not present in firmware/ (or tools/tic6x objdump missing)")
class CorpusTests(unittest.TestCase):
    def test_lofi_panel_priority_is_set_in_the_call_packet(self):
        name, entry, sections, img = packets.load(LOFI)
        text = packets.listing(sections, entry)
        self.assertEqual(packets.call_sites(text, 0xC2C5C7F0), [0xC2BACE1C])
        eps, k = packets.around(img, 0xC2BACE1C, 0, 0)
        self.assertEqual(eps[k], [0xC2BACE18, 0xC2BACE1C, 0xC2BACE20, 0xC2BACE22, 0xC2BACE24])
        self.assertEqual(text[0xC2BACE24], "mvk .L2 12,b4")

    def test_smpltrek_usb_start_sets_a4_in_delay_slots_after_a_header(self):
        name, entry, sections, img = packets.load(SMPLTREK)
        eps, k = packets.around(img, 0xC168EFF4, 0, 3)
        self.assertEqual([e[0] for e in eps], [0xC168EFF4, 0xC168EFF8, 0xC168F000, 0xC168F004])

    def test_smpltrek_power_manager_poll_packet_is_protected(self):
        name, entry, sections, img = packets.load(SMPLTREK)
        self.assertEqual(packets.header_of(img, 0xC1646E80), 0xE0100000)
        self.assertTrue(packets.protected(packets.header_of(img, 0xC1646E80)))
        self.assertFalse(packets.protected(packets.header_of(img, 0xC1646EC0)))

    def test_smpltrek_static_tasks(self):
        data = init_data.InitData(SMPLTREK)
        tasks = data.tasks()
        self.assertEqual(len(tasks), 10)
        self.assertEqual(tasks[0][0], 0xC16E1790)
        self.assertEqual({w[10] for _, w in tasks[:9]}, {0xC168EE40})
        self.assertEqual([init_data.signed(w[2]) for _, w in tasks], [-1] * 5 + [3] + [-1] * 3 + [0])
        handles = data.handles(0xC16F3320, [tasks[0][0]])
        self.assertEqual(handles[0xC16E1790], [1356])
        self.assertEqual(data.word(0xC16ECF18), 1000)  # g_clock_timer_period, initialised by the copy table


if __name__ == "__main__":
    unittest.main()
