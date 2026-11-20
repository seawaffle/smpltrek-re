#!/usr/bin/env python3
"""SYNC IN / SYNC OUT of SmplTrek 3.2.174, run in c6sim: pin set-up, polarity, pulse shape and rate, and the SYNC IN
edge path. Read-only and simulated. GPIO register names are TI's (SPRUH79C Table 19-2, section 19.3: banks 6 and 7
share DIR67 0x01E26088, SET_DATA67 0x90, CLR_DATA67 0x94, SET_RIS_TRIG67 0x9C, CLR_RIS_TRIG67 0xA0, SET_FAL_TRIG67
0xA4, CLR_FAL_TRIG67 0xA8, INTSTAT67 0xAC; GP7[n] is bit 16 + n). The GPIO block these functions sit in is the same
168 instructions in Lofi-12 XT 1.5.205 and CyDrums 1.1.84 (docs/01-platform-map.md, "GPIO"), so only SmplTrek is run.

The functions (SmplTrek addresses):
  0xC1671EE0  pin handles: StarterWare pin numbers 121 (GP7[8]) at B14+384, 122 (GP7[9]) at B14+388; clears the sync
              object 0xC1504350 (+0 delegate, +4 POLARITY OUT, +8 millisecond counter, +12 edge flag)
  0xC16720D8  set-up: PINMUX17 nibbles 0, 1 = 8, GP7[9] output low, GP7[8] rising-edge interrupt, counter 0
  0xC167208C  POLARITY IN: 1 -> rising edge, else falling edge (settings_apply_all passes g_settings+0x08)
  0xC1671F24  pulse start (from the clock-position handler): only when the counter has reached 60
  0xC1671F80  every 1 ms (a SYS/BIOS Clock object, period 1 tick, function 0xC169CCC0): counts, ends the pulse at 15,
              and passes a pending SYNC IN edge to the delegate's slot 0
  0xC1672134  gpio_bank_isr (GPIO_B7INT, event 72, SPRUH79C Table 2-1): GP7[8] interrupt -> clear INTSTAT, set the edge flag
  0xC154A264  clock-position handler: MIDI clock (midi_send_clock 0xC16190E0) at positions divisible by 3 when its
              gate allows, sync pulse start at positions 0 and 36

The internal sequencer clock object (0xC1504310, the one audio_render_main advances when SOURCE is
INTERNAL): +0 phase accumulator, +4 increment per sample, +8 position, +12 delegate.
  0xC1681874  set tempo (obj, tempo x 10): +4 = 72 x tempo x 10
  0xC16816F4  steps to samples (steps, tempo x 10) = steps x 28,800,000 / (72 x tempo x 10)
  0xC1681738  advance (obj, frames): +0 += frames x +4; each time it passes 28,800,000 (= 48,000 x 60 x 10) the
              position steps and wraps at 72, delegate slot 0 is called (obj), then slot 1 (obj, position) on a later
              block. So 72 steps per quarter note, at most one step per 128-frame block in this test.

SYNC IN to tempo. The sync object's delegate (+0) is MainDelegate's SyncClockReceiverDelegate base (this + 20, set in
0xC154A620); its slot 0 (thunk 0xC154A224 -> 0xC154A1F0) passes each edge, unless 0xC1652680() is non-zero, to
0xC165F5EC(0xC1501FE8, 0), an external-clock object built by the static initialiser 0xC16A1BB8 with +0 = 36 steps per
edge (fixed: no setting writes it). 0xC165F5EC sets +32 = 1 and counts +36 down; at 0 it calls the beat function
0xC165F214 and reloads +36 = 72 / (+0) = 2 edges, so SYNC IN is 2 PPQN like SYNC OUT. The beat function takes the
millisecond tick (0xC16ACDA0) minus the last beat (B14+1320); intervals of 2000 ms or more are dropped. The rest go into
a four-entry ring (+44.., index +60), and tempo x 10 = 2,400,000 / (sum of the four) (4 x 60,000 ms x 10). A change of
more than 5.0 BPM from the current tempo (+40) refills the ring with the new interval. When the tempo changes, the
object's delegate (+28) slot 2 gets (obj, tempo x 10). sync_in_tempo() runs this with a hooked clock.
Steps between edges: with SOURCE not INTERNAL the audio code (0xC159AC58) runs 0xC165F40C(obj, 128) once per block
instead of the internal clock. Nothing steps before the first beat. After it, each edge allows 36 steps, spaced at the
current tempo (72 per beat, at most one per block at normal tempos) and sent to the delegate's slot 1 with the
position (0-71). Steps still owed when an edge arrives are all sent in the next block; when the 36 are sent before
the next edge, the clock waits for it. sync_in_steps() runs this.

Usage (from the repository root; needs firmware/ and work/smpltrek-3.2.174.dis):
  python3 -B analysis/sync_map.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

OBJ = 0xC1504350
HANDLES, SETUP, POL_IN, PULSE, MS_TICK, ISR = 0xC1671EE0, 0xC16720D8, 0xC167208C, 0xC1671F24, 0xC1671F80, 0xC1672134
POSITION = 0xC154A264
MIDI_CLOCK, CLOCK_GATE = 0xC16190E0, 0xC1571160
CLOCK, SET_TEMPO, STEPS_TO_SAMPLES, ADVANCE = 0xC1504310, 0xC1681874, 0xC16816F4, 0xC1681738
PINMUX17 = 0x01C14164
GPIO = {0x88: "DIR67", 0x90: "SET_DATA67", 0x94: "CLR_DATA67", 0x9C: "SET_RIS_TRIG67", 0xA0: "CLR_RIS_TRIG67",
        0xA4: "SET_FAL_TRIG67", 0xA8: "CLR_FAL_TRIG67", 0xAC: "INTSTAT67"}
FAKE_DELEGATE, FAKE_VTABLE, FAKE_SLOT0 = 0xC0002000, 0xC0002100, 0xC0003000
EXT_CLOCK, EXT_FEED, MS_NOW, EXT_ADVANCE = 0xC1501FE8, 0xC165F5EC, 0xC16ACDA0, 0xC165F40C


class Session:
    def __init__(self):
        import c6sim
        import hw_compare
        import mmio_trace
        self.c6sim = c6sim
        self.t = mmio_trace.Trace(str(hw_compare.ROOT / hw_compare.PRODUCTS["smpltrek"]["image"]), "smpltrek")
        self.t.boot()
        self.hooks = {a: c6sim.returns(1 if a == 0xC16A1BF0 else 0) for a in hw_compare.HOOKS}
        self.b14 = self.t.boot_state.cfg["b14"]
        self.reset()

    def reset(self):
        self.t.state = dict(self.t.boot_state.overlay)
        self.t.regs = {}

    def word(self, address):
        return sum(self.t.state.get(address + i, 0) << (8 * i) for i in range(4))

    def poke(self, address, value):
        for i in range(4):
            self.t.state[address + i] = (value >> (8 * i)) & 0xFF

    def call(self, fn, regs=None, hooks=None, regs_mmio=None):
        self.t.regs = dict(regs_mmio or {})
        _, log = self.t.run(fn, regs or {}, hooks={**self.hooks, **(hooks or {})}, max_cycles=400000)
        return [("PINMUX17" if a.address == PINMUX17 else GPIO.get(a.address - 0x01E26000, hex(a.address)), a.value)
                for a in log if a.kind == "W" and (0x01E26000 <= a.address < 0x01E26100 or a.address == PINMUX17)]

    def setup(self):
        """(pin handles, set-up writes, POLARITY IN 0 writes, POLARITY IN 1 writes)."""
        self.reset()
        self.call(HANDLES)
        handles = (self.word(self.b14 + 384), self.word(self.b14 + 388))
        writes = self.call(SETUP, {"a4": OBJ})
        return handles, writes, self.call(POL_IN, {"a4": OBJ, "b4": 0}), self.call(POL_IN, {"a4": OBJ, "b4": 1})

    def pulse(self, polarity_out):
        """[(ms, writes)] for one pulse: start at ms 0, then the 1 ms function 70 times."""
        self.reset()
        self.call(HANDLES)
        self.call(SETUP, {"a4": OBJ})
        self.poke(OBJ + 8, 60)                      # the previous pulse is over
        self.poke(OBJ + 4, polarity_out)
        out = [(0, self.call(PULSE, {"a4": OBJ}))]
        for ms in range(1, 71):
            w = self.call(MS_TICK, {"a4": OBJ, "b4": ms})
            if w:
                out.append((ms, w))
        retrigger = self.call(PULSE, {"a4": OBJ})   # counter back at 60 after the 1 ms calls: a new pulse may start
        return out, retrigger

    def early_retrigger(self):
        """Writes of a pulse start 30 ms after the previous one (counter 30)."""
        self.reset()
        self.call(HANDLES)
        self.call(SETUP, {"a4": OBJ})
        self.poke(OBJ + 8, 30)
        return self.call(PULSE, {"a4": OBJ})

    def sync_in_edge(self):
        """(ISR writes, edge flag, delegate calls on the next 1 ms tick)."""
        self.reset()
        self.call(HANDLES)
        self.call(SETUP, {"a4": OBJ})
        self.poke(FAKE_DELEGATE, FAKE_VTABLE)
        self.poke(FAKE_VTABLE, FAKE_SLOT0)
        self.poke(OBJ, FAKE_DELEGATE)
        calls = []

        def slot0(m):
            calls.append((m.R["a4"], m.R["b4"]))
            return m.R["b3"]

        isr = self.call(ISR, regs_mmio={0x01E260AC: 1 << 24})
        flag = self.t.state.get(OBJ + 12, 0)
        self.call(MS_TICK, {"a4": OBJ, "b4": 0}, hooks={FAKE_SLOT0: slot0})
        return isr, flag, calls, self.t.state.get(OBJ + 12, 0)

    def clock(self, tempo_x10, blocks, frames=128):
        """(increment, samples per step, [(block, slot, position)]) for the internal clock over `blocks` blocks."""
        self.reset()
        self.t.run(SET_TEMPO, {"a4": CLOCK, "b4": tempo_x10}, hooks=self.hooks)
        inc = self.word(CLOCK + 4)
        sps, _ = self.t.run(STEPS_TO_SAMPLES, {"a4": 1, "b4": tempo_x10}, hooks=self.hooks)
        self.poke(CLOCK + 0, 0)
        self.poke(CLOCK + 8, 0)
        self.poke(FAKE_DELEGATE, FAKE_VTABLE)
        self.poke(FAKE_VTABLE, FAKE_SLOT0)
        self.poke(FAKE_VTABLE + 4, FAKE_SLOT0 + 0x100)
        self.poke(CLOCK + 12, FAKE_DELEGATE)
        events, block = [], [0]

        def slot(n):
            def h(m):
                events.append((block[0], n, m.R.get("a6", 0) if n else None))
                return m.R["b3"]
            return h

        hooks = {FAKE_SLOT0: slot(0), FAKE_SLOT0 + 0x100: slot(1)}
        for block[0] in range(blocks):
            self.t.run(ADVANCE, {"a4": CLOCK, "b4": frames}, hooks={**self.hooks, **hooks}, max_cycles=400000)
        return inc, sps, events

    def sync_in_tempo(self, periods_ms):
        """[tempo x 10 after each edge] for SYNC IN edges `periods_ms` apart (first edge at the first period)."""
        self.reset()
        self.poke(FAKE_DELEGATE, FAKE_VTABLE)
        self.poke(FAKE_VTABLE + 8, FAKE_SLOT0)
        self.poke(EXT_CLOCK + 28, FAKE_DELEGATE)
        now, out = [0], []

        def clock(m):
            m.R["a4"] = now[0]
            return m.R["b3"]
        hooks = {**self.hooks, MS_NOW: clock, FAKE_SLOT0: lambda m: m.R["b3"]}
        for p in periods_ms:
            now[0] += p
            self.t.run(EXT_FEED, {"a4": EXT_CLOCK, "b4": 0}, hooks=hooks, max_cycles=400000)
            out.append(self.word(EXT_CLOCK + 40))
        return out

    def sync_in_steps(self, periods_ms, blocks):
        """[(ms, position)] from the external clock: SYNC IN edges `periods_ms` apart (the last repeats) are fed to
        EXT_FEED, and EXT_ADVANCE (obj, 128) runs once per 128-frame block (2.67 ms), as audio code 0xC159AC58 does
        when SOURCE is not INTERNAL. Positions are the delegate (+28) slot 1 calls; ms is the block's time."""
        self.reset()
        self.poke(FAKE_DELEGATE, FAKE_VTABLE)
        for k in range(4):
            self.poke(FAKE_VTABLE + 4 * k, FAKE_SLOT0 + 0x100 * k)
        self.poke(EXT_CLOCK + 28, FAKE_DELEGATE)
        now, out = [0], []

        def clock(m):
            m.R["a4"] = now[0]
            return m.R["b3"]

        def position(m):
            out.append((now[0], m.R.get("a6", 0)))
            return m.R["b3"]
        hooks = {**self.hooks, MS_NOW: clock, FAKE_SLOT0 + 0x100: position}
        hooks.update({FAKE_SLOT0 + 0x100 * k: (lambda m: m.R["b3"]) for k in (0, 2, 3)})
        edge, n = periods_ms[0], 0
        for b in range(blocks):
            t = b * 128 / 48
            while edge <= t:
                now[0] = int(edge)
                self.t.run(EXT_FEED, {"a4": EXT_CLOCK, "b4": 0}, hooks=hooks, max_cycles=400000)
                n += 1
                edge += periods_ms[min(n, len(periods_ms) - 1)]
            now[0] = int(t)
            self.t.run(EXT_ADVANCE, {"a4": EXT_CLOCK, "b4": 128}, hooks=hooks, max_cycles=400000)
        return out

    def positions(self, gate, last=79):
        """{position: events} from the clock-position handler, MIDI clock and pulse start recorded, not run."""
        out = {}
        for pos in range(last + 1):
            self.reset()
            ev = []

            def rec(name, ret=0):
                def h(m):
                    ev.append(name)
                    m.R["a4"] = ret
                    return m.R["b3"]
                return h

            hooks = {PULSE: rec("pulse"), MIDI_CLOCK: rec("midi clock"), CLOCK_GATE: rec("gate", gate)}
            try:
                self.call(POSITION, {"a4": 0xC0005000, "b4": 0, "a6": pos}, hooks=hooks)
            except Exception:       # after these calls the handler goes on into sequencer code the test does not set up
                pass
            ev = [e for e in ev if e != "gate"]
            if ev:
                out[pos] = ev
        return out


