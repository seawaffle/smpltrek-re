"""mmtd2elf checks. Run: python3 -B -m unittest discover -s analysis -v

Needs the official updates in firmware/ (not tracked); skips when they are absent.
"""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmtd2elf
import sonicware_integrity as integrity

SKIP = {"CyDrums_folder.zip"}  # plus the original ELZ_1 (legacy header layout), excluded below


def corpus():
    return [p for p in sorted((ROOT / "firmware").rglob("*.zip"))
            if p.name not in SKIP and not p.name.startswith("ELZ_1 v")]


@unittest.skipUnless(corpus(), "official updates not present in firmware/")
class Mmtd2ElfTests(unittest.TestCase):
    def test_sections_round_trip_for_every_release(self):
        for path in corpus():
            for name, data in integrity.inputs([path]):
                with self.subTest(file=name):
                    _, entry, sections = mmtd2elf.mmtd_sections(data)
                    exec_indices = {i for i, (a, d) in enumerate(sections) if a <= entry < a + len(d)}
                    self.assertEqual(len(exec_indices), 1)
                    elf = mmtd2elf.build_elf(entry, sections, exec_indices)
                    self.assertEqual(elf[:4], b"\x7fELF")
                    machine, = struct.unpack_from("<H", elf, 18)
                    elf_entry, = struct.unpack_from("<I", elf, 24)
                    shoff, = struct.unpack_from("<I", elf, 32)
                    phnum, shnum = struct.unpack_from("<H", elf, 44)[0], struct.unpack_from("<H", elf, 48)[0]
                    self.assertEqual((machine, elf_entry, phnum, shnum),
                                     (mmtd2elf.EM_TI_C6000, entry, len(sections), len(sections) + 4))
                    for i, (address, payload) in enumerate(sections):
                        fields = struct.unpack_from("<10I", elf, shoff + 40 * (i + 1))
                        self.assertEqual((fields[3], fields[5]), (address, len(payload)))
                        self.assertEqual(elf[fields[4]:fields[4] + fields[5]], payload)
                        self.assertEqual(bool(fields[2] & mmtd2elf.SHF_EXECINSTR), i in exec_indices)

    def test_segments_only_variant_has_no_section_headers(self):
        (_, data), = list(integrity.inputs([ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"]))
        _, entry, sections = mmtd2elf.mmtd_sections(data)
        elf = mmtd2elf.build_segments_only_elf(entry, sections, {3})
        shoff, = struct.unpack_from("<I", elf, 32)
        phnum, shnum = struct.unpack_from("<H", elf, 44)[0], struct.unpack_from("<H", elf, 48)[0]
        self.assertEqual((shoff, shnum, phnum), (0, 0, len(sections)))
        for i, (address, payload) in enumerate(sections):
            _, offset, vaddr, _, filesz, _, flags, _ = struct.unpack_from("<8I", elf, 52 + 32 * i)
            self.assertEqual((vaddr, filesz), (address, len(payload)))
            self.assertEqual(elf[offset:offset + filesz], payload)
            self.assertEqual(bool(flags & mmtd2elf.PF_X), i == 3)

    def test_known_3_2_174_layout(self):
        path = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"
        (_, data), = list(integrity.inputs([path]))
        version, entry, sections = mmtd2elf.mmtd_sections(data)
        self.assertEqual((version, entry, len(sections)), ((3, 2, 174), 0xC1694580, 7))
        self.assertEqual((sections[3][0], len(sections[3][1])), (0xC1505400, 0x1A7F20))


if __name__ == "__main__":
    unittest.main()
