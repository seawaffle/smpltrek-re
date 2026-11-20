// Writes a stock project Config from a seeded, generated drum song.
//   node make_config.mjs OUTPUT GENRE SEED
// Uses the pinned npm packages smpltrek-builder (project writer and base template) and
// drum-pattern-engine (song generator), both MIT, by Alexander Schornberg. Run from a folder where
// `npm ci` has installed them; project_card.py does that in the work folder.
import { writeFileSync } from "node:fs";
import { arrange } from "drum-pattern-engine";
import { buildProject, template, GENRES, GENRE_METER } from "smpltrek-builder";

const [output, genre = "FUNK", seedText = "1"] = process.argv.slice(2);
if (!output || !GENRES[genre]) {
  console.error(`usage: node make_config.mjs OUTPUT GENRE SEED\ngenres: ${Object.keys(GENRES).join(" ")}`);
  process.exit(2);
}
const g = GENRES[genre], meter = GENRE_METER[genre] || {};
const params = { ...g.p, instrumentSpread: g.p.densitySpread, repetition: 0.7, oddMeter: meter.amount };
const song = arrange(params, { length: "full", bpm: g.bpm, seed: Number(seedText), structure: g.struct, feel: g.feel,
  meterMode: meter.mode, meterSet: meter.set });
const config = buildProject(template.bytes(), song, { kit: g.kit, bpm: g.bpm });
writeFileSync(output, config);
console.log(JSON.stringify({ genre, seed: Number(seedText), kit: g.kit, bpm: g.bpm, clips: song.clips.length, bytes: config.length }));
