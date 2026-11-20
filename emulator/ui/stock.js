"use strict";

const $ = (id) => document.getElementById(id);
const canvas = $("screen");
const context = canvas.getContext("2d");
const image = context.createImageData(128, 128);
const FRAME = 1, AUDIO = 2, STATUS = 3;
let streamShown = false;
// Panel units: the instrument is drawn 310 wide, positions are control centres.
const WIDTH = 310, HEIGHT = 351, TOP = -14;   // y values below are measured on a 365-high drawing
// Switch bits follow the stock test page's map. Each entry: key bit, LED name, x, y, face, print below.
const KEYS = [
  [19, "func", 98, 174, "", "func"], [26, "rec", 135, 174, "●", "sampling"], [20, "project", 172, 174, "▤", "pool"], [27, "home", 209, 174, "⌂", "system"],
  [22, "play", 98, 200, "▶", "◀◀"], [29, "stop", 135, 200, "■", "▶▶"], [21, "mixer", 172, 200, "╫", "fx"], [28, "edit", 209, 200, "✎", "rec src"],
];
// Printed labels. The products' panels are physically the same; only the printing differs
// (docs/10-cross-flash-button-map.md). Per function key: face, print below, name. Pads by analogue channel.
const UPPER = ["CFG", "SND", "FLT", "MOD", "AMP", "EFX", "RVB"];
const SHARED = {
  func: ["", "func", "FUNC"], rec: ["PTN", "save", "PTN"], project: ["COPY", "song", "COPY"], home: ["PAD", "project", "PAD"],
  stop: ["▶", "system", "PLAY"], mixer: ["MIX", "ext src", "MIX"],
};
const LABELS = {
  // The default, for writing and testing custom firmware: nothing product-specific. Function keys are
  // F1-F8, left to right with the upper row first; pads carry their analogue channel (the id of a pad
  // event). No icons and no shifted functions.
  generic: {
    keys: Object.fromEntries(["func", "rec", "project", "home", "play", "stop", "mixer", "edit"].map((lamp, index) => [lamp, [`F${index + 1}`, "", `F${index + 1}`]])),
    pads: Array.from({ length: 15 }, (_, index) => `PAD ${index}`),
    side: ["OCTAVE left", "OCTAVE right"], select: "SELECT",
  },
  sampler: {
    keys: { func: ["", "func", "FUNC"], rec: ["●", "sampling", "REC"], project: ["▤", "pool", "PROJECT"], home: ["⌂", "system", "HOME"],
      play: ["▶", "◀◀", "PLAY"], stop: ["■", "▶▶", "STOP"], mixer: ["╫", "fx", "MIXER"], edit: ["✎", "rec src", "EDIT"] },
    pads: ["TRK 8", "TRK 1", "TRK 9", "TRK 2", "TRK 10", "TRK 3", "GLOBAL 1", "TRK 4", "GLOBAL 2", "TRK 5", "GLOBAL 3", "TRK 6", "USB AUDIO", "TRK 7", "EXT SRC"],
    side: ["Octave down", "Octave up"], select: "SELECT",
  },
  lofi: {
    keys: { ...SHARED, play: ["●", "sampling", "REC"], edit: ["MUTE", "mix tape", "MUTE"] },
    pads: Array.from({ length: 15 }, (_, index) => (index % 2 ? UPPER[index >> 1] : `TRK ${(index >> 1) + 1}`)),
    side: ["Page left", "Page right"], select: "Auxiliary",
  },
};
LABELS.drum = { ...LABELS.lofi, keys: { ...SHARED, play: ["●", "kit", "REC"], edit: ["MUTE", "perform", "MUTE"] } };
const labelled = { keys: {}, pads: [], side: [], select: [] };   // elements whose text follows the label set
// Encoder index and push-switch bit per knob: the stock encoder test page labels encoders 0-4 A, B, C, D, V.
const KNOBS = [[0, 1, "A", 214, 98], [1, 0, "B", 245, 98], [2, 2, "C", 214, 137], [3, 3, "D", 245, 137], [4, 4, "VALUE", 286, 139]];
// Analogue channel n is taken to be pad n of the stock pad LED numbering: lower row even, upper row odd.
const PAD_LEDS = ["trk8", "trk1", "trk9", "trk2", "trk10", "trk3", "global1", "trk4", "global2", "trk5", "global3", "trk6", "usb", "trk7", "ext"];
// What each panel LED address (48a + 8b + c) lights, from analysis/led_table.py; g, r, b are its colour channels.
const LED_MAP = ("vol-l vol-r mic value:b value:g value:r - - trk4:b trk2:g trk2:r trk2:b trk9:g trk9:r trk9:b - usb:g usb:r usb:b global3:g global3:r global3:b trk4:g trk4:r " +
  "step10:g step10:r step3:g step3:r step4:g step4:r step5:g step5:r step6:g step6:r step15:g step15:r step16:g step16:r clr:g clr:r func:g func:r home:g home:r mixer:g mixer:r stop:g stop:r " +
  "vol-l vol-r mic value:b value:g value:r - - trk5:b trk3:g trk3:r trk3:b trk10:g trk10:r trk10:b - ext:g ext:r ext:b global2:g global2:r global2:b trk5:g trk5:r " +
  "step1:g step1:r step2:g step2:r step12:g step12:r step13:g step13:r step14:g step14:r step7:g step7:r step8:g step8:r ok:g ok:r rec:g rec:r project:g project:r edit:g edit:r play:g play:r " +
  "vol-l vol-r mic value:b value:g value:r - - trk6:b trk1:g trk1:r trk1:b trk8:g trk8:r trk8:b - trk7:g trk7:r trk7:b global1:g global1:r global1:b trk6:g trk6:r " +
  "- - - - - - - - - - - - - - - - - - - - step9:g step9:r step11:g step11:r").split(" ");
