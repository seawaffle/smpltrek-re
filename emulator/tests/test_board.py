import shutil
import struct
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from cpu import CPU, CoreFault
from ir import Instruction, instruction


@unittest.skipUnless(shutil.which("g++"), "host g++ required")
class Board(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="smpltrek-board-")
        cls.work = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def machine(self, texts=None):
        cpu = CPU(self.work, decode=False)
        cpu.enable_board()
        cpu.map(0x1000, 4096, 7)
        if texts is None:
            rows = [(0x1000, "b .S1 00001000", 0x1004), (0x1004, "nop 5", 0x1008)]
        else:
            texts = [*texts, "b .S2 b3", "nop 5"]
            rows = [(0x1000 + i * 4, text, 0x1004 + i * 4) for i, text in enumerate(texts)]
        for address, text, following in rows:
            compiled = (Instruction * 1)(instruction(address, text))
            cpu.install(address, following, False, address & ~31, 32, compiled)
        cpu.reset(0x1000, return_address=None if texts is None else 0xdead0000)
        return cpu

    @staticmethod
    def get(cpu, address):
        return struct.unpack("<I", cpu.read(address, 4))[0]

    @staticmethod
    def put(cpu, address, value):
        cpu.write(address, struct.pack("<I", value))

    def test_interrupt_mux_event_latches_masks_and_clear(self):
        with self.machine() as cpu:
            self.assertEqual(self.get(cpu, 0x01800104), 0x07060504)
            self.put(cpu, 0x01800024, 1 << 4)  # event 36
            self.assertEqual(self.get(cpu, 0x01800004), 1 << 4)
            self.assertEqual(self.get(cpu, 0x018000a4), 0)
            self.put(cpu, 0x01800084, 0xffffffef)
            self.assertEqual(self.get(cpu, 0x018000a4), 1 << 4)
            self.put(cpu, 0x01800044, 1 << 4)
            self.assertEqual(self.get(cpu, 0x01800004), 0)

    def test_mmio_capture_keeps_whole_sequences_folds_polls_and_filters(self):
        program = ["stw .D1T1 a5,*a4", "ldw .D1T1 *a4,a6", "nop 4", "ldw .D1T1 *a4,a6", "nop 4", "ldw .D1T1 *a4,a6",
                   "nop 4", "stw .D1T1 a5,*a7", "stw .D1T1 a8,*a4", "ldw .D1T1 *a4,a6", "nop 4"]
        with self.machine(program) as cpu:
            self.configure_i2c(cpu, pins=False)
            cpu.capture_start([(0x01c22000, 0x01c22004)])                # ICOAR only: the ICSAR store is outside
            for register, value in (("a4", 0x01c22000), ("a5", 0x55), ("a7", 0x01c2201c), ("a8", 0x66)):
                cpu.set_register(register, value)
            self.assertEqual(cpu.run(200)["status"], "returned")
            rows = cpu.capture_take(stop=True)
            self.assertEqual([(row["write"], row["value"], row["repeat"], row["pc"]) for row in rows],
                             [(True, 0x55, 1, 0x1000), (False, 0x55, 1, 0x1004), (False, 0x55, 1, 0x100c),
                              (False, 0x55, 1, 0x1014), (True, 0x66, 1, 0x1020), (False, 0x66, 1, 0x1024)])
            self.assertEqual(cpu.capture_take(), [])
        with self.machine(["stw .D1T1 a5,*a4", "ldw .D1T1 *a4,a6", "nop 4", "b .S1 00001004", "nop 5"]) as cpu:
            self.configure_i2c(cpu, pins=False)
            cpu.capture_start([(0x01c22000, 0x01c22004)])
            cpu.set_register("a4", 0x01c22000); cpu.set_register("a5", 0x22)
            cpu.run(5000)                                                # a poll: the same PC reading the same value
            rows = cpu.capture_take(stop=True)
            self.assertEqual(len(rows), 2)
            self.assertGreater(rows[1]["repeat"], 100)
            cpu.capture_start([(0x01c22000, 0x01c22004)], writes_only=True)
            cpu.run(1000)
            self.assertEqual(cpu.capture_take(stop=True), [])            # reads only: nothing kept
        with self.machine(["stw .D1T1 a5,*a4", "b .S1 00001000", "nop 5"]) as cpu:
            self.configure_i2c(cpu, pins=False)
            cpu.capture_start([(0x01c22000, 0x01c22004)], limit=4)       # a store every loop, never taken
            cpu.set_register("a4", 0x01c22000); cpu.set_register("a5", 0x22)
            cpu.run(1000)
            with self.assertRaisesRegex(RuntimeError, "dropped"):
                cpu.capture_take(stop=True)

    def test_stores_to_the_empty_emifa_chip_select_are_dropped_and_counted(self):
        # M1 bench I6 on the unit: three STW of 0 at 0x4630314e (so 0x4630314c), +4 and +8 completed with no
        # stall, exception or event flag. What a read returns there was not consistent, so reads still stop.
        with self.machine(["stw .D1T1 a5,*a4", "stw .D1T1 a5,*+a4(4)", "stb .D1T1 a5,*+a4(8)"]) as cpu:
            cpu.set_register("a4", 0x4630314e)
            self.assertEqual(cpu.run(100)["status"], "returned")
            self.assertEqual(cpu.emifa_state(), dict(stores_dropped=3, last_address=0x46303156, last_pc=0x1008))
            with self.assertRaisesRegex(ValueError, "unmapped"):
                cpu.write(0x4630314c, bytes(4))
        with self.machine(["ldw .D1T1 *a4,a5", "nop 4"]) as cpu:
            cpu.set_register("a4", 0x4630314c)
            with self.assertRaisesRegex(CoreFault, "unmapped"):
                cpu.run(100)
        for address in (0x3ffffffc, 0x60000000):
            with self.subTest(address=hex(address)), self.machine(["stw .D1T1 a5,*a4"]) as cpu:
                cpu.set_register("a4", address)
                with self.assertRaisesRegex(CoreFault, "unmapped"):
                    cpu.run(100)
        # RAM cannot sit in the range: a store would otherwise be kept or dropped depending on the path taken.
        with self.machine(["nop 1"]) as cpu:
            for address, size in ((0x40000000, 4096), (0x5ffff000, 4096), (0x3ffff000, 8192)):
                with self.assertRaisesRegex(ValueError, "EMIFA range"):
                    cpu.map(address, size, 3)
            cpu.map(0x3ffff000, 4096, 3)
            cpu.map(0x60000000, 4096, 3)
        with CPU(self.work, decode=False) as cpu:
            cpu.map(0x40000000, 4096, 3)
            with self.assertRaisesRegex(ValueError, "EMIFA range"):
                cpu.enable_board()
        # Enabling the board again starts the count afresh, as it does the other access counters.
        with self.machine(["stw .D1T1 a5,*a4"]) as cpu:
            cpu.set_register("a4", 0x40000000)
            cpu.run(100)
            self.assertEqual(cpu.emifa_state()["stores_dropped"], 1)
            cpu.enable_board()
            self.assertEqual(cpu.emifa_state(), dict(stores_dropped=0, last_address=0, last_pc=0))

    def test_cache_commands_complete_and_unknown_registers_remain_errors(self):
        with self.machine() as cpu:
            # The state the bootloader leaves, as read on the unit (M1 bench B1); L2CFG's identity bits stay.
            self.assertEqual([self.get(cpu, 0x01840000 + offset) for offset in (0, 0x20, 0x40)], [0x01010000, 4, 3])
            self.assertEqual([self.get(cpu, 0x01848000 + index * 4) for index in (17, 128, *range(192, 200))], [1, 1, 1, 1, 1, 1, 0, 0, 0, 1])
            self.put(cpu, 0x01840000, 0xffffffff)
            self.assertEqual(self.get(cpu, 0x01840000), 0x01010007)
            self.put(cpu, 0x01844010, 0xc2100000)
            self.put(cpu, 0x01844014, 1024)
            self.assertEqual(self.get(cpu, 0x01844010), 0xc2100000)
            self.assertEqual(self.get(cpu, 0x01844014), 0)
            self.put(cpu, 0x01848300, 0xffffffff)
            self.assertEqual(self.get(cpu, 0x01848300), 9)
            with self.assertRaisesRegex(ValueError, "unimplemented MMIO"):
                self.get(cpu, 0x01841008)
            self.assertEqual(self.get(cpu, 0xb0000000), 0x40311b1f)
            self.put(cpu, 0xb0000000, 0)
            self.assertEqual(self.get(cpu, 0xb0000000), 0x40311b1f)
            self.assertEqual(self.get(cpu, 0xb0000004), 0x40000004)

    def test_psc_commits_module_states_only_after_domain_transition(self):
        with self.machine() as cpu:
            for base in (0x01c10000, 0x01e27000):
                self.assertEqual(self.get(cpu, base + 0x80c) & 63, 0)
                self.put(cpu, base + 0xa0c, 3)
                self.assertEqual(self.get(cpu, base + 0x80c) & 63, 0)
                self.put(cpu, base + 0x120, 1)
                self.assertEqual(self.get(cpu, base + 0x128), 1)
                cpu.run(15)
                self.assertEqual(self.get(cpu, base + 0x128), 1)
                cpu.run(1)
                self.assertEqual(self.get(cpu, base + 0x128), 0)
                self.assertEqual(self.get(cpu, base + 0x80c), 0x1f03)
                self.put(cpu, base + 0xa0c, 2)
                self.put(cpu, base + 0x120, 1)
                cpu.run(16)
                self.assertEqual(self.get(cpu, base + 0x80c), 0xf02)

    def enable_module(self, cpu, base, module):
        self.put(cpu, base + 0xa00 + module * 4, 3)
        self.put(cpu, base + 0x120, 1)
        cpu.run(16)

    def configure_mmcsd(self, cpu, rate=0):
        self.enable_module(cpu, 0x01c10000, 5)
        self.put(cpu, 0x01c14148, 0x88222222)
        base = 0x01c40000
        self.put(cpu, base, 3)
        self.put(cpu, base + 4, 0x100 | rate)
        self.put(cpu, base + 0x14, 7)
        self.put(cpu, base, 0)
        return base

    def sd_command(self, cpu, base, index, argument=0, flags=0x200):
        self.get(cpu, base + 8)
        self.put(cpu, base + 0x34, argument)
        self.put(cpu, base + 0x30, index | flags)
        clocks = 48 + (80 if flags & 0x4000 else 0)
        if flags & 0x600:
            clocks += 144 if (flags & 0x600) == 0x400 else 56
        cpu.run(clocks * 4)
        status = self.get(cpu, base + 8)
        self.assertTrue(status & 4)
        self.assertFalse(status & 0xf8)
        return self.get(cpu, base + 0x44)

    def identify_sd(self, cpu):
        base = self.configure_mmcsd(cpu)
        self.sd_command(cpu, base, 0, flags=0x4000)
        self.sd_command(cpu, base, 55)
        self.sd_command(cpu, base, 55)
        self.sd_command(cpu, base, 0, flags=0x4000)  # CMD0 also resets an outstanding APP_CMD prefix
        self.assertEqual(self.sd_command(cpu, base, 8, 0x1aa), 0x1aa)
        self.assertEqual((self.get(cpu, base + 0x40) >> 16) & 255, 0x13)  # R7 CRC7 + end bit
        self.assertTrue(self.sd_command(cpu, base, 55) & 32)
        self.assertEqual(self.sd_command(cpu, base, 41, 0x40ff8000, 0x600), 0x80ff8000)
        self.assertEqual(self.get(cpu, base + 0x50), 63)  # R3 has reserved index/CRC fields
        self.sd_command(cpu, base, 2, flags=0x400)
        self.assertEqual(self.sd_command(cpu, base, 3) >> 16, 1)
        self.sd_command(cpu, base, 9, 0x10000, 0x400)
        csd = sum(self.get(cpu, base + 0x38 + i * 4) << (i * 32) for i in range(4))
        self.assertEqual(csd >> 126, 0)  # CSD v1.0 describes SDSC, not a tiny/invalid SDHC card
        c_size, multiplier, block_bits = (csd >> 62) & 4095, (csd >> 47) & 7, (csd >> 80) & 15
        self.assertEqual((c_size + 1) * (1 << (multiplier + 2 + block_bits)), cpu.sd_state()["size"])
        self.sd_command(cpu, base, 7, 0x10000, 0x300)
        self.sd_command(cpu, base, 55, 0x10000)
        self.sd_command(cpu, base, 6, 2)
        self.put(cpu, base, 4)
        self.sd_command(cpu, base, 16, 512)
        self.assertEqual(self.sd_command(cpu, base, 13, 0x10000), 0x900)
        return base

    def test_sd_identification_clocked_pio_read_and_fifo_backpressure(self):
        snapshots = []
        expected = bytes((i * 29 + 7) & 255 for i in range(512))
        for eager in (False, True):
            with self.subTest(eager=eager), self.machine() as cpu:
                cpu.board_eager_polling(eager)
                image = bytearray(2 * 1024 * 1024); image[5 * 512:6 * 512] = expected
                cpu.sd_load(image); image[:] = bytes(len(image))
                base = self.identify_sd(cpu)
                self.put(cpu, base + 0x74, 1); self.put(cpu, base + 0x74, 4)
                self.put(cpu, base + 0x20, 1)
                self.sd_command(cpu, base, 17, 5 * 512, 0xa200)
                cpu.run(64 * 8 - 1)
                self.assertFalse(self.get(cpu, base + 8) & 0x400)
                cpu.run(1)
                self.assertTrue(self.get(cpu, base + 8) & 0x400)
                self.assertEqual(self.get(cpu, base + 8), 0)  # ISR polling must terminate despite a full FIFO
                self.assertTrue(self.get(cpu, base + 12) & 8)  # the data remains in the FIFO
                self.assertTrue(self.get(cpu, base + 12) & 2)  # full FIFO holds the card clock
                cpu.run(10000)  # no data loss while the CPU leaves a full FIFO unserviced
                output = bytearray()
                for chunk in range(8):
                    if chunk:
                        cpu.run(64 * 8)
                    for _ in range(16):
                        output += cpu.read(base + 0x28, 4)
                self.assertEqual(bytes(output), expected)
                cpu.run(17 * 4)
                self.assertEqual(self.get(cpu, base + 8) & 0x1001, 0x1001)
                self.assertEqual(self.get(cpu, base + 0x24), 0)
                self.assertEqual(cpu.sd_state()["bytes_read"], 512)
                self.assertEqual(cpu.sd_read(5 * 512, 512), expected)
                snapshots.append((cpu.state(), cpu.sd_state(), output))
        self.assertEqual(snapshots[0], snapshots[1])

    def test_sd_receive_interrupts_arrive_at_the_same_cycle_with_and_without_an_event_for_every_byte(self):
        # The MMCSD model asks for an event only at a received byte that changes something visible (the FIFO
        # reaches its threshold, a block ends, DRRDY has to be raised again after a status read); the bytes in
        # between are clocked in when it is next consulted. With eager polling it is consulted every cycle,
        # which is the reference. A block is read by interrupt with both FIFO thresholds, in steps of a few
        # cycles between which only the CPU's interrupt flags are looked at: the cycle of every interrupt, every
        # status word and every byte must be the same.
        import random
        expected = bytes((i * 29 + 7) & 255 for i in range(512))
        for threshold, control in ((32, 0), (64, 4)):
            traces = []
            for eager in (False, True):
                with self.subTest(threshold=threshold, eager=eager), self.machine() as cpu:
                    cpu.board_eager_polling(eager)
                    image = bytearray(2 * 1024 * 1024); image[5 * 512:6 * 512] = expected
                    cpu.sd_load(image)
                    base = self.identify_sd(cpu)
                    self.put(cpu, 0x01800104, 15)                  # MMCSD0 INT0 -> interrupt 4
                    self.put(cpu, 0x01800040, 1 << 15); cpu.set_register("ifr", 0)
                    self.put(cpu, base + 0x74, 1); self.put(cpu, base + 0x74, control)
                    self.put(cpu, base + 0x20, 1)
                    self.put(cpu, base + 0x10, 0x401)              # DRRDY and DATDNE interrupt
                    self.sd_command(cpu, base, 17, 5 * 512, 0xa200)
                    rng, trace, output, done = random.Random(threshold), [], bytearray(), False
                    for _ in range(4000):
                        state = cpu.run(rng.randrange(1, 30))
                        if not state["registers"]["ifr"] & (1 << 4):
                            continue
                        status = self.get(cpu, base + 8)
                        trace.append((state["cycles"], status))
                        self.put(cpu, 0x01800040, 1 << 15); cpu.set_register("ifr", 0)
                        done = done or bool(status & 1)
                        words = (512 - len(output)) // 4
                        if not done:                               # DRRDY: at least `threshold` bytes are waiting
                            # With the lower threshold the flag is sometimes only cleared, and the next byte must
                            # raise it again. (At 64 the FIFO is then full and nothing more would arrive.)
                            words = min(words, rng.choice((0, 1, 4, 8, 8) if threshold == 32 else (1, 4, 8, 16)))
                        if not (done or status & 0x400):
                            words = 0                              # an interrupt whose flag a later byte took back
                        for _ in range(words):
                            output += cpu.read(base + 0x28, 4)
                        if len(output) == 512 and done:
                            break
                    for _ in range(4000):                          # what no further interrupt announced: a full FIFO
                        if len(output) == 512:                     # whose flag was cleared stops the card clock
                            break
                        try:
                            output += cpu.read(base + 0x28, 4)
                        except ValueError:
                            cpu.run(16)
                    self.assertEqual(bytes(output), expected)
                    self.assertGreater(len(trace), 512 // threshold)
                    traces.append((trace, cpu.state(), cpu.sd_state()))
            self.assertEqual(traces[0], traces[1], threshold)

    def test_a_128_mib_card_reports_its_capacity_and_reads_its_last_block(self):
        expected = bytes((i * 31 + 3) & 255 for i in range(512))
        size = 128 * 1024 * 1024
        with self.machine() as cpu:
            image = bytearray(size); image[-512:] = expected
            cpu.sd_load(image); del image
            base = self.identify_sd(cpu)                    # checks the CSD capacity against the image
            self.put(cpu, base + 0x74, 1); self.put(cpu, base + 0x74, 4)
            self.put(cpu, base + 0x20, 1)
            self.sd_command(cpu, base, 17, size - 512, 0xa200)
            output = bytearray()
            for chunk in range(8):
                cpu.run(64 * 8)
                for _ in range(16):
                    output += cpu.read(base + 0x28, 4)
            self.assertEqual(bytes(output), expected)
            with self.assertRaisesRegex(ValueError, "1 GiB"):
                cpu.sd_load(bytes(3 * 1024 * 1024))         # not a power of two

    def test_sd_pio_write_commits_after_data_crc_and_programming(self):
        with self.machine() as cpu:
            cpu.sd_load(bytes(2 * 1024 * 1024))
            base = self.identify_sd(cpu)
            expected = bytes((255 - i) & 255 for i in range(512))
            self.put(cpu, base + 0x74, 1); self.put(cpu, base + 0x74, 6)
            self.put(cpu, base + 0x20, 1)
            self.sd_command(cpu, base, 24, 7 * 512, 0xaa00)
            for chunk in range(8):
                if chunk:  # the command helper has already observed/cleared the initial DXRDY
                    self.assertTrue(self.get(cpu, base + 8) & 0x200)
                for word in range(16):
                    self.put(cpu, base + 0x2c, int.from_bytes(expected[chunk * 64 + word * 4:chunk * 64 + word * 4 + 4], "little"))
                self.assertFalse(self.get(cpu, base + 8) & 0x200)
                cpu.run(64 * 8)
            self.assertEqual(cpu.sd_read(7 * 512, 512), bytes(512))
            self.assertEqual(cpu.sd_state()["state"], 7)
            self.assertEqual(self.get(cpu, base + 8) & 0x1001, 0x1000)
            cpu.run(49 * 4 - 1)
            self.assertEqual(cpu.sd_state()["bytes_written"], 0)
            cpu.run(1)
            self.assertTrue(self.get(cpu, base + 8) & 1)
            self.assertEqual(cpu.sd_state()["bytes_written"], 512)
            self.assertEqual(cpu.sd_read(7 * 512, 512), expected)
            self.assertEqual(self.sd_command(cpu, base, 13, 0x10000), 0x900)

    def test_sd_pinmux_timeout_address_errors_and_unsupported_commands(self):
        with self.machine() as cpu:
            cpu.sd_load(bytes(2 * 1024 * 1024))
            base = self.configure_mmcsd(cpu)
            self.put(cpu, 0x01c14148, 0)
            self.put(cpu, base + 0x30, 0x208)
            cpu.run((48 + 7) * 4)
            self.assertTrue(self.get(cpu, base + 8) & 16)
            self.assertEqual(cpu.sd_state()["commands"], 0)
            base = self.identify_sd(cpu)
            self.assertTrue(self.sd_command(cpu, base, 17, 1, 0xa200) & (1 << 30))
            self.assertTrue(self.sd_command(cpu, base, 24, 2 * 1024 * 1024, 0xaa00) & (1 << 31))
            with self.assertRaisesRegex(ValueError, "unsupported SD command 32"):
                self.put(cpu, base + 0x30, 0x220)
            with self.assertRaisesRegex(ValueError, "before execution"):
                cpu.sd_load(bytes(2 * 1024 * 1024))

    def test_cmd55_carries_rca_0_before_cmd3_and_the_published_rca_after(self):
        def times_out(cpu, base, index, argument):
            self.get(cpu, base + 8)
            self.put(cpu, base + 0x34, argument)
            self.put(cpu, base + 0x30, index | 0x200)
            cpu.run(128 * 4)
            return bool(self.get(cpu, base + 8) & 16)                     # TOUTRS: no response
        with self.machine() as cpu:
            cpu.sd_load(bytes(2 * 1024 * 1024))
            base = self.identify_sd(cpu)
            self.assertTrue(times_out(cpu, base, 55, 0))                  # transfer state: RCA 1 only
            self.assertTrue(self.sd_command(cpu, base, 55, 0x10000) & 32)
            self.sd_command(cpu, base, 0, flags=0x4000)                   # re-initialised: idle, RCA 0
            self.assertTrue(times_out(cpu, base, 55, 0x10000))
            self.sd_command(cpu, base, 8, 0x1aa)
            self.assertTrue(times_out(cpu, base, 55, 0x10000))
            self.assertTrue(self.sd_command(cpu, base, 55) & 32)
            self.assertEqual(self.sd_command(cpu, base, 41, 0x40ff8000, 0x600), 0x80ff8000)
            self.assertTrue(times_out(cpu, base, 55, 0x10000))            # ready
            self.sd_command(cpu, base, 2, flags=0x400)
            self.assertTrue(times_out(cpu, base, 55, 0x10000))            # ident
            self.assertEqual(self.sd_command(cpu, base, 3) >> 16, 1)
            self.assertTrue(times_out(cpu, base, 55, 0))                  # stand-by: the published RCA only
            self.assertTrue(self.sd_command(cpu, base, 55, 0x10000) & 32)
            log, following = cpu.sd_log()
            self.assertEqual(following, len(log))
            cmd55 = [(row["argument"], row["answered"]) for row in log if row["command"] == "CMD55"]
            self.assertIn((0, False), cmd55)
            self.assertIn((0x10000, True), cmd55)
            self.assertEqual(log[-1]["sequence"], len(log) - 1)
            self.assertEqual(cpu.sd_log(following), ([], following))

    def test_sd_dma_short_scr_flush_and_sector_write_match_across_slices(self):
        snapshots = []
        for step, eager in ((1, False), (10000, False), (10000, True)):
            with self.subTest(step=step, eager=eager), self.machine() as cpu:
                cpu.sd_load(bytes(2 * 1024 * 1024)); cpu.board_eager_polling(eager)
                base = self.identify_sd(cpu)
                self.enable_module(cpu, 0x01c10000, 0)
                cpu.map(0x4000, 8192, 3)
                expected = bytes((i * 17 + 3) & 255 for i in range(512))
                cpu.write(0x4000, expected)
                for channel, src, dst, count, indices, cindices, frames in (
                        (16, base + 0x28, 0x5000, 2, 0x40000, 0x80000, 1),
                        (17, 0x4000, base + 0x2c, 16, 4, 64, 8)):
                    words = [0x100004 | channel << 12, src, count << 16 | 4, dst, indices, 0xffff, cindices, frames]
                    for i, value in enumerate(words):
                        self.put(cpu, 0x01c04000 + channel * 32 + i * 4, value)
                self.put(cpu, 0x01c01030, 0x30000)
                self.put(cpu, base + 0x1c, 8); self.put(cpu, base + 0x20, 1)
                self.sd_command(cpu, base, 55, 0x10000)
                self.put(cpu, base + 0x74, 1); self.put(cpu, base + 0x74, 4)
                self.sd_command(cpu, base, 51, 0, 0x1a200)
                self.assertFalse(self.get(cpu, base + 0x30) & 0x10000)
                end = cpu.state()["cycles"] + 8 * 8 + 17 * 4
                while cpu.state()["cycles"] < end:
                    cpu.run(min(step, end - cpu.state()["cycles"]))
                self.assertEqual(cpu.read(0x5000, 8), b"\x02\x05" + bytes(6))
                self.assertTrue(self.get(cpu, 0x01c01068) & (1 << 16))
                self.assertTrue(self.get(cpu, base + 8) & 1)
                # CMD6 checks high-speed availability; this SDSC supports default functions only.
                for i, value in enumerate([0x110004, base + 0x28, 16 << 16 | 4, 0x5000,
                                            0x40000, 0xffff, 0x400000, 1]):
                    self.put(cpu, 0x01c04200 + i * 4, value)
                self.put(cpu, base + 0x1c, 64)
                self.sd_command(cpu, base, 6, 0x00fffff1, 0x1a200)
                end = cpu.state()["cycles"] + 64 * 8 + 17 * 4
                while cpu.state()["cycles"] < end:
                    cpu.run(min(step, end - cpu.state()["cycles"]))
                status = cpu.read(0x5000, 64)
                self.assertEqual(int.from_bytes(status[12:14], "big"), 1)  # default speed supported, high speed absent
                self.assertEqual(status[16] & 15, 15)  # requested function 1 cannot be selected
                self.put(cpu, base + 0x1c, 512)
                self.put(cpu, base + 0x74, 1); self.put(cpu, base + 0x74, 6)
                self.sd_command(cpu, base, 24, 9 * 512, 0x1aa00)
                end = cpu.state()["cycles"] + 512 * 8 + 49 * 4
                while cpu.state()["cycles"] < end:
                    cpu.run(min(step, end - cpu.state()["cycles"]))
                self.assertEqual(cpu.sd_read(9 * 512, 512), expected)
                self.assertEqual(self.get(cpu, 0x01c01068) & 0x30000, 0x30000)
                self.assertEqual(self.get(cpu, 0x01c01000) & 0x30000, 0)
                self.assertEqual(cpu.sd_state()["bytes_read"], 72)
                self.assertEqual(cpu.sd_state()["bytes_written"], 512)
                snapshots.append((cpu.state(), cpu.sd_state(), cpu.mmio_trace()))
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[0], snapshots[2])

    def test_sd_multiblock_dma_commits_each_block_and_stops_with_cmd12(self):
        snapshots = []
        for step, eager in ((1, False), (100000, False), (100000, True)):
            with self.subTest(step=step, eager=eager), self.machine() as cpu:
                cpu.sd_load(bytes(2 * 1024 * 1024)); cpu.board_eager_polling(eager)
                base = self.identify_sd(cpu)
                self.enable_module(cpu, 0x01c10000, 0)
                cpu.map(0x4000, 8192, 3)
                expected = bytes((i * 31 + i // 512) & 255 for i in range(1024))
                cpu.write(0x4000, expected)
                for channel, src, dst, indices, cindices in (
                        (16, base + 0x28, 0x5000, 0x40000, 0x400000),
                        (17, 0x4000, base + 0x2c, 4, 64)):
                    for i, value in enumerate([0x100004 | channel << 12, src, 16 << 16 | 4, dst,
                                                indices, 0xffff, cindices, 16]):
                        self.put(cpu, 0x01c04000 + channel * 32 + i * 4, value)
                self.put(cpu, 0x01c01030, 0x30000)
                self.put(cpu, base + 0x20, 2)
                self.put(cpu, base + 0x74, 1); self.put(cpu, base + 0x74, 6)
                self.sd_command(cpu, base, 25, 4 * 512, 0x1aa00)
                for block in range(2):
                    end = cpu.state()["cycles"] + 512 * 8 + 49 * 4
                    while cpu.state()["cycles"] < end:
                        cpu.run(min(step, end - cpu.state()["cycles"]))
                    self.assertEqual(cpu.sd_state()["bytes_written"], (block + 1) * 512)
                    self.assertEqual(cpu.sd_read(4 * 512, 1024), expected[:(block + 1) * 512] + bytes((1 - block) * 512))
                    self.assertEqual(self.get(cpu, base + 0x24), 1 - block)
                    self.assertEqual(bool(self.get(cpu, base + 8) & 1), bool(block))
                self.assertEqual(cpu.sd_state()["state"], 6)
                self.sd_command(cpu, base, 12, flags=0x300)
                self.assertEqual(cpu.sd_state()["state"], 4)
                self.put(cpu, base + 0x74, 1); self.put(cpu, base + 0x74, 4)
                self.sd_command(cpu, base, 18, 4 * 512, 0x1a200)
                end = cpu.state()["cycles"] + 2 * (512 * 8 + 17 * 4)
                while cpu.state()["cycles"] < end:
                    cpu.run(min(step, end - cpu.state()["cycles"]))
                self.assertEqual(cpu.read(0x5000, 1024), expected)
                self.assertEqual(cpu.sd_state()["bytes_read"], 1024)
                self.assertEqual(cpu.sd_state()["state"], 5)
                self.sd_command(cpu, base, 12, flags=0x300)
                self.assertEqual(cpu.sd_state()["state"], 4)
                snapshots.append((cpu.state(), cpu.sd_state(), cpu.mmio_trace()))
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[0], snapshots[2])

    def configure_i2c(self, cpu, pins=True):
        base = 0x01c22000
        if pins:
            self.put(cpu, 0x01c14130, 0x2200)
        self.put(cpu, base + 0x24, 0)
        self.put(cpu, base + 0x30, 2)
        self.put(cpu, base + 0xc, 35)
        self.put(cpu, base + 0x10, 35)
        self.put(cpu, base + 0x1c, 0x18)
        self.put(cpu, base + 0x2c, 0)
        self.put(cpu, base + 0x24, 0x20)
        return base

    def i2c_write(self, cpu, register, value):
        base = 0x01c22000
        self.put(cpu, base + 0x14, 2)
        cpu.write(base + 0x20, bytes([register]))
        self.put(cpu, base + 0x24, 0x2e20)
        cpu.run(33480)  # nine 100 kHz address/ACK clocks
        cpu.write(base + 0x20, bytes([value]))
        cpu.run(33480 * 2 + 3720)  # two data/ACK bytes, one modeled STOP clock

    def test_i2c_clocked_write_stop_irq_and_reset_values(self):
        with self.machine() as cpu:
            base = 0x01c22000
            self.assertEqual(self.get(cpu, base + 8), 0x410)
            self.assertEqual(self.get(cpu, base + 0x2c), 1)
            self.assertEqual(self.get(cpu, base + 0x34), 0x4415)
            self.assertEqual(self.get(cpu, base + 0x38), 6)
            self.configure_i2c(cpu)
            self.put(cpu, 0x01800104, 36)
            self.put(cpu, base + 4, 16)
            self.assertEqual(self.get(cpu, base + 0x28), 5)
            self.assertEqual(self.get(cpu, base + 0x28), 0)  # ISR must drain XRDY by reading ICIVR
            self.assertEqual(self.get(cpu, base + 8) & 16, 0)
            self.put(cpu, base + 4, 0x20)
            self.put(cpu, base + 0x14, 2)
            self.put(cpu, base + 0x20, 3)
            self.put(cpu, base + 0x24, 0x2e20)
            cpu.run(33479)
            self.assertEqual(self.get(cpu, base + 8) & 0x1010, 0x1000)
            self.assertTrue(self.get(cpu, base + 0x24) & 0x2000)
            cpu.run(1)
            self.assertFalse(self.get(cpu, base + 0x24) & 0x2000)
            self.assertTrue(self.get(cpu, base + 8) & 16)
            cpu.write(base + 0x20, b"\xa2")
            cpu.run(33480 * 2 - 1)
            self.assertEqual(cpu.codec_register(0, 3), 0x10)
            cpu.run(1)
            self.assertEqual(cpu.codec_register(0, 3), 0xa2)
            self.assertTrue(self.get(cpu, base + 8) & 0x1000)
            cpu.run(3720)
            self.assertEqual(self.get(cpu, base + 8) & 0x1020, 0x20)
            self.assertEqual(self.get(cpu, base + 0x24) & 0x2c00, 0)
            self.assertEqual(self.get(cpu, base + 0x14), 2)  # internal countdown leaves ICCNT unchanged
            self.assertEqual(cpu.state()["registers"]["ifr"] & 16, 16)
            self.assertEqual(cpu.read(base + 0x29, 1), b"\0")  # high byte cannot acknowledge ICIVR
            self.assertEqual(self.get(cpu, base + 0x28), 6)
            self.assertEqual(self.get(cpu, base + 0x28), 0)
            state = cpu.codec_state()
            self.assertEqual((state["bytes_sent"], state["starts"], state["stops"], state["nacks"]), (2, 1, 1, 0))
            self.assertEqual(state["trace"], [dict(cycles=100440, page=0, register=3, value=0xa2)])

    def test_i2c_nack_missing_peer_pins_status_w1c_and_vector_priority(self):
        for pins, address in ((True, 0x19), (False, 0x18)):
            with self.subTest(pins=pins, address=address), self.machine() as cpu:
                base = self.configure_i2c(cpu, pins)
                self.put(cpu, base + 0x1c, address)
                self.put(cpu, base + 4, 0x26)
                self.put(cpu, base + 0x14, 2)
                self.put(cpu, base + 0x24, 0x2e20)
                cpu.run(33479)
                self.assertEqual(self.get(cpu, base + 8) & 6, 0)
                cpu.run(3721)
                self.assertEqual(self.get(cpu, base + 0x28), 2)  # NACK before ARDY/SCD
                self.assertEqual(self.get(cpu, base + 8) & 6, 4)  # reading status does not clear
                self.assertEqual(self.get(cpu, base + 0x28), 3)
                cpu.write(base + 9, b"\xff")  # upper-byte W1C cannot consume SCD
                self.assertTrue(self.get(cpu, base + 8) & 0x20)
                cpu.write(base + 8, b"\x20")
                self.assertEqual(self.get(cpu, base + 0x28), 0)
                self.assertEqual(cpu.codec_state()["register_writes"], 0)

    def test_i2c_repeated_start_receiver_backpressure_and_data_read_clear(self):
        with self.machine() as cpu:
            base = self.configure_i2c(cpu)
            self.put(cpu, base + 4, 4)
            self.put(cpu, base + 0x14, 1)
            self.put(cpu, base + 0x20, 3)  # codec register pointer only
            self.put(cpu, base + 0x24, 0x2620)  # no STOP, keep bus for repeated START
            cpu.run(66960)
            self.assertEqual(self.get(cpu, base + 8) & 0x1004, 0x1004)
            self.assertEqual(self.get(cpu, base + 0x28), 3)
            self.put(cpu, base + 0x14, 2)
            self.put(cpu, base + 4, 12)
            self.put(cpu, base + 0x24, 0x2c20)
            cpu.run(66960)
            self.assertEqual(cpu.read(base + 0x19, 1), b"\0")
            self.assertTrue(self.get(cpu, base + 8) & 8)
            self.assertEqual(self.get(cpu, base + 0x28), 4)
            self.assertEqual(self.get(cpu, base + 0x28), 0)
            cpu.run(100000)  # receive buffer holds the first byte; clock stretches until read
            self.assertEqual(cpu.codec_state()["bytes_received"], 1)
            self.assertEqual(cpu.read(base + 0x18, 1), b"\x10")
            log, _ = cpu.codec_log()
            self.assertEqual([(row["page"], row["register"], row["value"], row["read"]) for row in log], [(0, 3, 0x10, True)])
            self.assertEqual(cpu.codec_state()["trace"], [])             # the write trace leaves reads out
            self.assertFalse(self.get(cpu, base + 8) & 8)
            cpu.run(33480 + 3720)
            self.assertEqual(self.get(cpu, base + 0x18), 4)
            self.assertEqual(self.get(cpu, base + 8) & 0x3028, 0x2020)

    def test_i2c_codec_page_masks_defaults_and_software_reset_across_slices(self):
        for slice_cycles in (1, 1000):
            with self.subTest(slice_cycles=slice_cycles), self.machine() as cpu:
                base = self.configure_i2c(cpu)
                self.put(cpu, base + 0x14, 2)
                self.put(cpu, base + 0x20, 0)
                self.put(cpu, base + 0x24, 0x2e20)
                for at in range(0, 33480, slice_cycles):
                    cpu.run(min(slice_cycles, 33480 - at))
                self.put(cpu, base + 0x20, 1)  # select page 1
                for at in range(0, 70680, slice_cycles):
                    cpu.run(min(slice_cycles, 70680 - at))
                self.i2c_write(cpu, 65, 0x7f)
                self.assertEqual(cpu.codec_register(1, 65), 0x7f)
                self.i2c_write(cpu, 0, 0)
                self.i2c_write(cpu, 86, 0x0b)
                self.assertEqual(cpu.codec_register(0, 86), 0x0a)  # read-only status bits ignored
                self.i2c_write(cpu, 3, 0xa2)
                self.i2c_write(cpu, 1, 0x80)
                self.assertEqual(cpu.codec_register(0, 3), 0x10)
                self.assertEqual(cpu.codec_register(1, 65), 0x39)
                self.assertEqual(cpu.codec_register(0, 1), 0)  # reset self-clears
                self.assertEqual(cpu.codec_state()["software_resets"], 1)

    def test_i2c_reset_aborts_transfer_and_unsupported_modes_fault(self):
        with self.machine() as cpu:
            base = self.configure_i2c(cpu)
            self.put(cpu, base + 0x14, 2)
            self.put(cpu, base + 0x24, 0x2e20)
            cpu.run(1000)
            self.put(cpu, base + 0x24, 0)
            cpu.run(100000)
            self.assertEqual(self.get(cpu, base + 8), 0x410)
            self.assertEqual(cpu.codec_state()["register_writes"], 0)
            for offset, value in ((0x24, 0x2f20), (0x24, 0x2ea0), (0x24, 0x2e21), (0x24, 0x2e60),
                                  (0x2c, 2), (0x3c, 1)):
                with self.assertRaisesRegex(ValueError, "not implemented"):
                    self.put(cpu, base + offset, value)
            with self.assertRaisesRegex(ValueError, "unimplemented I2C register"):
                self.get(cpu, base + 0x40)
            with self.assertRaisesRegex(ValueError, "unimplemented codec"):
                cpu.codec_register(1, 10)

    def configure_mcasp(self, cpu, clocks=True, pins=True):
        self.enable_module(cpu, 0x01e27000, 7)
        if clocks:
            self.configure_i2c(cpu)
            for reg, value in ((3, 0xa2), (4, 0x20), (8, 0xd0), (9, 0x30)):
                self.i2c_write(cpu, reg, value)
        if pins:
            self.put(cpu, 0x01c14120, 0x00101010)
            self.put(cpu, 0x01c14124, 0x00000110)
        base = 0x01d00000
        self.put(cpu, base + 0x60, 0)
        self.put(cpu, base + 0xa0, 0)
        for side in (0x60, 0xa0):
            for reg, value in ((4, 0xffffffff), (8, 0x180f0), (12, 0x110), (24, 3), (28, 0xf)):
                self.put(cpu, base + side + reg, value)
        self.put(cpu, base + 0xb0, 0x80)
        self.put(cpu, base + 0x1b4, 1)
        self.put(cpu, base + 0x1b8, 2)
        self.put(cpu, base + 0x14, 0x2000)
        return base

    def test_mcasp_reset_aliases_clocked_words_status_and_receive_read_side_effect(self):
        with self.machine() as cpu:
            base = self.configure_mcasp(cpu)
            self.put(cpu, base + 0x44, 0x202)
            self.assertEqual(self.get(cpu, base + 0x60), 0x202)
            self.assertEqual(self.get(cpu, base + 0xa0), 0x202)
            self.put(cpu, base + 0x44, 0x606)
            self.assertTrue(self.get(cpu, base + 0x1b4) & 16)
            self.put(cpu, base + 0x2000, 0x12345678)
            self.assertFalse(self.get(cpu, base + 0xc0) & 32)
            self.put(cpu, base + 0x44, 0x1e1e)
            first = (cpu.state()["cycles"] // 7750 + 1) * 7750 + 3875
            cpu.run(first - cpu.state()["cycles"] - 1)
            self.assertEqual(cpu.audio_output()[1]["transmitted_words"], 0)
            cpu.run(1)
            data, state = cpu.audio_output()
            self.assertEqual(data, struct.pack("<I", 0x12345678))
            self.assertEqual(state["first_capture_cycle"], first)
            self.assertTrue(self.get(cpu, base + 0xc0) & 32)
            self.assertTrue(self.get(cpu, base + 0x1b8) & 32)
            self.assertEqual(self.get(cpu, base + 0x2000), 0)  # silence source
            self.assertFalse(self.get(cpu, base + 0x80) & 32)
            self.put(cpu, base + 0x60, 0)
            self.assertEqual(self.get(cpu, base + 0x44), 0x1e00)  # receiver alias preserves TX
            self.put(cpu, base + 0xa0, 0)
            self.assertEqual(self.get(cpu, base + 0x44), 0)

    def test_mcasp_silence_does_not_shift_without_codec_clocks_or_pinmux(self):
        for clocks, pins in ((False, True), (True, False)):
            with self.subTest(clocks=clocks, pins=pins), self.machine() as cpu:
                base = self.configure_mcasp(cpu, clocks, pins)
                self.put(cpu, base + 0x44, 0x1e1e)
                cpu.run(100000)
                self.assertEqual(cpu.audio_output()[1]["transmitted_words"], 0)
                self.assertEqual(cpu.audio_output()[1]["received_words"], 0)
                if not clocks:
                    self.assertEqual(self.get(cpu, base + 0x44), 0)  # reset release needs external clocks

    def test_mcasp_dma_linked_constant_ports_capture_order_and_completion_across_slices(self):
        snapshots = []
        for slice_cycles, eager in ((1, False), (1000000, False), (1000000, True)):
            with self.subTest(slice_cycles=slice_cycles, eager=eager), self.machine() as cpu:
                cpu.board_eager_polling(eager)
                base = self.configure_mcasp(cpu)
                self.enable_module(cpu, 0x01c10000, 0)
                cpu.map(0x4000, 8192, 3)
                expected = [0x7fffffff, 0x80000000, 0x01020304, 0xabcdef01, 0x12345678, 0x98765432, 0, 1]
                adc = [0x80000000, 0, 0x12345678, 0xffffffff]
                backing = bytearray(struct.pack("<4I", *adc))
                cpu.audio_input(backing, loop=True)
                backing[:] = bytes(len(backing))  # the digital source owns a private copy
                cpu.write(0x4000, struct.pack("<8I", *expected))
                for param, receive, offset, link in ((0, True, 0, 0x4820), (1, False, 0, 0x4800),
                                                     (64, False, 16, 0xffff), (65, True, 16, 0xffff)):
                    opt = 0x100201 if receive else 0x101202
                    src, dst = (base + 0x2000, 0x5000 + offset) if receive else (0x4000 + offset, base + 0x2000)
                    indices = 0x40008 if receive else 0x80004  # FIFO side ignores nonzero B index
                    words = [opt, src, 0x40004, dst, indices, link, 0, 1]
                    for index, value in enumerate(words):
                        self.put(cpu, 0x01c04000 + param * 32 + index * 4, value)
                self.put(cpu, 0x01c01030, 3)
                self.put(cpu, base + 0x44, 0x606)  # initial XDATA request fills XBUF before frame start
                self.put(cpu, 0x01800104, 61)
                cpu.run(1)
                self.assertFalse(self.get(cpu, base + 0xc0) & 32)
                self.put(cpu, base + 0x44, 0x1e1e)
                first = (cpu.state()["cycles"] // 7750 + 1) * 7750 + 3875
                end = first + 7 * 3875
                while cpu.state()["cycles"] < end:
                    cpu.run(min(slice_cycles, end - cpu.state()["cycles"]))
                data, state = cpu.audio_output()
                self.assertEqual(data, struct.pack("<8I", *expected))
                self.assertEqual(cpu.read(0x5000, 32), struct.pack("<8I", *(adc * 2)))
                self.assertEqual(cpu.audio_input_state(), dict(source_words=4, position_words=0, loop=True,
                                                              words_from_source=8, zero_padding_words=0,
                                                              nonzero_words_received=6))
                self.assertEqual((state["transmitted_words"], state["received_words"], state["underruns"], state["overruns"]), (8, 8, 0, 0))
                self.assertEqual(state["last_capture_cycle"] - state["first_capture_cycle"], 7 * 3875)
                self.assertEqual(self.get(cpu, 0x01c01068) & 3, 3)
                self.assertEqual(self.get(cpu, base + 0xc4), 1)
                self.assertEqual(self.get(cpu, base + 0x84), 1)
                # STAT slot-parity bit 3 must not trigger INTCTL DMA-error bit 3.
                self.assertEqual(cpu.state()["registers"]["ifr"] & 16, 0)
                snapshots.append((cpu.state(), data, state, cpu.mmio_trace()))
                self.put(cpu, base + 0x44, 0)
                cpu.run(100000)
                self.assertEqual(cpu.audio_output()[1]["transmitted_words"], 8)
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[0], snapshots[2])

    def test_mcasp_finite_adc_input_pads_eof_and_stays_still_with_receiver_reset(self):
        with self.machine() as cpu:
            for data in (b"", bytes(4), bytes(12)):
                with self.assertRaisesRegex(ValueError, "complete 32-bit slot pairs"):
                    cpu.audio_input(data)
            base = self.configure_mcasp(cpu)
            words = [0x80000000, 0, 0x12345678, 0xffffffff]
            cpu.audio_input(struct.pack("<4I", *words))
            cpu.run(20000)
            self.assertEqual(cpu.audio_input_state()["words_from_source"], 0)
            self.put(cpu, base + 0x60, 0x1e)
            first = (cpu.state()["cycles"] // 7750 + 1) * 7750 + 3875
            cpu.run(first - cpu.state()["cycles"])
            for index, expected in enumerate(words + [0, 0]):
                if index:
                    cpu.run(3875)
                self.assertEqual(self.get(cpu, base + 0x2000), expected)
            self.assertEqual(cpu.audio_input_state(), dict(source_words=4, position_words=4, loop=False,
                                                          words_from_source=4, zero_padding_words=2,
                                                          nonzero_words_received=3))
            self.assertEqual(cpu.audio_output()[1]["overruns"], 0)
            with self.assertRaisesRegex(ValueError, "before the first received slot"):
                cpu.audio_input(bytes(8))
            state = cpu.audio_input_state()
            self.put(cpu, base + 0x60, 0)
            cpu.run(20000)
            self.assertEqual(cpu.audio_input_state(), state)

    def test_mmcsd_scheduler_preserves_fraction_at_psc_stop_and_restart(self):
        states = []
        for eager in (False, True):
            with self.subTest(eager=eager), self.machine() as cpu:
                cpu.board_eager_polling(eager)
                base = self.configure_mmcsd(cpu)
                self.put(cpu, base + 0x30, 0)
                self.put(cpu, 0x01c10a14, 0)
                self.put(cpu, 0x01c10120, 1)
                cpu.run(16)
                cpu.run(1000)
                self.enable_module(cpu, 0x01c10000, 5)
                cpu.run(175)
                self.assertEqual(self.get(cpu, base + 8), 0x200)
                cpu.run(1)
                self.assertEqual(self.get(cpu, base + 8), 4)
                states.append(cpu.state())
        self.assertEqual(states[0], states[1])

    def test_mcasp_overrun_underrun_irq_w1c_and_unsupported_configuration(self):
        with self.machine() as cpu:
            base = self.configure_mcasp(cpu)
            self.put(cpu, 0x01800104, 61)
            self.put(cpu, base + 0x44, 0x1e1e)
            cpu.run(30000)  # deliberately leave both buffers unserviced
            self.assertTrue(self.get(cpu, base + 0xc0) & 0x101)
            self.assertTrue(self.get(cpu, base + 0x80) & 0x101)
            self.assertTrue(cpu.state()["registers"]["ifr"] & 16)
            self.put(cpu, base + 0xc0, 1)
            self.assertEqual(self.get(cpu, base + 0xc0) & 0x101, 0)
            self.put(cpu, base + 0x2000, 0x7fffffff)
            cpu.run(3875)
            self.assertEqual(cpu.audio_output()[0][-4:], b"\0" * 4)  # underrun requires reset to recover
            self.put(cpu, base + 0x44, 0)
            with self.assertRaisesRegex(ValueError, "unimplemented McASP"):
                self.get(cpu, base + 0x40)
            with self.assertRaisesRegex(ValueError, "not implemented"):
                self.put(cpu, base + 0x4c, 1)
            self.put(cpu, base + 0xa8, 0)
            with self.assertRaisesRegex(ValueError, "supports only"):
                self.put(cpu, base + 0x44, 0x1e1e)

    def test_edma_fifo_width_and_alignment_fail_explicitly(self):
        for source, acnt, fwid in ((0x4004, 4, 2), (0x4000, 8, 2), (0x4000, 4, 1)):
            with self.subTest(source=source, acnt=acnt, fwid=fwid), self.machine() as cpu:
                self.enable_module(cpu, 0x01c10000, 0)
                cpu.map(0x4000, 8192, 3)
                words = [1 | fwid << 8, source, 0x10000 | acnt, 0x5000, 0, 0xffff, 0, 1]
                for index, value in enumerate(words):
                    self.put(cpu, 0x01c04000 + index * 4, value)
                self.put(cpu, 0x01c01010, 1)
                with self.assertRaisesRegex(RuntimeError, "EDMA FIFO supports only"):
                    cpu.run(1)

    def test_mmcsd_reset_no_response_command_timing_and_interrupt_ack(self):
        with self.machine() as cpu:
            base = 0x01c40000
            self.assertEqual(self.get(cpu, base + 4), 255)
            self.assertEqual(self.get(cpu, base + 8), 0x200)
            self.assertEqual(self.get(cpu, base + 0x1c), 512)
            self.assertEqual(self.get(cpu, base + 0x24), 65535)
            base = self.configure_mmcsd(cpu, rate=1)
            self.put(cpu, 0x01800104, 15)  # MMCSD0 INT0 -> interrupt 4
            self.put(cpu, base + 0x10, 4)
            self.put(cpu, base + 0x30, 0x4000)  # CMD0, 80 init + 48 command clocks
            cpu.run(128 * 8 - 1)
            self.assertEqual(self.get(cpu, base + 8), 0x200)
            cpu.run(1)
            self.assertEqual(self.get(cpu, base + 8), 4)
            self.assertEqual(self.get(cpu, base + 8), 0)  # every status flag clears on read
            self.assertEqual(cpu.state()["registers"]["ifr"] & (1 << 4), 1 << 4)
            self.put(cpu, 0x01800040, 1 << 15)
            cpu.set_register("ifr", 0)
            cpu.run(100)
            self.assertEqual(cpu.state()["registers"]["ifr"], 0)

    def test_mmcsd_absent_card_timeout_is_clocked_and_clear_on_read(self):
        with self.machine() as cpu:
            base = self.configure_mmcsd(cpu)
            self.put(cpu, base + 0x30, 0x208)  # CMD8 expects a 48-bit response
            cpu.run((48 + 7) * 4 - 1)
            self.assertEqual(self.get(cpu, base + 8) & 0x14, 0)
            cpu.run(1)
            # Reading an unrelated byte must not clear low-byte status events.
            self.assertEqual(cpu.read(base + 9, 1), b"\x00")
            self.assertEqual(self.get(cpu, base + 8), 0x10)
            self.assertEqual(self.get(cpu, base + 8), 0)
            self.assertEqual(self.get(cpu, base + 0x44), 0)
            self.put(cpu, base + 0x14, 0)  # TOR=0 disables response timeout
            self.put(cpu, base + 0x30, 0x208)
            cpu.run(10000)
            self.assertEqual(self.get(cpu, base + 8), 0)
            self.put(cpu, base, 3)  # reset aborts an outstanding command
            self.put(cpu, base, 0)
            self.put(cpu, base + 0x30, 0)
            cpu.run(192)
            self.assertEqual(self.get(cpu, base + 8), 0x204)

    def test_mmcsd_stopped_clock_psc_divider_and_explicit_unsupported_modes(self):
        with self.machine() as cpu:
            base = self.configure_mmcsd(cpu)
            self.put(cpu, base + 4, 0)  # clock disabled
            self.put(cpu, base + 0x30, 0)
            cpu.run(1000)
            self.assertEqual(self.get(cpu, base + 8), 0x200)
            self.assertTrue(self.get(cpu, base + 12) & 2)
            self.put(cpu, base + 4, 0x300)  # DIV4 -> 8 DSP cycles per bit
            self.put(cpu, 0x01c10a14, 0)
            self.put(cpu, 0x01c10120, 1)
            cpu.run(16)
            # 16 cycles elapsed before the PSC transition; finish those clocks later.
            cpu.run(1000)
            self.assertEqual(self.get(cpu, base + 8), 0)
            self.enable_module(cpu, 0x01c10000, 5)
            cpu.run(48 * 8)
            self.assertEqual(self.get(cpu, base + 8), 4)
            for offset in (0x4c, 0x54, 0x60):
                with self.assertRaisesRegex(ValueError, "unimplemented MMCSD"):
                    self.get(cpu, base + offset)
            for offset, value in ((0x64, 1), (0, 0x200), (0x30, 0x10000), (0x30, 0x1000)):
                with self.assertRaisesRegex(ValueError, "unsupported|not implemented"):
                    self.put(cpu, base + offset, value)

    def test_gpio_directions_set_clear_and_external_pin_levels(self):
        with self.machine() as cpu:
            with self.assertRaisesRegex(ValueError, "not enabled"):
                self.get(cpu, 0x01e26010)
            self.enable_module(cpu, 0x01e27000, 3)
            # Pair 0 starts with all inputs. An output latch cannot drive an input.
            self.put(cpu, 0x01e26018, 3)
            cpu.gpio_input(0, 0, False)
            cpu.gpio_input(0, 1, True)
            self.assertEqual(self.get(cpu, 0x01e26020) & 3, 2)
            self.put(cpu, 0x01e26010, 0xfffffffc)
            self.assertEqual(self.get(cpu, 0x01e26020) & 3, 3)
            self.put(cpu, 0x01e2601c, 1)
            self.assertEqual(self.get(cpu, 0x01e26020) & 3, 2)
            self.assertEqual(self.get(cpu, 0x01e26018), self.get(cpu, 0x01e26014))
            self.assertEqual(self.get(cpu, 0x01e2601c), self.get(cpu, 0x01e26014))
            self.assertEqual(self.get(cpu, 0x01e26070) & (1 << 11), 1 << 11)

    def test_gpio_rise_fall_latch_bank_interrupt_and_acknowledge(self):
        with self.machine() as cpu:
            self.enable_module(cpu, 0x01e27000, 3)
            self.put(cpu, 0x01800104, 72)  # GPIO bank 7 -> CPU interrupt 4
            self.put(cpu, 0x01e26008, 1 << 7)
            self.put(cpu, 0x01e2609c, 1 << 24)  # bank 7 pin 8 rising enable
            cpu.gpio_input(7, 8, True)
            cpu.run(1)
            self.assertEqual(cpu.state()["registers"]["ifr"], 1 << 4)
            self.assertEqual(self.get(cpu, 0x01e260ac), 1 << 24)
            self.put(cpu, 0x01e260ac, 1 << 24)
            self.assertEqual(self.get(cpu, 0x01e260ac), 0)
            cpu.set_register("ifr", 0)
            self.put(cpu, 0x01e260a0, 1 << 24)  # clear rising enable
            self.put(cpu, 0x01e260a4, 1 << 24)  # falling enable
            cpu.gpio_input(7, 8, False)
            cpu.run(1)
            self.assertEqual(cpu.state()["registers"]["ifr"], 1 << 4)

    def test_edma_shadow_permissions_aliases_param_ram_and_qdma_trigger_fault(self):
        with self.machine() as cpu:
            self.enable_module(cpu, 0x01c10000, 0)
            base = 0x01c00000
            self.put(cpu, base + 0x2230, 0x1234)  # no DRAE1 access yet
            self.assertEqual(self.get(cpu, base + 0x1020), 0)
            self.put(cpu, base + 0x348, 0x1200)
            self.put(cpu, base + 0x2230, 0x1234)
            self.assertEqual(self.get(cpu, base + 0x1020), 0x1200)
            self.assertEqual(self.get(cpu, base + 0x2220), 0x1200)
            self.put(cpu, base + 0x2228, 0x200)
            self.assertEqual(self.get(cpu, base + 0x1020), 0x1000)
            self.put(cpu, base + 0x2260, 0x1000)
            self.assertEqual(self.get(cpu, base + 0x1050), 0x1000)
            self.put(cpu, base + 0x2258, 0x1000)
            self.assertEqual(self.get(cpu, base + 0x1050), 0)
            self.put(cpu, base + 0x4804, 0xc0001000)
            self.assertEqual(self.get(cpu, base + 0x4804), 0xc0001000)
            self.put(cpu, base + 0x200, (64 << 5) | (7 << 2))
            self.put(cpu, base + 0x108c, 1)
            with self.assertRaisesRegex(ValueError, "QDMA transfer trigger"):
                self.put(cpu, base + 0x481c, 1)
            with self.assertRaisesRegex(ValueError, "unimplemented EDMA"):
                self.get(cpu, base + 0x700)

    def configure_spi(self, cpu, loopback=True, pins=True):
        self.enable_module(cpu, 0x01e27000, 10)
        base = 0x01f0e000
        self.put(cpu, base, 0)
        self.put(cpu, base, 1)
        self.put(cpu, base + 4, 3)
        self.put(cpu, 0x01c14134, 0x00100110)
        if pins:
            self.put(cpu, base + 0x14, 0xe01)
        self.put(cpu, base + 0x50, 0x00011308)
        self.put(cpu, base + 4, 0x01000003 | (0x10000 if loopback else 0))
        return base

    def configure_nor(self, cpu):
        self.enable_module(cpu, 0x01c10000, 4)
        base = 0x01c41000
        self.put(cpu, 0x01c1412c, 0x1111)
        self.put(cpu, 0x01c14130, 0x11)
        self.put(cpu, base, 1)
        self.put(cpu, base + 4, 3)
        self.put(cpu, base + 0x14, 0xe03)
        self.put(cpu, base + 0x50, 8)  # fastest divider: 16 DSP cycles/byte
        self.put(cpu, base + 4, 0x01000003)
        return base

    def nor_transfer(self, cpu, data, chip=0, release=True):
        base = 0x01c41000
        result = bytearray()
        for index, byte in enumerate(data):
            hold = not release or index + 1 < len(data)
            self.put(cpu, base + 0x3c, ((255 ^ (1 << chip)) << 16) | (0x10000000 if hold else 0) | byte)
            cpu.run(16)
            result.append(self.get(cpu, base + 0x40) & 255)
        return bytes(result)

    def test_nor_identification_and_configuration_are_the_units(self):
        # Bench M1, step C1: both devices answer 9F with C2 20 18; 15 reads 0F on device 0 and 07 on device 1.
        with self.machine() as cpu:
            self.configure_nor(cpu)
            for chip, configuration in ((0, 0x0f), (1, 0x07)):
                self.assertEqual(self.nor_transfer(cpu, b"\x9f\0\0\0\0", chip)[1:], b"\xc2\x20\x18\xc2")
                self.assertEqual(self.nor_transfer(cpu, b"\x15\0\0", chip)[1:], bytes([configuration] * 2))
            self.nor_transfer(cpu, b"\x06"); self.nor_transfer(cpu, b"\x20\0\0\0")   # busy: only status answers
            self.assertEqual(self.nor_transfer(cpu, b"\x9f\0")[1:], b"\xff")
            self.assertEqual(self.nor_transfer(cpu, b"\x05\0")[1:], b"\x03")

    def test_nor_status_wren_edges_chip_select_isolation_and_read_wrap(self):
        with self.machine() as cpu:
            self.configure_nor(cpu)
            source = bytearray(b"\x12\x34")
            cpu.nor_load(0, source, 0xfffffe)
            cpu.nor_load(0, b"\x56\x78")
            cpu.nor_load(1, b"\xab\xcd")
            source[0] = 0  # private copy
            self.assertEqual(self.nor_transfer(cpu, b"\x03\xff\xff\xfe\0\0\0\0")[4:], b"\x12\x34\x56\x78")
            self.assertEqual(self.nor_transfer(cpu, b"\x03\0\0\0\0\0", chip=1)[4:], b"\xab\xcd")
            self.nor_transfer(cpu, b"\x06", release=False)
            self.assertEqual(cpu.nor_stats()[0]["status"], 0)  # WEL waits for CS rising
            # Upper-byte control store releases CS without transmitting another byte.
            cpu.write(0x01c4103f, b"\0")
            self.assertEqual(self.nor_transfer(cpu, b"\x05\0\0"), b"\xff\x02\x02")
            self.assertEqual(self.nor_transfer(cpu, b"\x05\0", chip=1), b"\xff\0")
            self.nor_transfer(cpu, b"\x04")
            self.assertEqual(self.nor_transfer(cpu, b"\x05\0"), b"\xff\0")
            self.nor_transfer(cpu, b"\x06\0")  # WREN requires exactly eight clocks before CS rises
            self.assertEqual(self.nor_transfer(cpu, b"\x05\0"), b"\xff\0")
            self.assertEqual(cpu.nor_stats()[0]["bytes_read"], 4)
            for chip, offset, size in ((2, 0, 1), (0, 0xffffff, 2)):
                with self.assertRaisesRegex(ValueError, "SPI NOR"):
                    cpu.nor_read(chip, offset, size)

    def test_nor_page_program_wel_busy_one_to_zero_and_page_wrap(self):
        with self.machine() as cpu:
            self.configure_nor(cpu)
            self.nor_transfer(cpu, b"\x02\0\x01\xff\x12\x34")  # no WREN: ignored
            cpu.run(372000)
            self.assertEqual(cpu.nor_read(0, 0x1ff, 1), b"\xff")
            self.nor_transfer(cpu, b"\x06")
            self.nor_transfer(cpu, b"\x02\0\x01\xff\x12\x34")
            self.assertEqual(self.nor_transfer(cpu, b"\x05\0")[1] & 1, 1)
            self.assertEqual(cpu.nor_read(0, 0x1ff, 1), b"\xff")  # pending mutation
            cpu.run(372000)
            self.assertEqual(cpu.nor_read(0, 0x1ff, 1), b"\x12")
            self.assertEqual(cpu.nor_read(0, 0x100, 1), b"\x34")  # page boundary wraps
            self.assertEqual(cpu.nor_read(0, 0x200, 1), b"\xff")
            self.assertEqual(self.nor_transfer(cpu, b"\x05\0")[1], 0)
            self.nor_transfer(cpu, b"\x06")
            self.nor_transfer(cpu, b"\x02\0\x01\xff\xf1")
            cpu.run(372000)
            self.assertEqual(cpu.nor_read(0, 0x1ff, 1), b"\x10")
            self.assertEqual(cpu.nor_stats()[0]["programs"], 2)
            self.assertEqual(cpu.nor_read(1, 0x1ff, 1), b"\xff")

    def test_nor_sector_erase_alignment_abort_busy_and_unknown_command(self):
        with self.machine() as cpu:
            self.configure_nor(cpu)
            cpu.nor_load(0, b"\0" * 4097, 0x1000)
            self.nor_transfer(cpu, b"\x06")
            self.nor_transfer(cpu, b"\x20\0\x10")  # incomplete address: no mutation
            self.assertEqual(cpu.nor_stats()[0]["status"], 2)
            self.nor_transfer(cpu, b"\x20\0\x1f\xff")
            self.nor_transfer(cpu, b"\x04")  # WRDI ignored while busy
            self.assertEqual(cpu.nor_stats()[0]["status"] & 1, 1)
            cpu.run(18600000)
            self.assertEqual(cpu.nor_read(0, 0x1000, 4096), b"\xff" * 4096)
            self.assertEqual(cpu.nor_read(0, 0x2000, 1), b"\0")
            self.assertEqual(cpu.nor_stats()[0]["erases"], 1)
            self.assertEqual(cpu.nor_stats()[0]["status"], 0)
            self.put(cpu, 0x01c4103c, 0x00fe0001)
            with self.assertRaisesRegex(RuntimeError, "unimplemented SPI NOR command 0x01"):
                cpu.run(16)

    def test_nor_spi0_full_duplex_dma_uses_channels_14_15_and_receives_exact_bytes(self):
        for slice_cycles in (1, 500):
            with self.subTest(slice_cycles=slice_cycles), self.machine() as cpu:
                base = self.configure_nor(cpu)
                self.enable_module(cpu, 0x01c10000, 0)
                cpu.map(0x4000, 8192, 3)
                expected = b"\x91\x23\xa5\x7e\x18\x40\xc3\x5a"
                cpu.nor_load(1, expected, 0x123456)
                self.nor_transfer(cpu, b"\x03\x12\x34\x56", chip=1, release=False)
                for channel, src, dst, indices in ((14, base + 0x40, 0x5000, 0x10000),
                                                   (15, 0x4000, base + 0x3c, 1)):
                    words = [0x100000 | channel << 12, src, len(expected) << 16 | 1,
                             dst, indices, 0xffff, 0, 1]
                    for index, value in enumerate(words):
                        self.put(cpu, 0x01c04000 + channel * 32 + index * 4, value)
                self.put(cpu, 0x01c01030, (1 << 14) | (1 << 15))
                self.put(cpu, base + 8, 0x10000)
                for start in range(0, 500, slice_cycles):
                    cpu.run(min(slice_cycles, 500 - start))
                self.assertEqual(cpu.read(0x5000, len(expected)), expected)
                self.assertEqual(cpu.nor_stats()[1]["bytes_read"], len(expected))
                self.assertEqual(self.get(cpu, 0x01c01068) & 0xc000, 0xc000)
                self.assertEqual(self.get(cpu, 0x01c01000) & 0x30000, 0)  # MMCSD0 events were never emitted

    def test_spi_loopback_clocked_completion_buffering_and_read_clear(self):
        with self.machine() as cpu:
            base = self.configure_spi(cpu)
            self.put(cpu, base + 0x3c, 0x00fe00a5)
            self.put(cpu, base + 0x3c, 0x00fe005a)
            self.assertEqual(self.get(cpu, base + 0x40) & 0xa0000000, 0xa0000000)
            with self.assertRaisesRegex(ValueError, "overflow"):
                self.put(cpu, base + 0x3c, 0x11)
            cpu.run(319)
            self.assertTrue(self.get(cpu, base + 0x40) & 0x80000000)
            cpu.run(1)
            self.assertEqual(self.get(cpu, base + 0x40), 0xa5)
            self.assertTrue(self.get(cpu, base + 0x40) & 0x80000000)
            cpu.run(320)
            self.assertEqual(self.get(cpu, base + 0x40), 0x5a)
            self.assertEqual(self.get(cpu, base + 0x10), 0x200)

    def test_spi_upper_control_byte_writes_do_not_transmit_and_missing_pins_stall(self):
        with self.machine() as cpu:
            base = self.configure_spi(cpu)
            cpu.write(base + 0x3f, bytes([0x10]))
            cpu.write(base + 0x3e, bytes([0xfe]))
            cpu.run(1000)
            self.assertTrue(self.get(cpu, base + 0x40) & 0x80000000)
            cpu.write(base + 0x3c, bytes([0x42]))
            cpu.run(320)
            self.assertEqual(self.get(cpu, base + 0x40), 0x42)
        with self.machine() as cpu:
            base = self.configure_spi(cpu, loopback=False, pins=False)
            self.put(cpu, base + 0x3c, 0x10fe00af)
            cpu.run(1000)
            self.assertTrue(self.get(cpu, base + 0x40) & 0x80000000)
            self.put(cpu, base + 0x14, 0xe01)
            cpu.run(1000)
            self.assertFalse(self.get(cpu, base + 0x40) & 0x80000000)

    def test_oled_commands_and_frame_are_supplied_only_by_spi_bytes(self):
        with self.machine() as cpu:
            base = self.configure_spi(cpu, loopback=False)
            self.enable_module(cpu, 0x01e27000, 3)
            self.put(cpu, 0x01c14134, 0x00180110)
            self.put(cpu, 0x01e26038, 0xfffff7ff)
            def send(value):
                self.put(cpu, base + 0x3c, 0x10fe0000 | value)
                cpu.run(320)
                self.assertEqual(self.get(cpu, base + 0x40), 255)
            for value in (0xb3, 0xf0, 0x81, 0xff, 0xa0, 7, 0xaf):
                send(value)
            self.put(cpu, 0x01e26040, 1 << 11)
            expected = bytes((i * 13) & 255 for i in range(8192))
            for value in expected:
                send(value)
            data, state = cpu.oled_frame()
            self.assertEqual(data, expected)
            self.assertEqual(state, {"bytes_received": 8192, "complete_frames": 1, "on": True,
                                     "first_frame_cycle": cpu.state()["cycles"],
                                     "contrast": 255, "remap": 7, "cursor": 0})

    def test_spi_hardware_dma_moves_ram_bytes_and_signals_completion(self):
        with self.machine() as cpu:
            base = self.configure_spi(cpu)
            self.enable_module(cpu, 0x01c10000, 0)
            cpu.map(0x4000, 8192, 3)
            cpu.write(0x4000, b"DMA!")
            self.put(cpu, 0x01800104, 8)
            self.put(cpu, 0x01800108, 0x0b0a097f)  # remove reset INT8's duplicate event-8 route
            self.put(cpu, 0x01c00348, 1 << 19)
            self.put(cpu, 0x01c01060, 1 << 19)
            words = [0x00113000, 0x4000, 0x00040001, base + 0x3c, 1, 0xffff, 0, 1]
            for index, value in enumerate(words):
                self.put(cpu, 0x01c04260 + index * 4, value)
            self.put(cpu, 0x01c01030, 1 << 19)
            self.put(cpu, base + 8, 0x10000)
            cpu.run(1)  # first device event is serviced at the next machine tick
            output = []
            for _ in range(4):
                cpu.run(320)
                output.append(self.get(cpu, base + 0x40) & 255)
            self.assertEqual(bytes(output), b"DMA!")
            self.assertEqual(self.get(cpu, 0x01c01068), 1 << 19)
            self.assertEqual(cpu.state()["registers"]["ifr"], 1 << 4)
            self.put(cpu, 0x01c01070, 1 << 19)
            self.assertEqual(self.get(cpu, 0x01c01068), 0)

    def test_edma_a_ab_sync_indices_null_link_and_reload(self):
        for ab in (False, True):
            with self.subTest(ab=ab), self.machine() as cpu:
                self.enable_module(cpu, 0x01c10000, 0)
                cpu.map(0x4000, 8192, 3)
                cpu.write(0x4000, struct.pack("<4I", 10, 20, 30, 40))
                # Reverse the source arrays into a forward destination. Software ESR
                # triggers work even when the channel's hardware event enable is clear.
                words = [4 if ab else 0, 0x400c, 0x00040004, 0x5000, 0x0004fffc, 0xffff, 0, 1]
                for index, value in enumerate(words):
                    self.put(cpu, 0x01c04040 + index * 4, value)
                for index in range(1 if ab else 4):
                    self.put(cpu, 0x01c01010, 1 << 2)
                    cpu.run(1)
                    self.assertEqual(cpu.read(0x5000, (4 if ab else index + 1) * 4),
                                     struct.pack("<4I", 40, 30, 20, 10)[:(16 if ab else (index + 1) * 4)])
                self.assertEqual(self.get(cpu, 0x01c04048), 0)
                self.assertEqual(self.get(cpu, 0x01c04054), 0xffff)
                # A completed descriptor reloads its linked descriptor before the next event.
                linked = [0, 0x4000, 0x00010004, 0x5010, 0, 0xffff, 0, 1]
                for index, value in enumerate(linked):
                    self.put(cpu, 0x01c04800 + index * 4, value)
                initial = [0, 0x4004, 0x00010004, 0x5014, 0, 0x4800, 0, 1]
                for index, value in enumerate(initial):
                    self.put(cpu, 0x01c04040 + index * 4, value)
                self.put(cpu, 0x01c01010, 1 << 2); cpu.run(1)
                self.assertEqual(self.get(cpu, 0x01c04044), 0x4000)
                self.put(cpu, 0x01c01010, 1 << 2); cpu.run(1)
                self.assertEqual(cpu.read(0x5010, 8), struct.pack("<2I", 10, 20))

    def test_edma_c_indices_and_a_sync_b_count_reload_across_frames(self):
        for ab in (False, True):
            with self.subTest(ab=ab), self.machine() as cpu:
                self.enable_module(cpu, 0x01c10000, 0)
                cpu.map(0x4000, 8192, 3)
                cpu.write(0x4000, struct.pack("<5I", 10, 20, 30, 40, 50))
                # C indices use the first array for AB sync, the last array for A sync.
                cidx = 0x0008000c if ab else 0x00040008
                words = [4 if ab else 0, 0x4000, 0x00020004, 0x5000, 0x00040004, 0x0002ffff, cidx, 2]
                for index, value in enumerate(words):
                    self.put(cpu, 0x01c04040 + index * 4, value)
                for frame in range(2):
                    for _ in range(1 if ab else 2):
                        self.put(cpu, 0x01c01010, 1 << 2)
                        cpu.run(1)
                    if frame == 0:
                        self.assertEqual(self.get(cpu, 0x01c04044), 0x400c)
                        self.assertEqual(self.get(cpu, 0x01c0404c), 0x5008)
                        self.assertEqual(self.get(cpu, 0x01c04048), 0x00020004)
                        self.assertEqual(self.get(cpu, 0x01c0405c), 1)
                self.assertEqual(cpu.read(0x5000, 16), struct.pack("<4I", 10, 20, 40, 50))

    def configure_uart(self, cpu, loopback=True):
        self.enable_module(cpu, 0x01e27000, 12)
        base = 0x01d0c000
        self.put(cpu, base + 0x20, 25)
        self.put(cpu, base + 0x24, 0)
        self.put(cpu, base + 0xc, 3)
        self.put(cpu, base + 8, 7)
        self.put(cpu, base + 0x30, 0x6001)
        self.put(cpu, base + 0x10, 0x10 if loopback else 0)
        return base

    def test_uart_baud_timing_loopback_fifo_status_and_receive_read_side_effect(self):
        with self.machine() as cpu:
            base = self.configure_uart(cpu)
            self.put(cpu, base, 0x5a)
            self.assertEqual(self.get(cpu, base + 0x14), 0x20)
            cpu.run(7999)  # 10 bits * 16x * divisor 25 * two DSP cycles per input clock
            self.assertEqual(self.get(cpu, base + 0x14), 0x20)
            cpu.run(1)
            self.assertEqual(self.get(cpu, base + 0x14), 0x61)
            self.assertEqual(self.get(cpu, base), 0x5a)
            self.assertEqual(self.get(cpu, base + 0x14), 0x60)
            with self.assertRaisesRegex(ValueError, "UART input must be bytes"):
                cpu.uart_receive(1, 0xa1)  # bytes(int) would silently inject 161 zeros.
            self.assertEqual(self.get(cpu, base + 0x14), 0x60)
            cpu.uart_receive(1, b"ab")
            cpu.write(base, b"x")  # THR byte write must not read/pop RBR.
            self.assertEqual(self.get(cpu, base), ord("a"))
            self.assertEqual(self.get(cpu, base), ord("b"))

    def test_uart_receive_irq_fifo_clear_overrun_and_reset(self):
        with self.machine() as cpu:
            base = self.configure_uart(cpu, loopback=False)
            self.put(cpu, 0x01800104, 46)
            self.put(cpu, base + 4, 5)
            cpu.uart_receive(1, bytes(range(17)))
            cpu.run(1)
            self.assertEqual(cpu.state()["registers"]["ifr"], 1 << 4)
            self.assertEqual(self.get(cpu, base + 8) & 15, 6)
            self.assertEqual(self.get(cpu, base + 0x14) & 3, 3)
            self.assertEqual(self.get(cpu, base + 8) & 15, 4)
            self.assertEqual([self.get(cpu, base) for _ in range(16)], list(range(16)))
            self.assertEqual(self.get(cpu, base + 8) & 15, 1)
            cpu.uart_receive(1, b"z")
            self.put(cpu, base + 8, 3)
            self.assertEqual(self.get(cpu, base + 0x14) & 1, 0)
            self.put(cpu, base + 0x30, 0)
            cpu.uart_receive(1, b"z")
            self.assertEqual(self.get(cpu, base + 0x14) & 1, 0)

    def test_panel_stream_sends_every_channel_in_the_units_order_at_the_measured_rate(self):
        # M1 bench D1, D2: 4192-4196 messages a second whether or not a pad is touched, 262 a second on one
        # channel. M2 P1: the channels come in the order 0 4 3 7 B D A E F 2 1 5 9 6 8 C. Even spacing and the
        # levels are this model's own.
        MESSAGE = 88698  # 372 MHz / 4194
        results = []
        for slice_cycles in (997, 100000):
            with self.machine() as cpu:
                base = self.configure_uart(cpu, loopback=False)   # divisor 25: 8000 cycles a character
                def run(cycles):
                    while cycles:
                        part = min(cycles, slice_cycles); cpu.run(part); cycles -= part
                def message():
                    return [self.get(cpu, base) for _ in range(3)]
                start = cpu.state()["cycles"]
                cpu.panel_stream()
                with self.assertRaisesRegex(ValueError, "panel stream"):
                    cpu.uart_receive(1, b"a")
                cpu.uart_receive(0, b"a")
                run(MESSAGE - 1)
                self.assertEqual(self.get(cpu, base + 0x14) & 1, 0)
                run(1)
                self.assertEqual(self.get(cpu, base + 0x14) & 1, 1)
                self.assertEqual(self.get(cpu, base), 0xb0)
                self.assertEqual(self.get(cpu, base + 0x14) & 1, 0)   # the level follows a character time later
                run(7999)
                self.assertEqual(self.get(cpu, base + 0x14) & 1, 0)
                run(8001)
                self.assertEqual([self.get(cpu, base), self.get(cpu, base)], [0, 0])
                cpu.panel_level(4, 0x1234)
                cpu.panel_level(3, 16383)
                run(MESSAGE)
                self.assertEqual(message(), [0xb4, 0x34, 0x24])
                # A level set while its message is under way is sent whole in the next round.
                run(MESSAGE - 16000 + 1)
                self.assertEqual(self.get(cpu, base), 0xb3)
                cpu.panel_level(3, 0)
                run(MESSAGE - 1)
                self.assertEqual(message() + [self.get(cpu, base + 0x14) & 1], [0x7f, 0x7f, 0xb7, 0])
                run(16000 + 4 * MESSAGE)
                self.put(cpu, base + 8, 7)                        # drop what has arrived
                run(MESSAGE)
                self.assertEqual(message(), [0xbf, 12000 & 0x7f, 12000 >> 7])   # the battery channel's starting level
                order = []
                for _ in range(7):
                    run(MESSAGE); order.append(message()[0])
                self.assertEqual(order, [0xb2, 0xb1, 0xb5, 0xb9, 0xb6, 0xb8, 0xbc])
                run(MESSAGE)
                self.assertEqual(message(), [0xb0, 0, 0])
                run(2 * MESSAGE)
                self.assertEqual(message() + message(), [0xb4, 0x34, 0x24, 0xb3, 0, 0])
                state = cpu.panel_stream_state()
                self.assertEqual((state["enabled"], state["messages"], state["levels"][4], state["levels"][15]), (True, 19, 0x1234, 12000))
                self.assertEqual(cpu.state()["cycles"] - start, 19 * MESSAGE + 16000)
                cpu.panel_stream(False)
                run(3 * MESSAGE)
                self.assertEqual(self.get(cpu, base + 0x14) & 1, 0)
                cpu.uart_receive(1, b"a")
                self.assertEqual(self.get(cpu, base), ord("a"))
                with self.assertRaisesRegex(ValueError, "0..15"):
                    cpu.panel_level(16, 0)
                with self.assertRaisesRegex(ValueError, "16383"):
                    cpu.panel_level(0, 16384)
                results.append((cpu.state()["cycles"], cpu.panel_stream_state()))
        self.assertEqual(results[0], results[1])

    def configure_midi(self, cpu, interrupts=0):
        # The stock MIDI set-up (docs/04-hardware-access.md, "MIDI DIN on UART0"): 31,250 baud 8N1.
        self.enable_module(cpu, 0x01c10000, 9)
        base = 0x01c42000
        self.put(cpu, 0x01c1412c, 0x00220000)  # PINMUX3: UART0 RXD, TXD
        self.put(cpu, base + 0x34, 0)
        self.put(cpu, base + 0x20, 0x74)
        self.put(cpu, base + 0x24, 1)
        self.put(cpu, base + 0xc, 3)
        self.put(cpu, base + 8, 7)
        self.put(cpu, base + 8, 1)
        self.put(cpu, base + 4, interrupts)
        self.put(cpu, base + 0x30, 0x6001)
        return base

    def test_midi_in_delivers_one_byte_a_character_time_where_uart_receive_overruns(self):
        CHARACTER = 119040  # 10 bits at 31,250 baud, in 372 MHz cycles
        results = []
        for slice_cycles in (997, 1000000):
            with self.machine() as cpu:
                def run(cycles):
                    while cycles:
                        part = min(cycles, slice_cycles); cpu.run(part); cycles -= part
                self.assertEqual(cpu.midi_state()["character_cycles"], CHARACTER)  # nothing programmed yet
                cpu.midi_in(b"\x90\x3c\x7f")   # the receiver is still in reset: lost, a character time apart
                run(3 * CHARACTER)
                state = cpu.midi_state()
                self.assertEqual((state["queued"], state["delivered"], state["ignored"], state["next_cycle"]), (0, 0, 3, None))
                base = self.configure_midi(cpu, interrupts=5)
                self.put(cpu, 0x01800104, 38)  # UART0 -> CPU interrupt 4
                self.assertEqual(cpu.midi_state()["character_cycles"], CHARACTER)
                dump = bytes([0xf0, *(value & 0x7f for value in range(38)), 0xf7])
                start = cpu.state()["cycles"]
                cpu.midi_in(dump[:10])
                cpu.midi_in(dump[10:])            # joins the queue: no gap, no restart
                cpu.midi_in(b"")
                self.assertEqual(cpu.midi_state()["next_cycle"], start + CHARACTER)
                run(CHARACTER - 1)
                self.assertEqual((self.get(cpu, base + 0x14) & 1, cpu.state()["registers"]["ifr"]), (0, 0))
                run(1)
                self.assertEqual(cpu.state()["registers"]["ifr"], 1 << 4)
                state = cpu.midi_state()
                self.assertEqual((state["queued"], state["delivered"], state["fifo"]), (39, 1, 1))
                run(15 * CHARACTER)               # sixteen unread bytes fill the FIFO and no more
                state = cpu.midi_state()
                self.assertEqual((state["fifo"], state["overruns"], state["line_errors"]), (16, 0, 0))
                received = [self.get(cpu, base) for _ in range(16)]
                for _ in range(24):
                    run(CHARACTER)
                    self.assertEqual(self.get(cpu, base + 0x14) & 3, 1)
                    received.append(self.get(cpu, base))
                self.assertEqual(bytes(received), dump)
                state = cpu.midi_state()
                self.assertEqual((state["queued"], state["delivered"], state["ignored"], state["overruns"], state["fifo"]),
                                 (0, 40, 3, 0, 0))
                self.assertEqual(cpu.state()["cycles"], start + 40 * CHARACTER)
                # A queue left unread overruns like the real line: one byte lost per character time.
                cpu.midi_in(bytes(range(18)))
                run(18 * CHARACTER)
                state = cpu.midi_state()
                self.assertEqual((state["fifo"], state["overruns"], state["line_errors"]), (16, 2, 2))
                self.assertEqual(self.get(cpu, base + 0x14) & 3, 3)
                self.assertEqual(cpu.midi_state()["line_errors"], 0)   # LSR read cleared OE; the count stays
                self.assertEqual(cpu.midi_state()["overruns"], 2)
                self.put(cpu, base + 8, 3)
                # The instant path is unchanged: seventeen bytes at once overrun a sixteen-byte FIFO.
                cpu.uart_receive(0, bytes(range(17)))
                state = cpu.midi_state()
                self.assertEqual((state["fifo"], state["overruns"], state["delivered"]), (16, 3, 58))
                # The character time follows the programmed divisor and format.
                self.put(cpu, base + 8, 3)
                self.put(cpu, base + 0x20, 0xba)
                self.put(cpu, base + 0x24, 0)     # divisor 186: 62,500 baud
                self.put(cpu, base + 0xc, 7)      # two stop bits: 11-bit characters
                self.assertEqual(cpu.midi_state()["character_cycles"], 11 * 16 * 186 * 2)
                cpu.midi_in(b"ab")
                run(11 * 16 * 186 * 2 * 2 - 1)
                self.assertEqual(cpu.midi_state()["fifo"], 1)
                run(1)
                self.assertEqual([self.get(cpu, base), self.get(cpu, base)], [ord("a"), ord("b")])
                with self.assertRaisesRegex(ValueError, "MIDI input must be bytes"):
                    cpu.midi_in(0x90)
                results.append((cpu.state()["cycles"], cpu.midi_state()))
        self.assertEqual(results[0], results[1])

    def test_uart_sent_cycles_and_midi_loopback(self):
        CHARACTER = 119040
        with self.machine() as cpu:
            base = self.configure_midi(cpu)
            start = cpu.state()["cycles"]
            for byte in (0xf8, 0xf2, 0x10):
                self.put(cpu, base, byte)
            cpu.run(2 * CHARACTER)
            self.assertEqual(cpu.uart_sent(0), (b"\xf8\xf2", 2))
            self.assertEqual(cpu.uart_sent(0, cycles=True), (b"\xf8\xf2", 2, [start + CHARACTER, start + 2 * CHARACTER]))
            cpu.run(CHARACTER + 5000)
            self.assertEqual(cpu.uart_sent(0, 2, cycles=True), (b"\x10", 3, [start + 3 * CHARACTER]))
            self.assertEqual(cpu.uart_sent(0, 3, cycles=True), (b"", 3, []))
            self.assertEqual(cpu.midi_state()["fifo"], 0)   # no cable: nothing comes back
            # A byte written later is stamped from its own start, not from the previous byte's end.
            later = cpu.state()["cycles"]
            self.put(cpu, base, 0xfa)
            cpu.run(CHARACTER)
            self.assertEqual(cpu.uart_sent(0, 3, cycles=True), (b"\xfa", 4, [later + CHARACTER]))
            cpu.midi_loopback()
            self.assertTrue(cpu.midi_state()["loopback"])
            with self.assertRaisesRegex(ValueError, "cabled to MIDI OUT"):
                cpu.midi_in(b"\x90")
            begin = cpu.state()["cycles"]
            for byte in (0x90, 0x40, 0x7f):
                self.put(cpu, base, byte)
            cpu.run(CHARACTER - 1)
            self.assertEqual(self.get(cpu, base + 0x14) & 1, 0)
            cpu.run(1)
            self.assertEqual((self.get(cpu, base + 0x14) & 1, self.get(cpu, base)), (1, 0x90))
            cpu.run(CHARACTER - 1)
            self.assertEqual(self.get(cpu, base + 0x14) & 1, 0)   # the next arrives a character time later
            cpu.run(CHARACTER + 1)
            self.assertEqual([self.get(cpu, base), self.get(cpu, base)], [0x40, 0x7f])
            state = cpu.midi_state()
            self.assertEqual((state["looped"], state["delivered"], state["overruns"]), (3, 0, 0))
            self.assertEqual(cpu.uart_sent(0, 4, cycles=True)[2], [begin + n * CHARACTER for n in (1, 2, 3)])
            cpu.midi_loopback(False)
            self.put(cpu, base, 0xfe)
            cpu.run(CHARACTER)
            self.assertEqual((cpu.uart_sent(0, 7)[0], cpu.midi_state()["fifo"]), (b"\xfe", 0))
            cpu.midi_in(b"\x80")
            with self.assertRaisesRegex(ValueError, "queued bytes"):
                cpu.midi_loopback()
            # Without its pins UART0 sends nothing, so nothing loops back either.
            cpu.run(CHARACTER)
            cpu.midi_loopback()
            self.put(cpu, 0x01c1412c, 0)
            self.put(cpu, base, 0x55)
            cpu.run(2 * CHARACTER)
            self.assertEqual((cpu.uart_sent(0)[1], cpu.midi_state()["looped"]), (8, 3))
        with self.machine() as cpu:   # the ring keeps the latest 4096 bytes and their cycles together
            base = self.configure_midi(cpu)
            for index in range(4100):
                self.put(cpu, base, index & 0xff)
                cpu.run(CHARACTER)
            data, total, cycles = cpu.uart_sent(0, cycles=True)
            self.assertEqual((total, len(data), len(cycles), data[0], data[-1]), (4100, 4096, 4096, 4, 4099 & 0xff))
            self.assertEqual({b - a for a, b in zip(cycles, cycles[1:])}, {CHARACTER})

    def test_scheduled_gpio_edges_raise_the_bank_interrupt_at_their_cycle(self):
        results = []
        for slice_cycles in (997, 50000000):
            with self.machine() as cpu:
                def run(cycles):
                    while cycles:
                        part = min(cycles, slice_cycles); cpu.run(part); cycles -= part
                self.enable_module(cpu, 0x01e27000, 3)
                self.put(cpu, 0x01800104, 72)        # GPIO bank 7 -> CPU interrupt 4
                self.put(cpu, 0x01e26008, 1 << 7)
                self.put(cpu, 0x01e2609c, 1 << 24)   # GP7[8] rising-edge interrupt
                now = cpu.state()["cycles"]
                with self.assertRaisesRegex(ValueError, "in the past"):
                    cpu.gpio_schedule(7, 8, True, now - 1)
                cpu.gpio_schedule(7, 8, False, now + 3000)   # given out of order
                cpu.gpio_schedule(7, 8, True, now + 1000)
                self.assertEqual(cpu.gpio_scheduled(), 2)
                run(999)
                self.assertEqual((cpu.state()["registers"]["ifr"], self.get(cpu, 0x01e260ac)), (0, 0))
                run(1)
                self.assertEqual(cpu.state()["registers"]["ifr"], 1 << 4)
                self.assertEqual((self.get(cpu, 0x01e260ac), self.get(cpu, 0x01e26098) >> 24 & 1), (1 << 24, 1))
                self.put(cpu, 0x01e260ac, 1 << 24)
                cpu.set_register("ifr", 0)
                run(2000)
                self.assertEqual((self.get(cpu, 0x01e26098) >> 24 & 1, cpu.state()["registers"]["ifr"]), (0, 0))  # falling: no interrupt
                self.assertEqual(cpu.gpio_scheduled(), 0)
                # Two levels in one cycle apply in the order given: a pulse of no width still latches its edge.
                now = cpu.state()["cycles"]
                cpu.gpio_schedule(7, 8, True, now + 10)
                cpu.gpio_schedule(7, 8, False, now + 10)
                run(10)
                self.assertEqual((self.get(cpu, 0x01e260ac), self.get(cpu, 0x01e26098) >> 24 & 1), (1 << 24, 0))
                self.put(cpu, 0x01e260ac, 1 << 24)
                cpu.set_register("ifr", 0)
                # A pulse train: 2 pulses per quarter note at 120 BPM is one every 250 ms, 15 ms wide.
                start = cpu.state()["cycles"] + 372000
                self.assertEqual(cpu.sync_in(120, 3, start), start + 3 * 93000000)
                self.assertEqual(cpu.gpio_scheduled(), 6)
                edges = []
                for at in (start, start + 5580000, start + 93000000, start + 98580000):
                    run(at - cpu.state()["cycles"] - 1)
                    before = self.get(cpu, 0x01e26098) >> 24 & 1
                    run(1)
                    edges.append((before, self.get(cpu, 0x01e26098) >> 24 & 1, self.get(cpu, 0x01e260ac) >> 24))
                    self.put(cpu, 0x01e260ac, 1 << 24)
                self.assertEqual(edges, [(0, 1, 1), (1, 0, 0), (0, 1, 1), (1, 0, 0)])
                # The clock stops: the third pulse never comes, and one cut short returns to idle.
                run(start + 2 * 93000000 + 1000 - cpu.state()["cycles"])
                self.assertEqual(self.get(cpu, 0x01e26098) >> 24 & 1, 1)
                cpu.sync_in_stop()
                self.assertEqual((cpu.gpio_scheduled(), self.get(cpu, 0x01e26098) >> 24 & 1), (0, 0))
                self.put(cpu, 0x01e260ac, 1 << 24)
                cpu.set_register("ifr", 0)
                run(93000000)
                self.assertEqual((cpu.state()["registers"]["ifr"], self.get(cpu, 0x01e260ac)), (0, 0))
                # A tempo that does not divide the clock keeps exact long-run timing; other pins are untouched
                # by clearing this one.
                now = cpu.state()["cycles"]
                cpu.gpio_schedule(0, 1, True, now + 5)
                self.assertEqual(cpu.sync_in(133.3, 7, now) - now, round(7 * 372000000 * 60 / (133.3 * 2)))
                cpu.gpio_schedule_clear(7, 8)
                self.assertEqual(cpu.gpio_scheduled(), 1)
                for arguments in ((0, 4, now), (120, 1, now, 0), (6000, 1, now)):
                    with self.assertRaisesRegex(ValueError, "expected"):
                        cpu.sync_in(*arguments)
                with self.assertRaisesRegex(ValueError, "shorter than"):
                    cpu.sync_in(1000, 1, now, 96, 15)
                results.append(cpu.state()["cycles"])
        self.assertEqual(results[0], results[1])

    def test_gpio_trace_records_watched_output_changes_with_their_cycle(self):
        with self.machine() as cpu:
            self.enable_module(cpu, 0x01e27000, 3)
            DIR, SET, CLR, OUT = 0x01e26088, 0x01e26090, 0x01e26094, 0x01e2608c
            pin9, pin10 = 1 << 25, 1 << 26
            self.assertEqual(cpu.gpio_trace(), ([], 0))
            self.put(cpu, SET, pin9)                         # an input's latch drives nothing
            self.put(cpu, DIR, 0xffffffff & ~pin9)           # an output, but PINMUX17 has not put GP7[9] on its pin
            self.assertEqual(cpu.gpio_trace(), ([], 0))
            cpu.run(100)
            first = cpu.state()["cycles"]
            self.put(cpu, 0x01c14164, 0x88)                  # PINMUX17 nibbles 0, 1 = 8: the pin now drives its latch
            self.assertEqual(cpu.gpio_trace(), ([dict(bank=7, pin=9, high=True, cycles=first)], 1))
            self.put(cpu, SET, pin9)                         # no change of level, no row
            cpu.run(5580000)
            self.put(cpu, CLR, pin9 | pin10)
            cpu.run(1000)
            self.put(cpu, OUT, pin9)                         # a whole-word write counts like SET
            self.put(cpu, DIR, 0xffffffff & ~(pin9 | pin10)) # GP7[10] is not watched
            self.put(cpu, SET, pin10)
            rows, total = cpu.gpio_trace()
            self.assertEqual((total, [(row["high"], row["cycles"] - first) for row in rows]),
                             (3, [(True, 0), (False, 5580000), (True, 5581000)]))
            self.assertEqual(cpu.gpio_trace(2), (rows[2:], 3))
            # Watching a pin that already drives starts with its level; unwatching stops its rows.
            cpu.run(10)
            cpu.gpio_watch(7, 10)
            cpu.gpio_watch(7, 10)
            cpu.gpio_watch(7, 9, False)
            self.put(cpu, CLR, pin9 | pin10)
            rows, total = cpu.gpio_trace(3)
            self.assertEqual([(row["pin"], row["high"], row["cycles"] - first) for row in rows],
                             [(10, True, 5581010), (10, False, 5581010)])
            # Made an input again and back: the level it drives on return is a row even if it is the old one.
            self.put(cpu, DIR, 0xffffffff)
            self.put(cpu, DIR, 0xffffffff & ~pin10)
            self.assertEqual([row["high"] for row in cpu.gpio_trace(5)[0]], [False])
            # The latest 4096 rows are kept.
            for index in range(4100):
                self.put(cpu, SET if index % 2 == 0 else CLR, pin10)
            rows, total = cpu.gpio_trace()
            self.assertEqual((total, len(rows), rows[-1]["high"], rows[0]["high"]), (4106, 4096, False, True))
            with self.assertRaisesRegex(ValueError, "expected GPIO"):
                cpu.gpio_watch(9, 0)

    def test_syscfg_protected_writes_require_both_unlock_keys(self):
        with self.machine() as cpu:
            self.put(cpu, 0x01c14038, 0)
            self.put(cpu, 0x01c1403c, 0)
            self.put(cpu, 0x01c14170, 123)
            self.assertEqual(self.get(cpu, 0x01c14170), 0)
            self.put(cpu, 0x01c14038, 0x83e70b13)
            self.put(cpu, 0x01c14170, 123)
            self.assertEqual(self.get(cpu, 0x01c14170), 0)
            self.put(cpu, 0x01c1403c, 0x95a4f1e0)
            self.put(cpu, 0x01c14170, 123)
            self.assertEqual(self.get(cpu, 0x01c14170), 123)

    def test_timer_count_period_event_and_disabled_counter(self):
        with self.machine() as cpu:
            self.put(cpu, 0x01c20018, 3)
            self.put(cpu, 0x01c20024, 5)
            self.put(cpu, 0x01c20020, 0x80)
            cpu.run(46)
            self.assertEqual(self.get(cpu, 0x01c20010), 2)
            self.assertEqual(cpu.state()["registers"]["ifr"], 0)
            cpu.run(1)
            self.assertEqual(self.get(cpu, 0x01c20010), 3)
            self.assertEqual(cpu.state()["registers"]["ifr"], 1 << 4)
            cpu.set_register("ifr", 0)
            cpu.run(61)
            self.assertEqual(cpu.state()["registers"]["ifr"], 0)
            cpu.run(1)
            self.assertEqual(cpu.state()["registers"]["ifr"], 1 << 4)
            self.put(cpu, 0x01c20020, 0)
            counter = self.get(cpu, 0x01c20010)
            cpu.run(500)
            self.assertEqual(self.get(cpu, 0x01c20010), counter)

    def test_timer_64_bit_mode_counts_through_both_halves_and_matches_the_64_bit_period(self):
        with self.machine() as cpu:
            # As the stock firmware runs TIMER64P1 while USB audio streams: TGCR 0x13, both periods all ones.
            for offset, value in ((0x18, 0xffffffff), (0x1c, 0xffffffff), (0x24, 0x13), (0x10, 0xfffffffe), (0x20, 0x80)):
                self.put(cpu, 0x01c21000 + offset, value)
            cpu.run(31 * 3)                                               # 6 ticks of 24 MHz
            self.assertEqual((self.get(cpu, 0x01c21010), self.get(cpu, 0x01c21014)), (4, 1))
            cpu.run(31 * 12000000)
            self.assertEqual((self.get(cpu, 0x01c21010), self.get(cpu, 0x01c21014)), (24000004, 1))
            self.assertEqual(cpu.state()["registers"]["ifr"], 0)
            self.put(cpu, 0x01c21020, 0)                                  # disabled: the count stays
            cpu.run(500)
            self.assertEqual(self.get(cpu, 0x01c21010), 24000004)
            self.put(cpu, 0x01c21024, 0)                                  # both halves in reset
            self.assertEqual((self.get(cpu, 0x01c21010), self.get(cpu, 0x01c21014)), (0, 0))
        with self.machine() as cpu:
            # A period across both halves on timer 0: the event at the match, then from zero again.
            for offset, value in ((0x18, 3), (0x1c, 1), (0x24, 0x03), (0x10, 0xfffffffe), (0x20, 0x80)):
                self.put(cpu, 0x01c20000 + offset, value)
            cpu.run(77)                                                   # 4 of the 5 ticks to 0x1_00000003
            self.assertEqual(((self.get(cpu, 0x01c20010), self.get(cpu, 0x01c20014)), cpu.state()["registers"]["ifr"]), ((2, 1), 0))
            cpu.run(1)
            self.assertEqual(cpu.state()["registers"]["ifr"], 1 << 4)
            cpu.run(31)
            self.assertEqual((self.get(cpu, 0x01c20010), self.get(cpu, 0x01c20014)), (1, 0))
            with self.assertRaisesRegex(ValueError, "not implemented"):
                self.put(cpu, 0x01c20024, 0x0b)                           # the chained mode is still not modelled

    def test_each_timer_raises_its_own_event(self):
        # DSP event numbers of the C6748: T64P0_TINT12 4, T64P1_TINT12 40, T64P2_TINTALL 25, T64P3_TINTALL 86.
        for base, number in ((0x01c20000, 4), (0x01c21000, 40), (0x01f0c000, 25), (0x01f0d000, 86)):
            with self.subTest(timer=hex(base)), self.machine() as cpu:
                self.put(cpu, 0x01800104, 0x07060000 | number << 8 | 0x7f)   # interrupt 5 takes this event, 4 an unused one
                self.put(cpu, base + 0x18, 3)
                self.put(cpu, base + 0x24, 5)
                self.put(cpu, base + 0x20, 0x80)
                cpu.run(200)
                self.assertEqual(cpu.state()["registers"]["ifr"], 1 << 5)

    def test_wait_timer_edge_and_interrupt_entry_match_every_cycle_reference(self):
        observations = []
        for eager, sliced in ((False, False), (True, False), (False, True)):
            with self.subTest(eager=eager, sliced=sliced), self.machine() as cpu:
                cpu.board_eager_polling(eager)
                cpu.map(0x2000, 4096, 7)
                self.install_handler(cpu, 4)
                cpu.set_register("istp", 0x2000)
                cpu.set_register("ier", 0x12)
                cpu.set_register("csr", 0x101)
                self.put(cpu, 0x01c20018, 3)
                self.put(cpu, 0x01c20024, 5)
                self.put(cpu, 0x01c20020, 0x40)  # one shot; Timer0 event at cycle 47
                cpu.profile_guest(1)
                rows = []
                for boundary in (46, 47, 48, 49, 57, 58, 70, 80):
                    while cpu.state()["cycles"] < boundary:
                        state = cpu.run(1 if sliced else boundary - cpu.state()["cycles"])
                    rows.append(state)
                self.assertEqual(rows[0]["registers"]["ifr"], 0)
                self.assertEqual(rows[1]["registers"]["ifr"], 16)
                self.assertEqual(rows[2]["interrupt_count"], 0)  # branch delay ends at 48
                self.assertEqual(rows[3]["interrupt_count"], 1)
                self.assertEqual(rows[3]["registers"]["irp"], 0x1000)
                self.assertEqual(rows[4]["pc"], 0x2080)  # nine-cycle interrupt entry
                self.assertEqual(rows[-1]["registers"]["a8"], 1)
                p = cpu.guest_profile()
                self.assertEqual((p["cycles"], p["interrupts"], p["interrupt_entry_cycles"]), (80, 1, 9))
                self.assertEqual(sum(p[k] for k in ("issue_cycles", "wait_cycles", "software_loop_cycles", "interrupt_entry_cycles")), 80)
                observations.append(rows)
        self.assertEqual(observations[0], observations[1])
        self.assertEqual(observations[0], observations[2])

    def test_timestamp_enable_ignores_written_value_and_does_not_restart(self):
        with self.machine(["mvc .S2 tscl,b5", "mvc .S2 b0,tscl", "mvc .S2 tscl,b1",
                           "mvc .S2 tscl,b2", "mvc .S2 b0,tscl", "mvc .S2 tscl,b4"]) as cpu:
            cpu.set_register("b0", 0xffffffff)
            state = cpu.run(100)
            self.assertEqual(state["registers"]["b5"], 0)
            self.assertEqual(state["registers"]["b1"], 0)
            self.assertEqual(state["registers"]["b2"], 1)
            self.assertEqual(state["registers"]["b4"], 3)

    def test_dint_and_rint_save_and_restore_global_interrupt_enable(self):
        with self.machine(["dint", "mvc .S2 csr,b4", "mvc .S2 tsr,b5", "rint", "mvc .S2 csr,b6"]) as cpu:
            cpu.set_register("csr", 3)
            state = cpu.run(100)
            self.assertEqual(state["registers"]["b4"], 2)
            self.assertEqual(state["registers"]["b5"], 2)
            self.assertEqual(state["registers"]["b6"], 3)

    def test_local_and_global_ram_alias_share_backing_storage(self):
        with CPU(self.work, decode=False) as cpu:
            cpu.map(0x11f00000, 32768, 3)
            cpu.alias(0x00f00000, 0x11f00000, 32768)
            cpu.write(0x00f00004, b"local")
            self.assertEqual(cpu.read(0x11f00004, 5), b"local")
            cpu.write(0x11f00008, b"global")
            self.assertEqual(cpu.read(0x00f00008, 6), b"global")

    def test_isr_icr_one_delay_slot_and_write_only_reads(self):
        with self.machine(["mvc .S2 b4,isr", "mvc .S2 ifr,b5", "mvc .S2 ifr,b6",
                           "mvc .S2 b4,icr", "mvc .S2 ifr,b7", "mvc .S2 ifr,b8", "mvc .S2 isr,b9"]) as cpu:
            cpu.set_register("b4", 1 << 6)
            state = cpu.run(100)
            self.assertEqual([state["registers"][r] for r in ("b5", "b6", "b7", "b8", "b9")], [0, 64, 64, 0, 0])

    def install_handler(self, cpu, number, texts=None):
        if texts is None:
            texts = ["add .L1 1,a8,a8", "mvc .S2 itsr,b9", "b .S2 irp", "nop 5"]
        start = 0x2000 + number * 32
        for index, text in enumerate(texts):
            address = start + index * 4
            cpu.install(address, address + 4, False, address & ~31, 32, (Instruction * 1)(instruction(address, text)))

    def test_maskable_interrupt_priority_latency_context_and_return_across_slices(self):
        states = []
        for sliced in (False, True):
            with self.subTest(sliced=sliced), self.machine(["mvk .S1 42,a4"]) as cpu:
                cpu.map(0x2000, 4096, 7)
                self.install_handler(cpu, 4)
                self.install_handler(cpu, 5)
                cpu.set_register("istp", 0x2000)
                cpu.set_register("ier", 0x32)
                cpu.set_register("csr", 0x101)
                cpu.set_register("tsr", 0x49)
                cpu.set_register("ifr", 0x30)
                state = cpu.run(1)
                self.assertEqual(state["registers"]["irp"], 0x1000)
                self.assertEqual(state["registers"]["itsr"], 0x49)
                self.assertEqual(state["registers"]["tsr"], 0x200)
                self.assertEqual(state["registers"]["csr"] & 3, 2)
                self.assertEqual(state["interrupt_count"], 1)
                state = cpu.run(8)
                self.assertEqual(state["pc"], 0x2080)
                self.assertEqual(state["registers"]["ifr"], 0x20)
                state = cpu.run(1 if sliced else 100)
                while state["status"] == "budget":
                    state = cpu.run(1)
                self.assertEqual(state["status"], "returned")
                self.assertEqual(state["interrupt_count"], 2)
                self.assertEqual(state["registers"]["a8"], 2)
                self.assertEqual(state["registers"]["a4"], 42)
                self.assertEqual(state["registers"]["tsr"], 0x49)
                self.assertEqual(state["registers"]["csr"] & 3, 3)
                self.assertEqual(state["registers"]["ifr"], 0)
                states.append(state)
        self.assertEqual(states[0], states[1])

    def test_untaken_branch_blocks_interrupts_for_five_delay_slots(self):
        with self.machine(["[a0] b .S1 00001000", *(["nop"] * 5), "nop"]) as cpu:
            cpu.map(0x2000, 4096, 7)
            self.install_handler(cpu, 4)
            cpu.set_register("istp", 0x2000)
            cpu.set_register("ier", 0x12)
            cpu.set_register("csr", 0x101)
            cpu.run(1)
            cpu.set_register("ifr", 0x10)
            self.assertEqual(cpu.run(5)["interrupt_count"], 0)
            self.assertEqual(cpu.run(1)["interrupt_count"], 1)
            self.assertEqual(cpu.state()["registers"]["irp"], 0x1018)


if __name__ == "__main__":
    unittest.main()
