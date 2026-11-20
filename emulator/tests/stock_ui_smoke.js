/* Exercise the stock panel's browser script without a browser: stream parsing, drawing,
   audio scheduling and input cleanup. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const created = [];
class Element {
  constructor(tagName = "DIV") {
    this.tagName = tagName; this.children = []; this.handlers = {}; this.dataset = {}; this.style = {};
    this.value = "9000"; this.checked = false; this.textContent = ""; this.classes = new Set();
    this.classList = { toggle: (name, on) => { if (on) this.classes.add(name); else this.classes.delete(name); } };
    created.push(this);
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, callback) { (this.handlers[name] ||= []).push(callback); }
  setAttribute() {}
  setPointerCapture() {}
  click() { this.dispatch("click"); }
  dispatch(name, fields = {}) {
    const event = { preventDefault() {}, pointerId: 1, target: this, shiftKey: false, ...fields };
    for (const callback of this.handlers[name] || []) callback(event);
  }
}
class HTMLInputElement extends Element {}

function message(kind, payload) {
  const out = new Uint8Array(5 + payload.length);
  out[0] = kind; new DataView(out.buffer).setUint32(1, payload.length, true); out.set(payload, 5);
  return out;
}

async function main() {
  const elements = new Map();
  let painted = null;
  const document = new Element();
  document.getElementById = (id) => {
    if (!elements.has(id)) { const node = new Element(); node.id = id; elements.set(id, node); }
    return elements.get(id);
  };
  document.createElement = (tag) => new Element(tag.toUpperCase());
  document.querySelectorAll = (selector) => created.filter((node) => node.dataset.key !== undefined &&
    (!selector.startsWith("button") || node.tagName === "BUTTON"));
  document.getElementById("screen").getContext = () => ({
    createImageData: () => ({ data: new Uint8ClampedArray(128 * 128 * 4) }),
    putImageData: (image) => { painted = image.data; },
  });
  document.getElementById("volume").value = "200";

  // One frame whose first bytes distinguish x, y and nibble order; split mid-message.
  const frame = new Uint8Array(8192);
  frame[0] = 0x21; frame[64] = 0x43; frame[8191] = 0xf0;
  const status = { cycles: 744000, guest_seconds: 0.002, rate: 1, speed: 1, paused: false, fault: null, notice: null,
    keys: (1n << 23n).toString(16).padStart(12, "0"), pads: new Array(15).fill(0), power_key: false,
    leds: "00".repeat(94) + "09" + "00".repeat(49), display_on: true, frames: 1, audio_lost_words: 0,
    skipped_cycles: 372000, checkpoints: [], conditional: true, persistent: false };
  const audio = new Uint8Array(1 + 4 * 2 * 600);
  const view = new DataView(audio.buffer);
  for (let index = 0; index < 600; index++) {
    view.setInt32(1 + index * 8, 0x40000000, true);      // slot 0: +0.5
    view.setInt32(5 + index * 8, -0x20000000, true);     // slot 1: -0.25
  }
  const stream = new Uint8Array([...message(3, new TextEncoder().encode(JSON.stringify(status))), ...message(1, frame), ...message(2, audio)]);
  const chunks = [stream.subarray(0, 700), stream.subarray(700, 9000), stream.subarray(9000)];
  const requests = [];
  const started = [];
  class AudioContext {
    constructor() { this.currentTime = 10; this.destination = {}; }
    createGain() { return { gain: { value: 0 }, connect() {} }; }
    createBuffer(channels, length, rate) {
      const data = [new Float32Array(length), new Float32Array(length)];
      return { duration: length / rate, copyToChannel: (source, channel) => data[channel].set(source), data };
    }
    createBufferSource() { return { connect() {}, start: function (when) { started.push({ when, buffer: this.buffer }); } }; }
    async close() {}
  }
  const window = new Element();
  const context = vm.createContext({
    document, window, console, HTMLInputElement, AudioContext, TextDecoder, setTimeout(callback) { callback(); },
    fetch: async (url, options) => {
      if (url === "/stream") {
        return { body: { getReader: () => ({ read: async () => chunks.length ? { value: chunks.shift(), done: false } : new Promise(() => {}) }) } };
      }
      requests.push(JSON.parse(options.body));
      return { ok: true, json: async () => ({}) };
    },
  });
  const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(setImmediate); };

  // Audio must be enabled before the stream's audio message is parsed.
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../ui/stock.js"), "utf8").replace(/\nconnect\(\);\s*$/, "\n"), context);
  document.getElementById("audio").dispatch("click");
  await settle();
  vm.runInContext("connect();", context);
  await settle();

  assert.equal(document.getElementById("pads").children.length, 15);
  assert.equal(document.getElementById("steps").children.length, 16);
  assert.equal(document.getElementById("leds").children.length, 144);
  assert.equal(document.getElementById("encoders").children.length, 5);
  // Panel byte 128*(y>>1) + 64*(x&1) + (x>>1); the even row is the low nibble.
  assert.equal(painted[0], 1 * 17);                       // (0,0): byte 0 low nibble
  assert.equal(painted[128 * 4], 2 * 17);                 // (0,1): byte 0 high nibble
  assert.equal(painted[4], 3 * 17);                       // (1,0): byte 64 low nibble
  assert.equal(painted[(128 * 127 + 127) * 4], 15 * 17);  // (127,127): byte 8191 high nibble
  assert.equal(document.getElementById("status").textContent, "Running");
  assert.equal(document.getElementById("conditional").hidden, false);
  assert.equal(document.getElementById("save").disabled, true);
  assert.match(document.getElementById("leds").children[94].style.backgroundColor, /^rgb/);
  assert.ok(created.find((node) => node.dataset.key === 32));  // STEP 1 is created by the script
  // Address 94 is PLAY green: the PLAY key lights, and nothing else on the panel does.
  const lit = created.filter((node) => node.tagName === "BUTTON" && node.style.boxShadow);
  assert.deepEqual(lit.map((node) => node.dataset.key), [22]);
  assert.match(lit[0].style.borderColor, /^rgb\(60, 2\d\d, 60\)$/);

  // 600 frames arrive: one block is scheduled 80 ms ahead with slot 1 on the left.
  assert.equal(started.length, 1);
  assert.ok(Math.abs(started[0].when - 10.08) < 1e-9);
  assert.equal(started[0].buffer.data[0].length, 600);
  assert.equal(started[0].buffer.data[0][0], -0.25);
  assert.equal(started[0].buffer.data[1][0], 0.5);

  const step = document.getElementById("steps").children[4];
  step.dispatch("pointerdown"); step.dispatch("pointerup"); step.dispatch("lostpointercapture");
  await settle();
  assert.deepEqual(requests.splice(0), [{ type: "key", index: 36, down: true }, { type: "key", index: 36, down: false }]);

  // Shift-click latches; a plain release and focus loss leave it held; a second click frees it.
  step.dispatch("pointerdown", { shiftKey: true }); step.dispatch("pointerup");
  window.dispatch("blur");
  await settle();
  assert.deepEqual(requests.splice(0), [{ type: "key", index: 36, down: true }]);
  step.dispatch("pointerdown"); step.dispatch("pointerup");
  await settle();
  assert.deepEqual(requests.splice(0), [{ type: "key", index: 36, down: false }]);

  // Keyboard: held keys are released when the window loses focus; repeats send nothing.
  window.dispatch("keydown", { key: "Enter", code: "Enter" });
  window.dispatch("keydown", { key: "Enter", code: "Enter", repeat: true });
  window.dispatch("keydown", { key: "!", code: "Digit1", shiftKey: true });
  window.dispatch("blur");
  await settle();
  assert.deepEqual(requests.splice(0), [{ type: "key", index: 23, down: true }, { type: "key", index: 40, down: true },
    { type: "key", index: 23, down: false }, { type: "key", index: 40, down: false }]);
  window.dispatch("keydown", { key: "x", code: "KeyX", target: new HTMLInputElement() });
  window.dispatch("keydown", { key: "x", code: "KeyX" }); window.dispatch("keyup", { key: "x", code: "KeyX" });
  window.dispatch("keydown", { key: "]", code: "BracketRight" });
  await settle();
  assert.deepEqual(requests.splice(0), [{ type: "pad", index: 1, value: 9000 }, { type: "pad", index: 1, value: 0 },
    { type: "encoder", index: 4, delta: 1 }]);

  // A pad held by key or pointer gets its zero-pressure release when the window loses focus.
  window.dispatch("keydown", { key: "x", code: "KeyX" });
  document.getElementById("pads").children[3].dispatch("pointerdown");
  window.dispatch("blur"); window.dispatch("blur");
  window.dispatch("keyup", { key: "x", code: "KeyX" });
  await settle();
  assert.deepEqual(requests.splice(0), [{ type: "pad", index: 1, value: 9000 }, { type: "pad", index: 3, value: 9000 },
    { type: "pad", index: 1, value: 0 }, { type: "pad", index: 3, value: 0 }]);

  // Label sets: the same buttons and pads, other printing. The default names nothing product-specific.
  const playKey = created.find((node) => node.tagName === "BUTTON" && node.dataset.key === 22);
  const firstPad = document.getElementById("pads").children[0], upperPad = document.getElementById("pads").children[1];
  const printed = () => [playKey.title, playKey.textContent, firstPad.title.split(":")[0], upperPad.title.split(":")[0]];
  assert.deepEqual(printed(), ["F5", "F5", "PAD 0", "PAD 1"]);
  for (const [name, expected] of [["sampler", ["PLAY", "▶", "TRK 8", "TRK 1"]], ["drum", ["REC", "●", "TRK 1", "CFG"]], ["generic", ["F5", "F5", "PAD 0", "PAD 1"]]]) {
    document.getElementById("labels").value = name; document.getElementById("labels").dispatch("change");
    assert.deepEqual(printed(), expected);
  }

  const knob = document.getElementById("encoders").children[2];
  knob.dispatch("wheel", { deltaY: 3 });
  // Dragging up 30 px is two detents and no push; a click without movement is the push switch (knob C, bit 2).
  knob.dispatch("pointerdown", { clientY: 100 }); knob.dispatch("pointermove", { clientY: 70 }); knob.dispatch("pointerup", { clientY: 70 });
  knob.dispatch("pointerdown", { clientY: 100 }); knob.dispatch("pointerup", { clientY: 100 });
  await settle();
  assert.deepEqual(requests.splice(0), [{ type: "encoder", index: 2, delta: -1 }, { type: "encoder", index: 2, delta: 2 },
    { type: "key", index: 2, down: true }, { type: "key", index: 2, down: false }]);

  // A 240 px drag is 20 detents: sent in parts the server accepts (at most 8 each), none lost.
  knob.dispatch("pointerdown", { clientY: 300 }); knob.dispatch("pointermove", { clientY: 60 }); knob.dispatch("pointerup", { clientY: 60 });
  knob.dispatch("pointerdown", { clientY: 60 }); knob.dispatch("pointermove", { clientY: 168 }); knob.dispatch("pointerup", { clientY: 168 });
  await settle();
  assert.deepEqual(requests.splice(0).map((event) => event.delta), [8, 8, 4, -8, -1]);

  // The power key is captured while held; losing focus releases it, and only once.
  const power = document.getElementById("power");
  let captured = 0; power.setPointerCapture = () => { captured++; };
  power.dispatch("pointerdown"); window.dispatch("blur"); power.dispatch("pointerup");
  power.dispatch("pointerdown"); power.dispatch("lostpointercapture"); power.dispatch("pointerup");
  await settle();
  assert.equal(captured, 2);
  assert.deepEqual(requests.splice(0), [{ type: "power", down: true }, { type: "power", down: false },
    { type: "power", down: true }, { type: "power", down: false }]);
  console.log("PASS: stream parsing, display decode, audio scheduling, LED lamps, latching, keyboard, knobs and focus-loss release");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