const SHORTCUTS = {
  ArrowUp: 17, ArrowDown: 25, ArrowLeft: 24, ArrowRight: 18, Enter: 23, Backspace: 30, " ": 22,
  s: 29, f: 19, h: 27, r: 26, p: 20, m: 21, e: 28,
};
const PAD_KEYS = ["z", "x", "c", "v", "b", "a", "d", "g", "j", "k", "q", "w", "t", "y", "u"];
const ledElements = [];
const lamps = {};        // LED name -> { element, kind }
const padButtons = [];
const down = new Set();
const latched = new Set();
const padsDown = new Set();
let sending = Promise.resolve();
let volumeKnob = null, suggested = false;

function send(event) {
  sending = sending.then(() => fetch("/api/input", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(event),
  })).then(async (response) => {
    if (!response.ok) $("notice").textContent = (await response.json()).error;
  }).catch(() => {});
}

// ---- display ---------------------------------------------------------------------------
function draw(frame) {
  for (let y = 0; y < 128; y++) {
    for (let x = 0; x < 128; x++) {
      const packed = frame[128 * (y >> 1) + 64 * (x & 1) + (x >> 1)];
      const gray = ((packed >> ((y & 1) * 4)) & 15) * 17;
      const offset = (128 * y + x) * 4;
      image.data[offset] = gray; image.data[offset + 1] = gray; image.data[offset + 2] = gray; image.data[offset + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
}

// ---- audio -----------------------------------------------------------------------------
// Slot words arrive as produced. They are paired into frames, collected into ~10 ms blocks
// and scheduled back to back a little ahead of the sound card's clock.
let audio = null, gain = null, playhead = 0, underruns = 0;
let pendingLeft = [], pendingRight = [], carry = null;

function play(payload) {
  if (!audio) return;
  const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
  let slot = payload[0];
  for (let offset = 1; offset + 4 <= payload.byteLength; offset += 4, slot ^= 1) {
    const sample = view.getInt32(offset, true) / 2147483648;
    if (slot === 0) carry = sample;
    else if (carry !== null) {
      // Slot 0 carries the source's right channel and slot 1 its left on this stock profile.
      const swap = $("swap").checked;
      pendingLeft.push(swap ? carry : sample); pendingRight.push(swap ? sample : carry);
      carry = null;
    }
  }
  if (pendingLeft.length < 480) return;
  const now = audio.currentTime;
  if (playhead < now + 0.005) {
    if (playhead) $("underruns").textContent = ++underruns;
    playhead = now + 0.08;
  }
  if (playhead - now < 0.5) {
    const buffer = audio.createBuffer(2, pendingLeft.length, 48000);
    buffer.copyToChannel(Float32Array.from(pendingLeft), 0);
    buffer.copyToChannel(Float32Array.from(pendingRight), 1);
    const source = audio.createBufferSource();
    source.buffer = buffer; source.connect(gain); source.start(playhead);
    playhead += buffer.duration;
  } // Otherwise the emulator ran ahead of the sound card; drop this block to catch up.
  pendingLeft = []; pendingRight = [];
  $("buffer").textContent = `${Math.max(0, Math.round((playhead - now) * 1000))} ms`;
}

$("audio").addEventListener("click", async () => {
  if (audio) {
    await audio.close(); audio = null; playhead = 0;
    $("audio").textContent = "Enable audio"; $("buffer").textContent = "off";
    return;
  }
  audio = new AudioContext({ sampleRate: 48000, latencyHint: "interactive" });
  gain = audio.createGain(); gain.gain.value = $("volume").value / 100; gain.connect(audio.destination);
  pendingLeft = []; pendingRight = []; carry = null;
  $("audio").textContent = "Mute audio";
});

function volume() {
  const value = Number($("volume").value);
  $("volume-value").textContent = `${(value / 100).toFixed(1)}×`;
  if (gain) gain.gain.value = value / 100;
  if (volumeKnob) volumeKnob.style.transform = `rotate(${Math.round(-135 + 270 * value / 800)}deg)`;
}
$("volume").addEventListener("input", volume);

// ---- status ----------------------------------------------------------------------------
// Panel LED levels run 0-10. A lamp's colour is the sum of its channels.
function light(lamp, level) {
  const [r, g, b] = [level.r || 0, level.g || 0, level.b || 0].map((value) => Math.min(1, value / 10) ** 0.6);
  const on = r + g + b > 0, style = lamp.element.style;
  const colour = (scale, floor) => `rgb(${[r, g, b].map((value) => Math.round(floor + (scale - floor) * value)).join(", ")})`;
  if (lamp.kind === "pad") {
    style.backgroundColor = on ? colour(255, 60) : "";
    style.boxShadow = on ? `0 0 3cqw ${colour(255, 0)}` : "";
  } else if (lamp.kind === "ring") {
    style.borderColor = on ? colour(255, 40) : "";
    style.boxShadow = on ? `0 0 2.2cqw ${colour(255, 0)}` : "";
  } else {                                   // keys and indicator dots
    style.backgroundColor = on ? colour(lamp.kind === "dot" ? 255 : 150, 20) : "";
    style.borderColor = on ? colour(255, 60) : "";
    style.boxShadow = on ? `0 0 2.2cqw ${colour(255, 0)}` : "";
  }
}

function show(state) {
  $("status").textContent = state.fault ? "Stopped" : state.paused ? "Paused" : state.display_on ? "Running" : "Running, display off";
  $("clock").textContent = `${state.guest_seconds.toFixed(1)} s guest · ${Math.round(100 * state.skipped_cycles / Math.max(1, state.cycles))}% idle skipped` +
    (state.compiled_blocks ? ` · ${state.compiled_blocks} compiled blocks` : "");
  $("rate").textContent = state.paused || state.fault ? "–" : `${state.rate.toFixed(2)}×`;
  $("rate").classList.toggle("slow", !state.paused && !state.fault && state.rate < 0.97 * state.speed);
  $("pause").textContent = state.paused ? "Resume" : "Pause";
  $("pause").dataset.action = state.paused ? "resume" : "pause";
  $("conditional").hidden = !state.conditional;
  if (state.panel_stream && !streamShown) {
    streamShown = true;
    $("battery-value").textContent = $("battery").value;
    $("battery-hint").textContent = "The panel MCU reports every pad and this channel (15) continuously, as on the unit.";
  }
  $("save").disabled = !state.persistent;
  $("save").title = state.persistent ? "" : "Start with --state DIRECTORY to keep the card and flash";
  $("error").hidden = !state.fault;
  if (state.fault) $("error").textContent = state.fault;
  if (state.notice) $("notice").textContent = state.notice;
  if (state.labels && !suggested) {
    suggested = true;
    let stored = null;
    try { stored = window.localStorage.getItem("panel-labels"); } catch (error) { /* storage unavailable */ }
    if (!LABELS[stored]) relabel(state.labels);
  }
  const keys = BigInt(`0x${state.keys}`);
  document.querySelectorAll("[data-key]").forEach((button) => {
    button.classList.toggle("held", !!(keys & (1n << BigInt(button.dataset.key))));
  });
  padButtons.forEach((button, index) => button.classList.toggle("held", state.pads[index] > 0));
  $("power").classList.toggle("held", state.power_key);
  lamps.speaker.forEach((slot) => slot.classList.toggle("on", !!audio));
  const levels = {};
  ledElements.forEach((element, index) => {
    const value = parseInt(state.leds.substr(index * 2, 2), 16);
    element.style.backgroundColor = value ? `rgb(${Math.min(255, 90 + value * 11)}, ${Math.min(255, 60 + value * 8)}, 40)` : "";
    element.title = `LED ${index}: (${Math.floor(index / 48)}, ${Math.floor((index % 48) / 8)}, ${index % 8}) = ${value}` +
      (LED_MAP[index] === "-" ? ", no LED known" : `, ${LED_MAP[index]}`);
    if (LED_MAP[index] === "-") return;
    const [name, channel] = LED_MAP[index].split(":");
    const level = levels[name] ||= {};
    // Single-colour indicators have one address per plane: show the brightest. They are drawn warm white.
    if (channel) level[channel] = value;
    else ["r", "g", "b"].forEach((each) => { level[each] = Math.max(level[each] || 0, value * (each === "b" ? 0.7 : 1)); });
  });
  Object.entries(levels).forEach(([name, level]) => { if (lamps[name] && lamps[name].element) light(lamps[name], level); });
}

// ---- stream ----------------------------------------------------------------------------
async function connect() {
  for (;;) {
    try {
      const response = await fetch("/stream");
      const reader = response.body.getReader();
      let buffered = new Uint8Array(0);
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        const joined = new Uint8Array(buffered.length + value.length);
        joined.set(buffered); joined.set(value, buffered.length);
        let offset = 0;
        while (joined.length - offset >= 5) {
          const length = new DataView(joined.buffer, offset + 1, 4).getUint32(0, true);
          if (joined.length - offset - 5 < length) break;
          const payload = joined.subarray(offset + 5, offset + 5 + length);
          if (joined[offset] === FRAME) draw(payload);
          else if (joined[offset] === AUDIO) play(payload);
          else if (joined[offset] === STATUS) show(JSON.parse(new TextDecoder().decode(payload)));
          offset += 5 + length;
        }
        buffered = joined.slice(offset);
      }
    } catch (error) { /* The emulator is not reachable; retry below. */ }
    $("status").textContent = "Disconnected";
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

// ---- controls --------------------------------------------------------------------------
function key(index, pressed) {
  if (pressed === down.has(index)) return;
  if (pressed) down.add(index); else down.delete(index);
  send({ type: "key", index, down: pressed });
}

function latch(element, index) {
  const hold = !latched.has(index);
  if (hold) latched.add(index); else latched.delete(index);
  element.classList.toggle("latched", hold);
  key(index, hold);
}

function bindKey(button) {
  const index = Number(button.dataset.key);
  button.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    if (event.shiftKey || latched.has(index)) { latch(button, index); return; }
    button.setPointerCapture(event.pointerId);
    key(index, true);
  });
  const release = () => { if (!latched.has(index)) key(index, false); };
  button.addEventListener("pointerup", release);
  button.addEventListener("pointercancel", release);
  button.addEventListener("lostpointercapture", release);
}

function pad(index, pressed) {
  if (pressed === padsDown.has(index)) return;
  if (pressed) padsDown.add(index); else padsDown.delete(index);
  send({ type: "pad", index, value: pressed ? Number($("pressure").value) : 0 });
}

// Places an element by its centre, in panel units.
function at(parent, tag, className, x, y, width, height, text) {
  const element = document.createElement(tag);
  element.className = className + (tag === "button" || className.startsWith("knob") ? "" : " at");
  element.style.left = `${(100 * x / WIDTH).toFixed(2)}%`; element.style.top = `${(100 * (y + TOP) / HEIGHT).toFixed(2)}%`;
  if (width) element.style.width = `${(100 * width / WIDTH).toFixed(2)}%`;
  if (height) element.style.height = `${(100 * height / HEIGHT).toFixed(2)}%`;
  if (text) element.textContent = text;
  parent.append(element);
  return element;
}

function keyButton(parent, className, bit, x, y, width, height, face, name) {
  const button = at(parent, "button", className, x, y, width, height, face);
  button.dataset.key = bit; button.title = name; button.setAttribute("aria-label", name);
  return button;
}

// A knob turns by dragging up or down or with the wheel; a click without a drag is its push switch.
function knob(parent, className, x, y, size, name, turn, pushBit) {
  const element = at(parent, "div", `knob ${className}`, x, y, size, size);
  const pointer = document.createElement("i"); element.append(pointer);
  element.title = name; element.setAttribute("aria-label", name); element.setAttribute("role", "slider"); element.tabIndex = 0;
  if (pushBit !== undefined) element.dataset.key = pushBit;
  let angle = 0, origin = null, moved = false;
  const step = (detents) => {
    if (!detents) return;
    angle += 30 * detents; pointer.style.transform = `rotate(${angle}deg)`;
    // The server takes at most eight detents per event: a fast drag is sent in parts.
    for (let rest = detents; rest;) { const part = Math.max(-8, Math.min(8, rest)); turn(part); rest -= part; }
  };
  if (!turn) return element;
  element.addEventListener("wheel", (event) => { event.preventDefault(); step(event.deltaY < 0 ? 1 : -1); }, { passive: false });
  element.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    if (pushBit !== undefined && (event.shiftKey || latched.has(pushBit))) { latch(element, pushBit); return; }
    element.setPointerCapture(event.pointerId); origin = event.clientY || 0; moved = false;
  });
  element.addEventListener("pointermove", (event) => {
    if (origin === null) return;
    const detents = Math.trunc((origin - (event.clientY || 0)) / 12);
    if (detents) { moved = true; origin -= detents * 12; step(detents); }
  });
  const finish = (push) => () => {
    if (origin === null) return;
    origin = null;
    if (push && !moved && pushBit !== undefined) { key(pushBit, true); setTimeout(() => key(pushBit, false), 120); }
  };
  element.addEventListener("pointerup", finish(true));
  element.addEventListener("pointercancel", finish(false));
  return element;
}

