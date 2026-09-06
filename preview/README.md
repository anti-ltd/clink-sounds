# New Clink sound auditions

Open `index.html` in a browser. It is self-contained, works offline, and never autoplays.
Each card plays one of the actual four WAV variants or a six-key typing burst.
Click again to cycle the variant. Stop or Escape cancels queued audio. Switching
packs also cancels old playback. The waveform follows the current sample and is
cropped to the audible hit; it does not change the audio.

`reel.wav` is a 24-second, mono 44,100 Hz PCM comparison.
Each two-second segment has a single click followed by six keypresses. The native
reel player is also embedded in the page. `timeline.json` records every onset and
variant number, allowing a reviewer to identify exactly what they heard.

| Time | Sound |
| --- | --- |
| 0:00–0:02 | Velvet |
| 0:02–0:04 | Walnut |
| 0:04–0:06 | Bamboo |
| 0:06–0:08 | Porcelain |
| 0:08–0:10 | Copper |
| 0:10–0:12 | Titanium |
| 0:12–0:14 | Pebble |
| 0:14–0:16 | Rain |
| 0:16–0:18 | Bubble |
| 0:18–0:20 | Parchment |
| 0:20–0:22 | Relay |
| 0:22–0:24 | Arcade |

The browser uses the pack's gain × 0.40 headroom × volume-setting^1.6, matching
Clink's pack volume mapping. The card slider starts at 80%; the WAV reel is fixed
at 80%. Browser/device media volume still affects playback, and this page does
not emulate iOS's output-volume compensation or Silent Mode. Check final perceived
loudness and rapid typing on an iPhone in Clink before release.

Only the twelve new IDs from `tools/sound-recipes.json` are included. Historical
packs and old Clonk recordings are not part of this audition. The embedded clips
come byte-for-byte from the generated `.clinkpack` files, with source hashes in
`provenance.json`. This development preview does not modify app copy or release
payloads and lives outside the `Sounds/*.clinkpack` release asset set.

Rebuild from the repository root using only Python's standard library:

```sh
python3 tools/build-preview.py
```
