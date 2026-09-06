#!/usr/bin/env python3
"""Render original, deterministic Clink clicks from editable DSP recipes.

Uses only Python's standard library. No recordings, old Clonk presets, external
audio, network requests, or Git operations. Existing packs outside the recipe
list are never rewritten. Run --check to verify reproducibility without writes.
"""
import argparse
import base64
import hashlib
import io
import json
import math
import pathlib
import re
import statistics
import struct
import wave

ROOT = pathlib.Path(__file__).resolve().parents[1]
RECIPE_PATH = ROOT / "tools" / "sound-recipes.json"
SAMPLE_RATE = 44_100
VARIANTS = 4
PROTECTED_IDS = {"clicky", "marble", "tactile", "typewriter"}


class Noise:
    """A fixed xorshift32 stream, independent of Python's random implementation."""
    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF or 0x6D2B79F5

    def next(self) -> float:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state / 2**31 - 1


def lowpass(values: list[float], hz: float) -> list[float]:
    pole = math.exp(-2 * math.pi * hz / SAMPLE_RATE)
    previous = 0.0
    output = []
    for value in values:
        previous = (1 - pole) * value + pole * previous
        output.append(previous)
    return output


def highpass(values: list[float], hz: float) -> list[float]:
    pole = math.exp(-2 * math.pi * hz / SAMPLE_RATE)
    previous_input = previous_output = 0.0
    output = []
    for value in values:
        previous_output = pole * (previous_output + value - previous_input)
        previous_input = value
        output.append(previous_output)
    return output


def resonator(values: list[float], hz: float, q: float) -> list[float]:
    """Constant-peak RBJ bandpass; its ringing gives a noisy impact a body."""
    omega = 2 * math.pi * min(hz, SAMPLE_RATE * 0.45) / SAMPLE_RATE
    alpha = math.sin(omega) / (2 * q)
    b = alpha / (1 + alpha)
    a1 = -2 * math.cos(omega) / (1 + alpha)
    a2 = (1 - alpha) / (1 + alpha)
    x1 = x2 = y1 = y2 = 0.0
    output = []
    for value in values:
        y = b * (value - x2) - a1 * y1 - a2 * y2
        output.append(y)
        x2, x1, y2, y1 = x1, value, y1, y
    return output


def load_recipes(path: pathlib.Path = RECIPE_PATH) -> list[dict]:
    document = json.loads(path.read_text())
    if document.get("version") != 1:
        raise ValueError("Unsupported synthesis recipe version")
    recipes = document["packs"]
    identifiers = [recipe["id"] for recipe in recipes]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Recipe IDs must be unique")
    for recipe in recipes:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", recipe["id"]):
            raise ValueError("Recipe IDs must be lowercase kebab-case")
        if recipe["id"] in PROTECTED_IDS:
            raise ValueError("A synthesis recipe must not replace an existing official pack")
        if not 20 <= recipe["duration_ms"] <= 500:
            raise ValueError("Recipe duration must stay within the keyboard sample limit")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", recipe["tint"]):
            raise ValueError("Recipe tint must be #RRGGBB")
    return recipes