function build() {
  const fixed = $("fixed");
  // Jacks, speaker and the analogue knobs: drawn for orientation. The speaker grille toggles this page's sound.
  [["IN", 27], ["SYNC", 53], ["OUT", 79]].forEach(([name, x]) => { at(fixed, "div", "print small", x, 41, 0, 0, name); at(fixed, "div", "jack", x, 51, 9, 7.6); });
  lamps.speaker = [72, 82, 92].map((y) => {
    const slot = at(fixed, "div", "slot", 53, y, 62, 6.5);
    slot.title = "Speaker: click to turn this page's sound on or off";
    slot.addEventListener("click", () => $("audio").click());
    return slot;
  });
  [["L", 34, "vol-l"], ["R", 80, "vol-r"]].forEach(([name, x, lamp]) => {
    at(fixed, "div", "print small", x, 118, 0, 0, name);
    knob(fixed, "inert", x, 131, 13, `Input gain ${name} (not emulated)`);
    lamps[lamp] = { element: at(fixed, "div", "dot", x - 13, 131, 0, 0), kind: "dot" };
    lamps[lamp].element.title = `Level indicator ${name}`;
  });
  lamps.mic = { element: at(fixed, "div", "dot", 243, 47, 0, 0), kind: "dot" };
  lamps.mic.element.title = "Microphone indicator";
  knob(fixed, "inert", 262, 47, 11, "Microphone gain (not emulated)");
  at(fixed, "div", "jack", 285, 45, 8, 6.8).title = "Microphone";
  at(fixed, "div", "print small", 285, 82, 0, 0, "VOL");
  volumeKnob = knob(fixed, "", 286, 98, 15, "VOL: this page's volume", (detents) => {
    $("volume").value = String(Math.max(0, Math.min(800, Number($("volume").value) + 25 * detents)));
    volume();
  }).children[0];
  volume();
  // Selection buttons under the display, the direction keys, OK and CLR.
  labelled.select = [keyButton(fixed, "key pill", 8, 132, 153, 22, 7, "", "SELECT left"), keyButton(fixed, "key pill", 9, 166, 153, 22, 7, "", "SELECT right")];
  at(fixed, "div", "well", 50, 187, 62, 62);
  [[17, "▲", 50, 169, "Up"], [24, "◀", 31, 187, "Left"], [18, "▶", 69, 187, "Right"], [25, "▼", 50, 205, "Down"]].forEach(([bit, face, x, y, name]) => {
    keyButton(fixed, "arrow", bit, x, y, 17, 14, face, name);
  });
  KEYS.forEach(([bit, lamp, x, y, face, print]) => {
    const button = keyButton(fixed, `key${lamp === "home" ? " home" : ""}`, bit, x, y, 28, 13, face, lamp);
    lamps[lamp] = { element: button, kind: "key" };
    labelled.keys[lamp] = [button, at(fixed, "div", "print small", x, y + 11, 0, 0, print)];
  });
  at(fixed, "div", "frame", 98, 177, 36, 26);
  at(fixed, "div", "frame", 263, 185, 62, 40).style.borderRadius = "9cqw";
  lamps.clr = { element: keyButton(fixed, "key round", 30, 248, 192, 21, 21, "CLR", "CLR"), kind: "key" };
  lamps.ok = { element: keyButton(fixed, "key round", 23, 278, 178, 21, 21, "OK", "OK"), kind: "key" };
  // Control knobs A-D and VALUE.
  at(fixed, "div", "frame", 229.5, 115, 62, 80);
  KNOBS.forEach(([index, pushBit, name, x, y]) => {
    at(fixed, "div", "print small", name === "VALUE" ? x : x - 9, name === "VALUE" ? y - 15 : y - 13, 0, 0, name);
    const element = knob($("encoders"), name === "VALUE" ? "ring" : "", x, y, name === "VALUE" ? 15 : 13,
      `${name}: turn, or click to push`, (delta) => send({ type: "encoder", index, delta }), pushBit);
    if (name === "VALUE") lamps.value = { element, kind: "ring" };
  });
  // Steps: two rows of eight.
  for (let index = 0; index < 16; index++) {
    const button = keyButton($("steps"), "step", 32 + index, 30 + 35.6 * (index % 8), index < 8 ? 231 : 262, 23, 23, String(index + 1), `STEP ${index + 1}`);
    lamps[`step${index + 1}`] = { element: button, kind: "ring" };
  }
  // Pads: seven above, eight below, staggered like a keyboard. Octave keys at the ends of the upper row.
  labelled.side = [keyButton(fixed, "octave", 16, 17, 299, 13, 15, "", "Octave down"), keyButton(fixed, "octave right", 31, 293, 299, 13, 15, "", "Octave up")];
  for (let index = 0; index < 15; index++) {
    const upper = index % 2 === 1, x = (upper ? 46 : 28) + 35.6 * (index >> 1), y = upper ? 299 : 339;
    const print = at(fixed, "div", "print small", x, y - 18.5, 0, 0, "");
    const button = at($("pads"), "button", "pad", x, y, 27, 26);
    labelled.pads.push([button, print]);
    button.addEventListener("pointerdown", (event) => { event.preventDefault(); button.setPointerCapture(event.pointerId); pad(index, true); });
    ["pointerup", "pointercancel"].forEach((name) => button.addEventListener(name, () => pad(index, false)));
    padButtons.push(button); lamps[PAD_LEDS[index]] = { element: button, kind: "pad" };
  }
  for (let index = 0; index < 144; index++) {
    const element = document.createElement("i");
    ledElements.push(element); $("leds").append(element);
  }
  document.querySelectorAll("button[data-key]").forEach(bindKey);
  relabel(chosenLabels());
}

