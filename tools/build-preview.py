#!/usr/bin/env python3
"""Build an offline audition page and reel from the new sound recipes.

Run after generating Sounds/*.clinkpack. Only recipe IDs in NEW_PACK_IDS are
included; historical packs are deliberately excluded. Uses Python's stdlib.
"""
from __future__ import annotations

import argparse
import array
import base64
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import struct
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
NEW_PACK_IDS = ("velvet", "walnut", "bamboo", "porcelain", "copper", "titanium",
                "pebble", "rain", "bubble", "parchment", "relay", "arcade", "shot")
RATE = 44_100
HEADROOM = 0.40
DEFAULT_VOLUME = 0.80
SEGMENT_SECONDS = 2.0
BURST_OFFSETS = (0.0, 0.12, 0.26, 0.38, 0.52, 0.68)


def read_pcm(data: bytes, description: str) -> list[float]:
    with wave.open(io.BytesIO(data), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, RATE, "NONE"):
            raise ValueError(f"{description}: expected mono 16-bit PCM at {RATE} Hz")
        frames = source.getnframes()
        if not 0 < frames <= RATE // 2:
            raise ValueError(f"{description}: expected 0 < duration <= 0.5 seconds")
        pcm = source.readframes(frames)
        if len(pcm) != frames * 2:
            raise ValueError(f"{description}: incomplete PCM data")
    return [value / 32768.0 for (value,) in struct.iter_unpack("<h", pcm)]