def render_variant(recipe: dict, variant_index: int) -> list[int]:
    if not 0 <= variant_index < VARIANTS:
        raise ValueError("Variant index out of range")
    seed = hashlib.sha256(f"clink-original-v1/{recipe['id']}/{variant_index}".encode()).digest()
    rng = Noise(int.from_bytes(seed[:4], "little"))
    pitch = 1 + (-0.021, -0.006, 0.008, 0.023)[variant_index]
    stretch = 1 + (-0.025, 0.017, -0.009, 0.026)[variant_index]
    count = round(recipe["duration_ms"] * SAMPLE_RATE / 1000)
    excitation = [0.0] * count

    # Multiple independently seeded, filtered impacts can model a case aftertap,
    # dry grains, or a double contact. Decay values are actual time constants;
    # there is no second master exponential to crush them into the first 5 ms.
    for event in recipe["excitation"]:
        start = round(event["at_ms"] * stretch * SAMPLE_RATE / 1000)
        noise = lowpass([rng.next() for _ in range(count - start)], event["lowpass_hz"] * pitch)
        tau = event["decay_ms"] * stretch / 1000
        attack = min(0.00035, tau * 0.25)
        for index, value in enumerate(noise):
            t = index / SAMPLE_RATE
            envelope = min(1, t / attack) * math.exp(-t / tau)
            excitation[start + index] += value * envelope * event["gain"]

    raw = [0.0] * count
    for hz, q, gain in recipe["body"]:
        body = resonator(excitation, hz * pitch, q)
        for index, value in enumerate(body):
            raw[index] += value * gain * 2.8

    # Unequal inharmonic modal decay makes ceramic/metal distinct from a
    # pitched instrument. The same bounded envelope also works for brief blips.
    for hz, decay_ms, gain in recipe.get("modes", []):
        phase = rng.next() * 0.18
        tau = decay_ms * stretch / 1000
        for index in range(count):
            t = index / SAMPLE_RATE
            raw[index] += math.sin(2 * math.pi * hz * pitch * t + phase) * math.exp(-t / tau) * gain

    bend = recipe.get("bend")
    if bend:
        fall = bend["fall_ms"] * stretch / 1000
        decay = bend["decay_ms"] * stretch / 1000
        for index in range(count):
            t = index / SAMPLE_RATE
            cycles = pitch * (bend["end_hz"] * t + (bend["start_hz"] - bend["end_hz"]) * fall * (1 - math.exp(-t / fall)))
            # Add only harmonics below Nyquist; no aliased square-wave edges.
            tone = sum(math.sin(2 * math.pi * cycles * harmonic) * amount
                       for harmonic, amount in bend["harmonics"]
                       if max(bend["start_hz"], bend["end_hz"]) * pitch * harmonic < SAMPLE_RATE * 0.45)
            raw[index] += tone * math.exp(-t / decay) * bend["gain"]

    contact = recipe["contact"]
    contact_noise = highpass([rng.next() for _ in range(count)], contact["highpass_hz"] * pitch)
    tau = contact["decay_ms"] * stretch / 1000
    for index, value in enumerate(contact_noise):
        raw[index] += value * math.exp(-index / SAMPLE_RATE / tau) * contact["gain"]

    raw = highpass(lowpass(raw, recipe["finish_lowpass_hz"]), 35)
    # Remove the tiny finite-buffer DC residual before applying endpoint fades.
    dc = statistics.fmean(raw)
    attack_frames = max(2, round(recipe["attack_ms"] * SAMPLE_RATE / 1000))
    tail_frames = round(0.008 * SAMPLE_RATE)
    for index, value in enumerate(raw):
        attack = math.sin(min(1, index / attack_frames) * math.pi / 2) ** 2
        tail = math.sin(min(1, (count - 1 - index) / tail_frames) * math.pi / 2) ** 2
        raw[index] = (value - dc) * attack * tail
    if not all(math.isfinite(value) for value in raw):
        raise ValueError("Synthesis produced nonfinite audio")
    peak = max(map(abs, raw))
    if peak < 1e-8:
        raise ValueError("Synthesis produced silent audio")
    # Trim only inaudible trailing padding. Preserve context and fade to exact
    # zero again, so even a long modal tail never ends in a discontinuity.
    last = next(index for index in range(count - 1, -1, -1) if abs(raw[index]) >= peak * 0.001)
    end = min(count, max(round(0.024 * SAMPLE_RATE), last + round(0.002 * SAMPLE_RATE)))
    raw = raw[:end]
    fade = min(round(0.001 * SAMPLE_RATE), len(raw))
    for index in range(fade):
        raw[-fade + index] *= (1 - index / (fade - 1)) ** 2
    # Fades and trimming can reintroduce a small finite-buffer DC offset. Remove
    # it through a smooth zero-endpoint taper, preserving the silent boundaries.
    taper = [math.sin(math.pi * index / (len(raw) - 1)) ** 2 for index in range(len(raw))]
    residual = sum(raw) / sum(taper)
    raw = [value - residual * weight for value, weight in zip(raw, taper)]
    scale = 0.75 / max(map(abs, raw))
    pcm = [round(value * scale * 32767) for value in raw]
    pcm[0] = pcm[-1] = 0
    return pcm