// The label set: chosen on the page (remembered by the browser), else the one the emulator suggests.
function chosenLabels() {
  let stored = null;
  try { stored = window.localStorage.getItem("panel-labels"); } catch (error) { /* storage unavailable */ }
  return LABELS[stored] ? stored : "generic";
}

function relabel(name) {
  if (!LABELS[name]) name = "generic";
  const set = LABELS[name];
  const describe = (element, text) => { element.title = text; element.setAttribute("aria-label", text); };
  Object.entries(labelled.keys).forEach(([lamp, [button, print]]) => {
    const [face, below, title] = set.keys[lamp];
    button.textContent = face; print.textContent = below; describe(button, title);
    button.classList.toggle("word", face.length > 1);
  });
  labelled.pads.forEach(([button, print], index) => {
    print.textContent = set.pads[index];
    button.title = `${set.pads[index]}: analogue channel ${index}, key ${PAD_KEYS[index].toUpperCase()}`;
    button.setAttribute("aria-label", set.pads[index]);
  });
  labelled.side.forEach((button, index) => describe(button, set.side[index]));
  labelled.select.forEach((button, index) => describe(button, `${set.select} ${index ? "right" : "left"}`));
  $("labels").value = name;
}

function keyboard(event, pressed) {
  if (event.target instanceof HTMLInputElement || event.ctrlKey || event.metaKey || event.altKey) return;
  const name = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  const digit = /^Digit[1-8]$/.test(event.code) ? Number(event.code[5]) : 0;
  // Steps 1-8 on the digits, 9-16 with Shift. Release both, whichever Shift state remains.
  if (digit) {
    event.preventDefault();
    if (event.repeat) return;
    if (pressed) key((event.shiftKey ? 39 : 31) + digit, true);
    else { key(31 + digit, false); key(39 + digit, false); }
    return;
  }
  if (name in SHORTCUTS) { event.preventDefault(); if (!event.repeat) key(SHORTCUTS[name], pressed); return; }
  const index = PAD_KEYS.indexOf(name);
  if (index >= 0) { event.preventDefault(); if (!event.repeat) pad(index, pressed); return; }
  if (pressed && (name === "[" || name === "]")) { event.preventDefault(); send({ type: "encoder", index: 4, delta: name === "]" ? 1 : -1 }); }
}

