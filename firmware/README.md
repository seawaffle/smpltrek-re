# firmware/

Sonicware's update files are copyrighted and are not in this repository. Download them from
[sonicware.co.jp](https://sonicware.co.jp) / [sonicware.com](https://sonicware.com) and place them here,
unrenamed, in this layout. Everything in this folder except this README is git-ignored.

```
firmware/
  smpltrek/   SmplTrek v1.0.65.zip ... SmplTrek v3.2.174.zip   (eight releases)
  lofi12/     Lofi-12XT_v1.1.156.zip, Lofi-12XT_v1.2.179.zip, Lofi-12XT_v1.5.205.zip
  cydrums/    CyDrums_v1.1.84.zip, CyDrums_v2.0.97beta.zip, CyDrums_folder.zip
  other/      ELZ_1 v2.0.zip ... ELZ_1 v7.0.zip, ELZ_1_play_v*.zip, MINIMAL_v1.0.58.zip,
              LIVEN_*.syx (Liven 8bit warps, Lofi-12, XFM, Bass&Beats, Mega Synthesis, Ambient Ø)
```

The SHA-256 of every file the analysis was done against is in
[tools/verified_corpus.json](../tools/verified_corpus.json); `python3 -B tools/sonicware_integrity.py verify`
checks a download. The symbol files in [symbols/](../symbols) are pinned to these exact releases.

Tests and scripts that need a file which is not present skip with a notice.