def main():
    s = Session()
    handles, writes, pol0, pol1 = s.setup()
    print(f"pin handles {handles}; set-up {[(n, hex(v)) for n, v in writes]}")
    print(f"POLARITY IN 0 {[(n, hex(v)) for n, v in pol0]}; 1 {[(n, hex(v)) for n, v in pol1]}")
    for p in (0, 1):
        seq, again = s.pulse(p)
        print(f"POLARITY OUT {p}: {[(ms, [(n, hex(v)) for n, v in w]) for ms, w in seq]}; restart at 60 ms "
              f"{[(n, hex(v)) for n, v in again]}")
    print(f"start 30 ms after the last: {s.early_retrigger()}")
    isr, flag, calls, after = s.sync_in_edge()
    print(f"SYNC IN edge: ISR {[(n, hex(v)) for n, v in isr]}, flag {flag}; next ms: delegate slot 0 calls "
          f"{[(hex(a), hex(b)) for a, b in calls]}, flag {after}")
    inc, sps, ev = s.clock(1200, 375)
    steps = [e for e in ev if e[1] == 1]
    print(f"internal clock at tempo x10 1200: increment {inc}, {sps} samples per step, {len(steps)} steps in 375 "
          f"blocks (1 s), positions {steps[0][2]}..{max(e[2] for e in steps)}, last {steps[-1][2]}")
    for gate in (0, 1):
        print(f"positions, MIDI clock gate {gate}: {s.positions(gate)}")
    print(f"SYNC IN edges 300 ms apart (100 BPM at 2 PPQN): tempo x 10 {s.sync_in_tempo([300] * 8)}")
    print(f"then 250 ms (120 BPM): {s.sync_in_tempo([300] * 6 + [250] * 6)}")
    steps = s.sync_in_steps([250] * 6 + [200], 720)
    print(f"steps, edges 250 ms then 200 ms apart: {len(steps)}; first {steps[:3]}; around 1700 ms "
          f"{[x for x in steps if 1690 <= x[0] <= 1712]}")


if __name__ == "__main__":
    main()