let powerHeld = false;
function power(held) {
  if (held !== powerHeld) { powerHeld = held; send({ type: "power", down: held }); }
}

function releaseAll() {
  [...down].forEach((index) => { if (!latched.has(index)) key(index, false); });
  [...padsDown].forEach((index) => pad(index, false));
  power(false);
}

build();
window.addEventListener("keydown", (event) => keyboard(event, true));
window.addEventListener("keyup", (event) => keyboard(event, false));
window.addEventListener("blur", releaseAll);
$("pressure").addEventListener("input", () => { $("pressure-value").textContent = $("pressure").value; });
$("labels").addEventListener("change", () => {
  try { window.localStorage.setItem("panel-labels", $("labels").value); } catch (error) { /* storage unavailable */ }
  relabel($("labels").value);
});
$("pause").addEventListener("click", () => send({ type: "control", action: $("pause").dataset.action || "pause" }));
$("save").addEventListener("click", () => send({ type: "control", action: "save" }));
// Captured, so a release outside the button still reaches it; focus loss releases it too.
$("power").addEventListener("pointerdown", (event) => { event.preventDefault(); $("power").setPointerCapture(event.pointerId); power(true); });
["pointerup", "pointercancel", "lostpointercapture"].forEach((name) => $("power").addEventListener(name, () => power(false)));
$("battery").addEventListener("change", () => {
  $("battery-value").textContent = $("battery").value;
  send({ type: "battery", value: Number($("battery").value) });
});
connect();