def wav_bytes(pcm: list[int]) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))
    return output.getvalue()


def make_pack(recipe: dict) -> dict:
    variants = [render_variant(recipe, index) for index in range(VARIANTS)]
    energies = [sum((value / 32768) ** 2 for value in pcm) for pcm in variants]
    # Equal peaks do not imply equally strong clicks. Match variations by
    # attenuation only, so the loudest individual sample remains below 0.75.
    # The pack gain then brings this common energy to its fixed reference.
    quietest = min(energies)
    variants = [[round(value * math.sqrt(quietest / energy)) for value in pcm]
                for pcm, energy in zip(variants, energies)]
    energies = [sum((value / 32768) ** 2 for value in pcm) for pcm in variants]
    # A fixed per-click energy reference was measured from the original four
    # Clink packs (~10–18 after pack gain). It is an auditable level proxy, not
    # a LUFS or perceptual-loudness claim. Longer ringing sounds need less gain.
    gain = round(math.sqrt(recipe["target_energy"] / statistics.median(energies)), 4)
    if not 0.05 <= gain <= 2:
        raise ValueError(f"{recipe['id']}: level calibration needs review ({gain})")
    return {
        "pack": {
            "id": recipe["id"], "name": recipe["name"], "blurb": recipe["blurb"],
            "sampleNames": [f"{recipe['id']}-{index + 1}" for index in range(VARIANTS)],
            "fileExtension": "wav", "gain": gain, "source": "bundled",
        },
        "samples": [base64.b64encode(wav_bytes(pcm)).decode("ascii") for pcm in variants],
    }


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare generated assets without writing files")
    parser.add_argument("--root", type=pathlib.Path, default=ROOT, help="Output repository (use a temporary directory for experiments)")
    args = parser.parse_args()
    root = args.root.resolve()
    recipes = load_recipes()
    sounds = root / "Sounds"
    style_path = sounds / "presentation.json"
    styles = json.loads(style_path.read_text()) if style_path.exists() else {}
    planned = {}
    generated = {}
    for recipe in recipes:
        payload = make_pack(recipe)
        raw = json_bytes(payload)
        planned[sounds / f"{recipe['id']}.clinkpack"] = raw
        styles[recipe["id"]] = {"switchTint": recipe["tint"]}
        generated[recipe["id"]] = {"sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw), "gain": payload["pack"]["gain"], "sampleCount": VARIANTS}
    planned[style_path] = json_bytes(dict(sorted(styles.items())))
    planned[root / "validation" / "generation.json"] = json_bytes({
        "generatorVersion": 1, "sampleRate": SAMPLE_RATE, "variantsPerPack": VARIANTS,
        "recipeSHA256": hashlib.sha256(RECIPE_PATH.read_bytes()).hexdigest(),
        "generatorSHA256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        "provenance": "Original procedural synthesis; no imported recordings or reused Clonk presets/audio.",
        "packs": generated,
    })
    if args.check:
        mismatches = [str(path.relative_to(root)) for path, data in planned.items() if not path.exists() or path.read_bytes() != data]
        if mismatches:
            raise SystemExit("Generated output differs: " + ", ".join(mismatches))
        print(f"PASS: {len(recipes)} packs / {len(recipes) * VARIANTS} samples reproduce byte-for-byte")
        return
    for path, data in planned.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"Generated {len(recipes)} new packs / {len(recipes) * VARIANTS} samples; existing packs outside the recipe list were untouched")


if __name__ == "__main__":
    main()
