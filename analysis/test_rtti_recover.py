"""rtti_recover checks. Run: python3 -B -m unittest discover -s analysis -v

Needs the official updates in firmware/ (not tracked); skips when they are absent.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmtd2elf
import rtti_recover
import sonicware_integrity as integrity

SKIP = {"CyDrums_folder.zip"}  # plus the original ELZ_1 (legacy header layout), excluded below
CORPUS = [p for p in sorted((ROOT / "firmware").rglob("*.zip"))
          if p.name not in SKIP and not p.name.startswith("ELZ_1 v")]


def recover(path):
    (_, data), = list(integrity.inputs([path]))
    _, entry, sections = mmtd2elf.mmtd_sections(data)
    return rtti_recover.recover(sections, entry)


def primary(cls):
    return next((v for v in cls["vtables"] if v["offset_to_top"] == 0), None)


@unittest.skipUnless(CORPUS, "official updates not present in firmware/")
class RttiRecoverTests(unittest.TestCase):
    def test_structural_invariants_for_every_release(self):
        for path in CORPUS:
            with self.subTest(file=path.name):
                result = recover(path)
                self.assertEqual(result["abi"]["source"], "named __cxxabiv1 type_infos")
                self.assertEqual(set(result["abi"]["vptrs"]), {"class", "si", "vmi"})
                classes = {c["typeinfo"]: c for c in result["classes"]}
                self.assertGreater(len(classes), 150)
                for cls in classes.values():
                    for base in cls["bases"]:
                        self.assertTrue(base["resolved"], f"{cls['name']} base {base['typeinfo']:#x}")
                    # At most one primary vtable, and a derived primary vtable is never shorter than
                    # its primary base's (it extends the base's layout).
                    self.assertLessEqual(sum(v["offset_to_top"] == 0 for v in cls["vtables"]), 1)
                    table = primary(cls)
                    for base in cls["bases"]:
                        parent = primary(classes[base["typeinfo"]])
                        if table and parent and base["offset"] == 0 and not base["virtual"]:
                            self.assertGreaterEqual(len(table["entries"]), len(parent["entries"]), cls["name"])
                self.assertEqual(sum(s["name"] == "__cxa_pure_virtual_candidate" for s in result["symbols"]), 1)

    def test_known_3_2_174_classes(self):
        result = recover(ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip")
        by_name = {c["name"]: c for c in result["classes"]}
        self.assertEqual(len(by_name), 533)
        flash = by_name["HAL::FlashMemoryDriver"]
        self.assertEqual([b["name"] for b in flash["bases"]], ["HAL::SPIDriverDelegate", "Foundation::TaskHandler"])
        self.assertEqual(flash["typeinfo"], 0xC16CBF88)
        self.assertEqual([b["name"] for b in by_name["DialogConfirmation"]["bases"]], ["Dialog"])
        main = by_name["MainDelegate"]
        self.assertEqual(len(main["bases"]), 20)
        self.assertIn(("KeyPadDelegate", 40), [(b["name"], b["offset"]) for b in main["bases"]])
        pure = next(s for s in result["symbols"] if s["name"] == "__cxa_pure_virtual_candidate")
        self.assertEqual(pure["address"], 0xC16AC720)


if __name__ == "__main__":
    unittest.main()
