#!/usr/bin/env python3
"""Conditional stock WAV preview through its original UI, filesystem, mixer and DMA."""
import argparse
import json
import math
from pathlib import Path
import struct
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_capture import stereo_wav
from build import WORK, digest
from fat_image import FatImage
from media import build_card
from performance import pinned_cpu
from stock import Stock
from stock_session import StockSession, MODAL
from usb_probe import IMAGE_SHA256

WAV_PATH = "/SMPLTREK/POOL/AUDIO/TONE.WAV"


def fixture(path):
    # Distinct frequencies and amplitudes detect channel/phase and PCM conversion errors.
    # The second second is quieter. Checking it and the subsequent wrap prevents
    # a stuck, periodically repeated DMA block from passing a pure-tone test.
    pcm = b"".join(struct.pack("<hh", round((4096 if i < 48000 else 2048) * math.sin(i * math.tau / 64)),
                               round((8192 if i < 48000 else 4096) * math.sin(i * math.tau / 32)))
                   for i in range(96000))
    with wave.open(str(path), "wb") as wav:
        wav.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)


def tones(raw, audio, amplitude_divisor=1):
    values = struct.unpack(f"<{len(raw) // 4}i", raw)
    leading = audio["first_capture_slot"]
    values = values[leading:leading + (len(values) - leading) // 2 * 2]
    result = []
    # On this stock profile the output slots carry source right, then source left,
    # at one-quarter of full 16-to-32-bit scaling. This does not assign physical L/R.
    for slot, period, amplitude in ((0, 32, 8192), (1, 64, 4096)):
        amplitude //= amplitude_divisor
        words = values[slot::2][-4096:]
        expected = [round(amplitude * math.sin(i * math.tau / period)) * 16384 for i in range(period)]
        errors = [max((abs(value - expected[(i + phase) % period]) for i, value in enumerate(words)),
                      default=2**32) for phase in range(period)]
        result.append(dict(slot=slot, source_channel=1 - slot, period_frames=period,
                           frequency_hz=48000 // period, compared_frames=len(words),
                           peak=max(map(abs, words), default=0), max_error=min(errors),
                           phase=errors.index(min(errors))))
    return result


def tail_silent(stock):
    return not any(stock.cpu.audio_output()[0][-4096:])


def _probe(output, slice_cycles, guest_sample_period):
    output.mkdir(parents=True, exist_ok=True)
    tone = output / "tone.wav"; fixture(tone)
    source = tone.read_bytes()
    card = build_card(output / "input.img", {WAV_PATH: tone})
    original = card.read_bytes()
    if FatImage(original).read(WAV_PATH) != source:
        raise RuntimeError("independent FAT reader did not recover the exact WAV fixture")
    checks, reports, matches, artifacts = {}, [], {}, {}
    with Stock(card=card, reserved_low_writes=True) as stock:
        if stock.input["sha256"] != IMAGE_SHA256:
            raise ValueError("stock audio UI probe requires original SmplTrek 3.2.174")
        ui = StockSession(stock, output / "stages", slice_cycles)
        ui.advance(1500000000)
        if ui.word(MODAL):
            ui.key(30, "dismiss-card-warning")
        ui.wait(lambda: ui.word(MODAL) == 0)
        ui.capture("home")
        checks["initial_output_silent"] = tail_silent(stock)
        # Reference manual pp.40-41: FUNC+PROJECT -> SAMPLE -> Pool -> AUDIO.
        stock.key_input(19, True); ui.advance(20000000)
        ui.key(20, "pool-type")
        stock.key_input(19, False); ui.advance(20000000)
        ui.key(23, "pool-root")
        ui.turn(1, label="select-pool")
        ui.key(23, "pool-files")
        ui.turn(1, label="select-tone")
        # Move left to the preview column. OK on the filename follows a separate
        # stop/open path which currently faults on a low null-object read.
        ui.key(24, "preview-column")
        ui.key(23, "preview-started")
        if guest_sample_period:
            stock.cpu.profile_guest(guest_sample_period)
        ui.advance(200000000)

        def capture_playing(label, amplitude_divisor=1):
            ui.capture(label)
            reports.append(ui.report)
            raw, audio = stock.cpu.audio_output()
            matches[label] = tones(raw, audio, amplitude_divisor)
            checks[f"{label}_exact_fixture_samples"] = all(
                row["compared_frames"] == 4096 and row["max_error"] == 0 and row["peak"] > 0
                for row in matches[label])
            # With full slot-0/1 frames the observed source-left channel leads
            # source-right by one frame. Keep this profile observation visible;
            # physical I2S/DMA startup phase still needs independent validation.
            checks[f"{label}_recorded_slot_phase"] = (matches[label][0]["phase"] + 1) % 32 == matches[label][1]["phase"] % 32
            data, info = stereo_wav(raw, audio["first_capture_slot"])
            path = output / f"{label}.wav"; path.write_bytes(data)
            artifacts[label] = {**info, "path": str(path)}

        capture_playing("playing")
        playback = ui.report["execution_window"].copy()
        playback_profile = None
        if guest_sample_period:
            stock.cpu.profile_guest(0)
            playback_profile = stock.cpu.guest_profile()
        ui.key(23, "preview-stop")
        ui.advance(100000000)
        ui.capture("stopped")
        checks["stop_produces_silence"] = tail_silent(stock)
        reports.append(ui.report)
        ui.key(23, "preview-restart")
        ui.advance(150000000)
        capture_playing("restarted")
        ui.advance(450000000)
        capture_playing("second-half", 2)
        ui.advance(350000000)
        capture_playing("looped")
        ui.key(23, "preview-stop-again")
        ui.advance(100000000)
        ui.capture("stopped-again")
        checks["second_stop_produces_silence"] = tail_silent(stock)
        reports.append(ui.report)
        checks["guest_read_wav_data"] = reports[-1]["sd"]["bytes_read"] >= len(source)
        checks["private_card_kept_wav"] = FatImage(stock.cpu.sd_read()).read(WAV_PATH) == source
        checks["input_card_unchanged"] = card.read_bytes() == original
        checks["input_wav_unchanged"] = tone.read_bytes() == source
        checks["no_guest_hooks"] = all(r["guest_function_hooks"] == [] for r in reports)
        checks["no_audio_errors"] = all(r["audio"]["underruns"] == r["audio"]["overruns"] == 0 for r in reports)
        checks["equal_rx_tx_word_counts"] = all(r["audio"]["received_words"] == r["audio"]["transmitted_words"] for r in reports)
        checks["continuous_48khz_slot_clock"] = all(
            r["audio"]["last_capture_cycle"] - r["audio"]["first_capture_cycle"] ==
            (r["audio"]["captured_words"] - 1) * 3875 for r in reports)
        checks["only_known_reserved_accesses"] = all(
            r["reserved_low"]["count"] == 6 and r["usb"]["reserved_status"]["count"] == 2 for r in reports)
        report = dict(kind="conditional stock WAV preview", checks=checks, passed=all(checks.values()),
                      fixture=dict(path=WAV_PATH, sha256=digest(source), frames=96000, sample_bits=16,
                                   channels_hz=[750, 1500], channels_peak_first_second=[4096, 8192],
                                   channels_peak_second_second=[2048, 4096]),
                      matches=matches, artifacts=artifacts, playback_window=playback, playback_guest_profile=playback_profile,
                      slot_phase=dict(reference="complete McASP slot-0/1 frames", source_left_leads_frames=1,
                                      physical_phase_verified=False),
                      observations=ui.observations, inputs=stock.inputs.copy(), runs=reports,
                      limitations=["reserved-bus hypotheses remain explicit and unverified",
                                   "filename action still faults on a null-object read; preview column works",
                                   "digital capture only; physical channel routing and analog conversion unverified",
                                   "one-frame source-channel offset in slot-0/1 frames; I2S/DMA startup phase unverified",
                                   "no live host playback; measured throughput remains below real time",
                                   "one 48 kHz stereo PCM16 fixture; other audio formats and track playback remain pending"])
        (output / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def probe(output, slice_cycles=1000000, guest_sample_period=0, cpu=None):
    if type(guest_sample_period) is not int or not 0 <= guest_sample_period <= 1000000:
        raise ValueError("guest sample period must be 0..1000000")
    with pinned_cpu(cpu) as affinity:
        report = _probe(output, slice_cycles, guest_sample_period)
        report["host_affinity"] = affinity
        (output / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conditional", action="store_true", required=True,
                        help="explicitly select both recorded reserved-bus hypotheses; silicon response remains unverified")
    parser.add_argument("--output", type=Path, default=WORK / "stock-audio")
    parser.add_argument("--slice-cycles", type=int, default=1000000)
    parser.add_argument("--guest-sample-period", type=int, default=0, help="optional jittered packet histogram during warmed playback")
    parser.add_argument("--cpu", type=int, help="pin the emulation thread to an allowed CPU")
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(WORK.resolve()):
        parser.error("generated audio artifacts must remain under work/emulator/")
    report = probe(args.output, args.slice_cycles, args.guest_sample_period, args.cpu)
    if not report["passed"]:
        raise RuntimeError(f'stock audio checks failed: {report["checks"]}')
    print(f'Conditional stock WAV preview passed; playback {report["playback_window"]["realtime_ratio"]:.4f}x real time. Report: {args.output / "result.json"}')


if __name__ == "__main__":
    main()