def envelope(pcm: list[float], count: int = 72) -> list[float]:
    """The actual sample, cropped to its audible hit, with no invented bars."""
    peaks = [abs(value) for value in pcm]
    peak = max(peaks)
    if peak == 0:
        return [0.0] * count
    threshold = peak * 10 ** (-36 / 20)
    first = next(index for index, value in enumerate(peaks) if value >= threshold)
    last = len(peaks) - 1 - next(index for index, value in enumerate(reversed(peaks)) if value >= threshold)
    start, end = max(0, first - round(RATE * 0.0006)), min(len(peaks), last + round(RATE * 0.002) + 1)
    window = peaks[start:end]
    result = []
    for index in range(count):
        lower = min(len(window) - 1, index * len(window) // count)
        upper = max(lower + 1, (index + 1) * len(window) // count)
        # Square root improves visual legibility, but never changes the audio.
        result.append(round(math.sqrt(max(window[lower:upper]) / peak), 4))
    return result


def read_packs(recipe_path: Path) -> tuple[list[dict], list[list[list[float]]], dict]:
    recipe_data = json.loads(recipe_path.read_text())
    if recipe_data.get("version") != 1 or not isinstance(recipe_data.get("packs"), list):
        raise ValueError("Expected recipes version 1 with a packs array")
    recipes = {item["id"]: item for item in recipe_data["packs"]}
    missing = [identity for identity in NEW_PACK_IDS if identity not in recipes]
    if missing:
        raise ValueError("Missing new recipes: " + ", ".join(missing))
    packs, audio, hashes = [], [], {}
    for identity in NEW_PACK_IDS:
        path = ROOT / "Sounds" / f"{identity}.clinkpack"
        data = path.read_bytes()
        payload = json.loads(data)
        pack = payload["pack"]
        if pack["id"] != identity or len(pack["sampleNames"]) != 4 or len(payload["samples"]) != 4:
            raise ValueError(f"{path.name}: expected matching ID and four variants")
        gain = float(pack.get("gain", 1))
        if not math.isfinite(gain) or gain <= 0:
            raise ValueError(f"{path.name}: invalid gain")
        tint = recipes[identity]["tint"]
        if not isinstance(tint, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", tint):
            raise ValueError(f"{identity}: expected #RRGGBB recipe tint")
        decoded = [read_pcm(base64.b64decode(sample, validate=True), f"{identity}/{index + 1}")
                   for index, sample in enumerate(payload["samples"])]
        packs.append({"id": identity, "name": pack["name"], "blurb": pack.get("blurb", ""),
                      "tint": tint, "gain": gain, "samples": payload["samples"],
                      "waves": [envelope(sample) for sample in decoded],
                      "durations": [len(sample) / RATE for sample in decoded]})
        audio.append(decoded)
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    hashes[str(recipe_path.relative_to(ROOT))] = hashlib.sha256(recipe_path.read_bytes()).hexdigest()
    return packs, audio, hashes


def build_reel(packs: list[dict], audio: list[list[list[float]]]) -> tuple[bytes, dict]:
    duration = len(packs) * SEGMENT_SECONDS
    mixed = array.array("f", [0.0]) * round(duration * RATE)
    timeline = []
    for index, (pack, variants) in enumerate(zip(packs, audio)):
        start = index * SEGMENT_SECONDS
        events = [(start + 0.12, 0)] + [(start + 0.68 + offset, variant % 4)
                                      for variant, offset in enumerate(BURST_OFFSETS)]
        scale = HEADROOM * DEFAULT_VOLUME ** 1.6 * pack["gain"]
        for timestamp, variant in events:
            offset = round(timestamp * RATE)
            for frame, value in enumerate(variants[variant]):
                mixed[offset + frame] += value * scale
        timeline.append({"id": pack["id"], "name": pack["name"], "start": start,
                         "end": start + SEGMENT_SECONDS,
                         "events": [{"time": round(timestamp, 4), "variant": variant + 1}
                                    for timestamp, variant in events]})
    peak = max(abs(value) for value in mixed)
    if peak >= 1:
        raise ValueError(f"Reel would clip (peak {peak:.3f}); adjust audition timing rather than normalize pack gains")
    pcm = array.array("h", (round(value * 32767) for value in mixed))
    if sys.byteorder != "little":
        pcm.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(pcm.tobytes())
    mapping = {"duration": duration, "sampleRate": RATE, "channels": 1,
               "headroom": HEADROOM, "volumeSetting": DEFAULT_VOLUME,
               "volumeExponent": 1.6, "peakAmplitude": peak, "packs": timeline}
    return buffer.getvalue(), mapping


PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Clink — @@COUNTWORD@@ new sounds</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f1f2ee;background:#111310;color-scheme:dark;font-synthesis:none}
*{box-sizing:border-box}body{margin:0}button,input,a{-webkit-tap-highlight-color:transparent}button{font:inherit;cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible{outline:3px solid #d8edab;outline-offset:4px}button:disabled{opacity:.36;cursor:default}a{color:#d4e8ad;text-underline-offset:4px}
main{max-width:1180px;margin:auto;padding:52px 36px 70px}.masthead{display:flex;align-items:center;justify-content:space-between;margin-bottom:62px}.wordmark{font-size:27px;font-weight:800;letter-spacing:-1.5px}.wordmark span{color:#c9e3a0}.edition,.eyebrow{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#959d8d}.edition{border:1px solid #394034;border-radius:40px;padding:10px 13px}.intro{display:flex;gap:50px;justify-content:space-between;align-items:flex-end;margin-bottom:36px}h1{font-size:clamp(39px,5.7vw,70px);font-weight:580;line-height:1.02;letter-spacing:-3.5px;margin:13px 0 18px;max-width:680px}h1 span{color:#b2c58e}.lead{font-size:15px;line-height:1.6;color:#a5ad9c;max-width:510px;margin:0}.count{font-size:72px;letter-spacing:-5px;line-height:1;color:#536048}.count small{display:block;letter-spacing:1.5px;font-size:10px;color:#959d8d;text-align:right;margin-top:13px}.transport{position:sticky;top:12px;z-index:3;display:flex;align-items:center;gap:22px;background:#20251def;border:1px solid #394132;border-radius:14px;padding:16px 18px;backdrop-filter:blur(16px);margin-bottom:28px;box-shadow:0 10px 30px #0003}.status{min-width:0;flex:1;display:flex;align-items:center;gap:11px;font-size:12px;color:#c9d0c0}.status-dot{height:7px;width:7px;border-radius:50%;background:#66765a;flex:none}.status-dot.active{background:#c9e3a0;box-shadow:0 0 0 5px #c9e3a018}.volume{display:flex;align-items:center;gap:10px;font-size:10px;color:#a9b49b;white-space:nowrap}.volume input{width:94px;accent-color:#c9e3a0}.volume output{width:28px;text-align:right;font-variant-numeric:tabular-nums}.stop{border:1px solid #4a5540;background:none;color:#d5ddc9;border-radius:7px;padding:10px 13px;font-size:11px}.stop-icon{display:inline-block;width:6px;height:6px;background:currentColor;margin-right:7px;border-radius:1px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.card{display:flex;flex-direction:column;border:1px solid #32372e;border-radius:16px;background:linear-gradient(145deg,#242920,#1a1e17);overflow:hidden;padding:23px 22px 17px;position:relative;transition:border-color .15s,background .15s}.card.playing{border-color:var(--tint);background:linear-gradient(145deg,color-mix(in srgb,var(--tint) 12%,#242920),#1a1e17)}.card-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:27px}.ordinal{font-size:10px;color:#77816c;letter-spacing:1px;font-variant-numeric:tabular-nums}.take{font-size:9px;color:#88967a;letter-spacing:.5px}.key{width:43px;height:43px;border:1px solid color-mix(in srgb,var(--tint) 52%,#4d5944);border-radius:12px;background:linear-gradient(135deg,color-mix(in srgb,var(--tint) 18%,#343f2c),#20271a);box-shadow:0 3px 0 #11180c,inset 0 1px 1px #ffffff12;display:grid;place-items:center}.key::after{content:"";width:18px;height:18px;background:var(--tint);clip-path:polygon(35% 0,65% 0,65% 35%,100% 35%,100% 65%,65% 65%,65% 100%,35% 100%,35% 65%,0 65%,0 35%,35% 35%);filter:drop-shadow(0 1px 0 #0008)}.card h2{font-size:22px;font-weight:570;letter-spacing:-.5px;margin:0 0 8px}.blurb{flex:1;min-height:35px;color:#a0aa94;font-size:11px;line-height:1.6;margin:0 0 18px}.wave{width:100%;height:58px;display:block;color:var(--tint);opacity:.78;margin-bottom:20px}.card.playing .wave{opacity:1}.actions{display:flex;gap:8px}.actions button{border:1px solid #424a39;border-radius:7px;color:#d3dcc8;background:#ffffff04;min-height:39px;padding:0 12px;font-size:10px;display:flex;align-items:center;justify-content:center;gap:7px}.actions .single{background:var(--tint);border-color:var(--tint);color:#13170f;font-weight:750;flex:1}.actions .burst{flex:1.3}.play-icon{width:0;height:0;border-left:5px solid currentColor;border-top:3px solid transparent;border-bottom:3px solid transparent}.bars{display:inline-flex;align-items:center;gap:2px;height:11px}.bars i{width:2px;background:currentColor;border-radius:1px;height:6px}.bars i:nth-child(2){height:11px}.bars i:nth-child(3){height:8px}.reel{margin-top:46px;padding-top:29px;border-top:1px solid #343b2c;display:grid;grid-template-columns:1fr 1.3fr;gap:36px}.reel h2{font-size:22px;font-weight:550;letter-spacing:-.5px;margin:8px 0 12px}.reel p{font-size:11px;line-height:1.7;color:#9eaa91;margin:0 0 13px;max-width:365px}.reel audio{width:100%;height:35px;display:block;margin:10px 0 16px}.timeline{display:grid;grid-template-columns:repeat(3,1fr);gap:6px 12px}.timeline button{border:0;background:none;text-align:left;color:#b9c5aa;padding:4px 0;font-size:10px;min-height:28px}.timeline span{font-variant-numeric:tabular-nums;color:#738363;margin-right:8px}.note{margin-top:29px;color:#77836b;font-size:10px;line-height:1.7}.links{font-size:10px;display:flex;gap:17px}.error{color:#f4b9a0}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:800px){main{padding:30px 23px 50px}.masthead{margin-bottom:45px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.count{display:none}.reel{grid-template-columns:1fr;gap:13px}h1{letter-spacing:-2px}.card{padding:20px 17px 16px}.transport{gap:14px}.volume input{width:65px}}
@media(max-width:460px){main{padding:25px 16px 38px}.edition{font-size:8px;letter-spacing:1px}.masthead{margin-bottom:39px}.grid{gap:10px}.card{padding:17px 13px 13px;border-radius:12px}.card h2{font-size:19px}.card-top{margin-bottom:23px}.key{width:36px;height:36px;border-radius:10px}.blurb{font-size:10px;min-height:49px}.actions{gap:5px}.actions button{font-size:9px;padding:0 7px}.transport{padding:12px 11px;gap:9px}.status{font-size:10px;gap:8px}.volume label{display:none}.volume input{width:50px}.volume{gap:5px}.stop{font-size:10px;padding:9px}.timeline{grid-template-columns:repeat(2,1fr)}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
</style>
</head>
<body>
<main>
<header class="masthead"><div class="wordmark">clink<span>.</span></div><div class="edition">Sound studies · 01</div></header>
<section class="intro"><div><div class="eyebrow">A new collection</div><h1>@@COUNTWORD@@ new ways<br>to <span>feel a key.</span></h1><p class="lead">Soft grain. Bright metal. A little play. Listen to a single click, then hear each sound find its rhythm.</p></div><div class="count">@@COUNT@@<small>Sounds · @@VARIANTS@@ variations</small></div></section>
<div class="transport" role="group" aria-label="Playback controls"><div class="status"><span class="status-dot" id="status-dot" aria-hidden="true"></span><span id="status" role="status" aria-live="polite">Ready to listen</span></div><div class="volume"><label for="volume">Volume</label><input id="volume" type="range" min="0" max="100" value="80" aria-label="Preview volume"><output for="volume" id="volume-value">80%</output></div><button class="stop" id="stop" disabled><span class="stop-icon" aria-hidden="true"></span>Stop</button></div>
<section class="grid" aria-label="New sound packs">@@CARDS@@</section>
<section class="reel"><div><div class="eyebrow">Listen side by side</div><h2>The @@SECONDS@@-second collection.</h2><p>One click and a short typing burst for each sound, in the same order as the cards. Pick a name to start there.</p><div class="links"><a href="reel.wav" download="clink-new-sounds.wav">Download WAV</a><a href="timeline.json" download>Timeline</a></div></div><div><audio id="reel" controls preload="none" aria-label="Comparison of @@COUNT@@ new Clink sound packs" src="data:audio/wav;base64,@@REEL@@"></audio><div class="timeline">@@TIMELINE@@</div></div></section>
<p class="note">The page works offline and starts audio only when you press play. Card previews use the pack’s own gain and Clink’s volume curve. The reel is fixed at an 80% setting. Browser and device volume affect what you hear; final loudness should be checked in Clink.</p>
</main>
<script id="pack-data" type="application/json">@@PACKS@@</script>
<script>
'use strict';
const packs = JSON.parse(document.getElementById('pack-data').textContent);
const volume = document.getElementById('volume');
const status = document.getElementById('status');
const statusDot = document.getElementById('status-dot');
const stopButton = document.getElementById('stop');
const reel = document.getElementById('reel');
const cards = [...document.querySelectorAll('.card')];
let context, master, generation = 0, sources = [], finishTimer;
const decoded = new Map(), rotation = new Map();
function setStatus(message, active = false, error = false) {
  status.textContent = message; status.classList.toggle('error', error);
  statusDot.classList.toggle('active', active); stopButton.disabled = !active;
}
function stopPlayback(stopReel = true) {
  generation++; clearTimeout(finishTimer);
  sources.forEach(source => { try { source.stop(); source.disconnect(); } catch (_) {} });
  sources = []; cards.forEach(card => card.classList.remove('playing'));
  if (stopReel) { reel.pause(); reel.currentTime = 0; } setStatus('Ready to listen');
}
async function audioContext() {
  if (!context) {
    const AudioAPI = window.AudioContext || window.webkitAudioContext;
    if (!AudioAPI) throw new Error('This browser cannot preview audio. Use the WAV reel below.');
    context = new AudioAPI(); master = context.createGain(); master.connect(context.destination);
  }
  master.gain.value = 0.40 * Math.pow(Number(volume.value) / 100, 1.6);
  if (context.state !== 'running') await context.resume();
  return context;
}
async function packBuffers(pack) {
  if (!decoded.has(pack.id)) {
    const pending = Promise.all(pack.samples.map(encoded => {
      const raw = atob(encoded), bytes = new Uint8Array(raw.length);
      for (let index = 0; index < raw.length; index++) bytes[index] = raw.charCodeAt(index);
      return context.decodeAudioData(bytes.buffer);
    }));
    decoded.set(pack.id, pending);
    pending.catch(() => decoded.delete(pack.id));
  }
  return decoded.get(pack.id);
}
function updateWave(card, peaks) {
  const svg = card.querySelector('.wave');
  svg.querySelectorAll('line[data-bar]').forEach((bar, index) => {
    const half = peaks[index] * 23;
    bar.setAttribute('y1', 29 - half); bar.setAttribute('y2', 29 + half);
  });
}
async function audition(index, burst) {
  stopPlayback(); const request = generation, pack = packs[index], card = cards[index];
  setStatus(pack.name + ' · Preparing', true);
  try {
    await audioContext();
    const buffers = await packBuffers(pack);
    if (request !== generation) return;
    const next = rotation.get(pack.id) || 0;
    rotation.set(pack.id, (next + 1) % buffers.length);
    updateWave(card, pack.waves[next]);
    card.querySelector('.take').textContent = 'Take ' + (next + 1) + ' / 4';
    card.classList.add('playing');
    setStatus(pack.name + (burst ? ' · Typing burst' : ' · Take ' + (next + 1) + ' / 4'), true);
    const offsets = burst ? [0, .12, .26, .38, .52, .68] : [0];
    const start = context.currentTime + .015;
    let duration = 0;
    offsets.forEach((offset, position) => {
      const buffer = buffers[(next + position) % buffers.length];
      const source = context.createBufferSource(), trim = context.createGain();
      source.buffer = buffer; trim.gain.value = pack.gain;
      source.connect(trim); trim.connect(master);
      source.onended = () => { source.disconnect(); trim.disconnect(); };
      sources.push(source); source.start(start + offset);
      duration = Math.max(duration, offset + buffer.duration);
    });
    finishTimer = setTimeout(() => { if (request === generation) stopPlayback(false); }, (duration + .04) * 1000);
  } catch (error) {
    if (request === generation) { stopPlayback(); setStatus(error.message || 'Audio could not be played.', false, true); }
  }
}
cards.forEach((card, index) => {
  card.querySelector('.single').addEventListener('click', () => audition(index, false));
  card.querySelector('.burst').addEventListener('click', () => audition(index, true));
});
stopButton.addEventListener('click', () => stopPlayback());
volume.addEventListener('input', () => {
  document.getElementById('volume-value').value = volume.value + '%';
  if (master) master.gain.value = .40 * Math.pow(Number(volume.value) / 100, 1.6);
});
reel.addEventListener('play', () => { stopPlayback(false); setStatus('The collection · 24 seconds', true); });
reel.addEventListener('pause', () => { if (!sources.length) setStatus('Ready to listen'); });
reel.addEventListener('ended', () => setStatus('Ready to listen'));
document.querySelectorAll('[data-time]').forEach(button => button.addEventListener('click', () => {
  stopPlayback(); reel.currentTime = Number(button.dataset.time);
  reel.play().catch(() => setStatus('Press play on the reel to listen.', false));
}));
document.addEventListener('keydown', event => { if (event.key === 'Escape') stopPlayback(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) stopPlayback(); });
window.addEventListener('pagehide', () => { stopPlayback(); if (context) context.close(); });
</script>
</body>
</html>
'''


def number_word(value: int) -> str:
    words = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
             "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
             "seventeen", "eighteen", "nineteen", "twenty")
    return words[value].capitalize() if value < len(words) else str(value)


def card_html(pack: dict, index: int, total: int) -> str:
    bars = []
    for number, peak in enumerate(pack["waves"][0]):
        x = 3 + number * 3.6
        bars.append(f'<line data-bar x1="{x:.1f}" x2="{x:.1f}" y1="{29 - peak * 23:.2f}" y2="{29 + peak * 23:.2f}"/>')
    name = html.escape(pack["name"])
    return f'''<article class="card" style="--tint:{pack['tint']}" aria-labelledby="name-{index}">
<div class="card-top"><span class="ordinal">{index + 1:02d} / {total:02d}</span><span class="take">Four variations</span><span class="key" aria-hidden="true"></span></div>
<h2 id="name-{index}">{name}</h2><p class="blurb">{html.escape(pack['blurb'])}</p>
<svg class="wave" viewBox="0 0 262 58" role="img" aria-label="Waveform of {name}"><path d="M1 29H261" stroke="currentColor" stroke-opacity=".13" stroke-width=".5"/><g stroke="currentColor" stroke-width="1.9" stroke-linecap="round">{''.join(bars)}</g></svg>
<div class="actions"><button class="single" aria-label="Play one {name} click"><span class="play-icon" aria-hidden="true"></span>Click</button><button class="burst" aria-label="Play a {name} typing burst"><span class="bars" aria-hidden="true"><i></i><i></i><i></i></span>Typing burst</button></div></article>'''


def build(output: Path, recipes: Path) -> dict:
    packs, audio, hashes = read_packs(recipes)
    reel, timeline = build_reel(packs, audio)
    cards = "\n".join(card_html(pack, index, len(packs)) for index, pack in enumerate(packs))
    timeline_html = "\n".join(
        f'<button data-time="{item["start"]:.2f}" aria-label="Play {html.escape(item["name"])} in the comparison reel"><span>0:{round(item["start"]):02d}</span>{html.escape(item["name"])}</button>'
        for item in timeline["packs"])
    payload = json.dumps(packs, separators=(",", ":")).replace("<", "\\u003c")
    page = PAGE.replace("@@COUNTWORD@@", number_word(len(packs))).replace("@@COUNT@@", str(len(packs)))
    page = page.replace("@@VARIANTS@@", str(sum(len(pack["samples"]) for pack in packs)))
    page = page.replace("@@SECONDS@@", f"{timeline['duration']:.0f}")
    page = page.replace("@@CARDS@@", cards).replace("@@TIMELINE@@", timeline_html).replace("@@PACKS@@", payload).replace("@@REEL@@", base64.b64encode(reel).decode())
    if "@@" in page:
        raise ValueError("Unresolved page template marker")
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(page)
    (output / "reel.wav").write_bytes(reel)
    (output / "timeline.json").write_text(json.dumps(timeline, indent=2) + "\n")
    rows = "\n".join(f'| 0:{round(item["start"]):02d}–0:{round(item["end"]):02d} | {item["name"]} |' for item in timeline["packs"])
    readme = f'''# New Clink sound auditions

Open `index.html` in a browser. It is self-contained, works offline, and never autoplays.
Each card plays one of the actual four WAV variants or a six-key typing burst.
Click again to cycle the variant. Stop or Escape cancels queued audio. Switching
packs also cancels old playback. The waveform follows the current sample and is
cropped to the audible hit; it does not change the audio.

`reel.wav` is a {timeline['duration']:.0f}-second, mono {RATE:,} Hz PCM comparison.
Each two-second segment has a single click followed by six keypresses. The native
reel player is also embedded in the page. `timeline.json` records every onset and
variant number, allowing a reviewer to identify exactly what they heard.

| Time | Sound |
| --- | --- |
{rows}

The browser uses the pack's gain × 0.40 headroom × volume-setting^1.6, matching
Clink's pack volume mapping. The card slider starts at 80%; the WAV reel is fixed
at 80%. Browser/device media volume still affects playback, and this page does
not emulate iOS's output-volume compensation or Silent Mode. Check final perceived
loudness and rapid typing on an iPhone in Clink before release.

Only the {len(packs)} new IDs from `tools/sound-recipes.json` are included. Historical
packs and old Clonk recordings are not part of this audition. The embedded clips
come byte-for-byte from the generated `.clinkpack` files, with source hashes in
`provenance.json`. This development preview does not modify app copy or release
payloads and lives outside the `Sounds/*.clinkpack` release asset set.

Rebuild from the repository root using only Python's standard library:

```sh
python3 tools/build-preview.py
```
'''
    (output / "README.md").write_text(readme)
    report = {"packIDs": list(NEW_PACK_IDS), "packCount": len(packs), "sampleCount": sum(len(pack["samples"]) for pack in packs),
              "reelDuration": timeline["duration"], "reelPeakAmplitude": timeline["peakAmplitude"],
              "sourceSHA256": hashes, "outputs": {"index.html": hashlib.sha256(page.encode()).hexdigest(), "reel.wav": hashlib.sha256(reel).hexdigest()},
              "builderSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "externalResources": False, "autoplay": False}
    (output / "provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipes", type=Path, default=ROOT / "tools" / "sound-recipes.json")
    parser.add_argument("--output", type=Path, default=ROOT / "preview")
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve(), args.recipes.resolve()), indent=2))


if __name__ == "__main__":
    main()
