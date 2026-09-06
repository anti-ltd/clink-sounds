#!/usr/bin/env python3
"""Build the verified manifest for a Clink sound-pack release."""
import base64
import hashlib
import io
import json
import os
import pathlib
import re
import struct
import wave

WAVEFORM_BINS = 48


def sample_waveform(encoded_sample: str) -> list[float]:
    """Return raw peaks across the audible transient, normalized to its own peak.

    Keep a little of the real attack/decay around the -36 dB active region. The
    conditioned WAV can contain a much longer, effectively silent tail; using
    the complete file would reduce a short key click to one or two left spikes.
    Perceptual scaling belongs to the client, not these amplitude measurements.
    """
    with wave.open(io.BytesIO(base64.b64decode(encoded_sample, validate=True)), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 44_100:
            raise ValueError("Sound previews require conditioned mono 16-bit 44.1 kHz WAV samples")
        frames = audio.readframes(audio.getnframes())
    values = [abs(value[0]) for value in struct.iter_unpack("<h", frames)]
    if not values:
        raise ValueError("Sound preview sample is empty")
    peak = max(values)
    if not peak:
        return [0.0] * WAVEFORM_BINS
    threshold = peak * 10 ** (-36 / 20)
    first = next(index for index, value in enumerate(values) if value >= threshold)
    last = len(values) - 1 - next(index for index, value in enumerate(reversed(values))
                                if value >= threshold)
    # Match SoundPackWaveformLoader's crop while preserving the original audio.
    start = max(0, first - int(44_100 * 0.0006))
    end = min(len(values), last + int(44_100 * 0.002) + 1)
    values = values[start:end]
    peaks = []
    for index in range(WAVEFORM_BINS):
        start = index * len(values) // WAVEFORM_BINS
        end = max(start + 1, (index + 1) * len(values) // WAVEFORM_BINS)
        peaks.append(max(values[start:end]))
    return [round(value / peak, 4) for value in peaks]


def build_manifest(root: pathlib.Path, repository: str) -> dict:
    """Keep the download contract intact; append optional display metadata."""
    presentation_path = root / "Sounds" / "presentation.json"
    styles = json.loads(presentation_path.read_text(encoding="utf-8")) if presentation_path.exists() else {}
    sounds = []
    for path in sorted((root / "Sounds").glob("*.clinkpack")):
        if path.name.startswith("."):
            continue
        raw = path.read_bytes()
        payload = json.loads(raw)
        pack = payload["pack"]
        presentation = {"waveform": sample_waveform(payload["samples"][0])}
        tint = styles.get(path.stem, {}).get("switchTint")
        if tint is not None:
            if not isinstance(tint, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", tint):
                raise ValueError(f"{path.stem}: switchTint must be #RRGGBB")
            presentation["switchTint"] = tint
        sounds.append({
            "id": path.stem,
            "name": pack["name"],
            "version": "latest",
            "asset": {
                "path": path.name,
                "url": f"https://github.com/{repository}/releases/download/latest/{path.name}",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "byteCount": len(raw),
            },
            "presentation": presentation,
        })
    return {"version": "latest", "sounds": sounds}


if __name__ == "__main__":
    root = pathlib.Path(__file__).resolve().parents[1]
    repository = os.environ.get("GITHUB_REPOSITORY", "anti-ltd/clink-sounds")
    (root / "manifest.json").write_text(
        json.dumps(build_manifest(root, repository), indent=2) + "\n", encoding="utf-8",
    )
