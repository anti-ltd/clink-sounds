#!/usr/bin/env python3
"""Validate the complete release against the existing Clink download contract."""
import base64
import binascii
import hashlib
import io
import json
import math
import os
import pathlib
import re
import struct
import urllib.parse
import wave

MAX_PACK_BYTES = 512_000
MAX_SAMPLE_BYTES = 80_000
MAX_SAMPLES = 4
SAMPLE_RATE = 44_100
MAX_FRAMES = 22_050
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")
SHA256 = re.compile(r"[0-9a-f]{64}")
DEFAULT_REPOSITORY = "anti-ltd/clink-sounds"


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"non-finite JSON number: {value}")


def _read_json(raw):
    return json.loads(raw, object_pairs_hook=_object, parse_constant=_nonfinite)


def _safe_id(value):
    return isinstance(value, str) and SAFE_ID.fullmatch(value) is not None


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _sample_errors(encoded, prefix):
    if not isinstance(encoded, str):
        return [f"{prefix}: sample must be base64 text"]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return [f"{prefix}: invalid base64 sample"]
    if not 44 < len(raw) <= MAX_SAMPLE_BYTES:
        return [f"{prefix}: WAV must contain 45–{MAX_SAMPLE_BYTES} bytes"]
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return [f"{prefix}: sample must be RIFF/WAVE"]
    if struct.unpack_from("<I", raw, 4)[0] + 8 != len(raw):
        return [f"{prefix}: WAV RIFF size does not match its bytes"]
    try:
        with wave.open(io.BytesIO(raw), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, SAMPLE_RATE, "NONE"):
                return [f"{prefix}: expected mono 16-bit PCM {SAMPLE_RATE} Hz WAV"]
            frames = audio.getnframes()
            if not 1 <= frames <= MAX_FRAMES:
                return [f"{prefix}: sample must contain 1–{MAX_FRAMES} frames (at most 0.5 seconds)"]
            if len(audio.readframes(frames + 1)) != frames * 2:
                return [f"{prefix}: WAV sample data is truncated"]
    except (wave.Error, EOFError, OSError, struct.error):
        return [f"{prefix}: invalid PCM WAV structure"]
    return []


def _payload_errors(raw, sound):
    prefix = sound.get("id", "<unknown>")
    if not 0 < len(raw) <= MAX_PACK_BYTES:
        return [f"{prefix}: payload must contain 1–{MAX_PACK_BYTES} bytes"]
    try:
        payload = _read_json(raw)
    except (ValueError, UnicodeError, RecursionError):
        return [f"{prefix}: invalid .clinkpack JSON"]
    if not isinstance(payload, dict) or not isinstance(payload.get("pack"), dict):
        return [f"{prefix}: payload must contain a pack object"]
    pack = payload["pack"]
    errors = []
    if not _safe_id(pack.get("id")):
        errors.append(f"{prefix}: payload id must be a safe nonempty identifier")
    if not isinstance(pack.get("name"), str) or pack["name"] != sound.get("name"):
        errors.append(f"{prefix}: manifest name does not match payload")
    if not isinstance(pack.get("blurb", ""), str):
        errors.append(f"{prefix}: blurb must be text")
    # These optional fields retain the client's existing decoding defaults.
    if pack.get("fileExtension", "wav") != "wav":
        errors.append(f"{prefix}: fileExtension must be wav")
    if pack.get("source", "bundled") not in ("bundled", "custom", "external"):
        errors.append(f"{prefix}: source must be bundled, custom, or external")
    gain = pack.get("gain", 1)
    if not _finite_number(gain) or gain <= 0:
        errors.append(f"{prefix}: gain must be positive and finite")
    names = pack.get("sampleNames")
    if not isinstance(names, list) or not 1 <= len(names) <= MAX_SAMPLES:
        errors.append(f"{prefix}: one to four sample names are required")
    elif any(not _safe_id(name) for name in names):
        errors.append(f"{prefix}: sample names contain unsafe characters")
    elif len(set(names)) != len(names):
        errors.append(f"{prefix}: sample names must be unique")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= MAX_SAMPLES:
        errors.append(f"{prefix}: one to four samples are required")
    else:
        if not isinstance(names, list) or len(samples) != len(names):
            errors.append(f"{prefix}: sample count does not match metadata")
        for index, encoded in enumerate(samples, 1):
            errors.extend(_sample_errors(encoded, f"{prefix} sample {index}"))
    return errors


def _presentation_errors(presentation, prefix):
    if presentation is None:
        return []
    if not isinstance(presentation, dict):
        return [f"{prefix}: presentation must be an object"]
    errors = []
    tint = presentation.get("switchTint")
    if tint is not None and (not isinstance(tint, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", tint)):
        errors.append(f"{prefix}: switchTint must be #RRGGBB")
    waveform = presentation.get("waveform")
    if waveform is not None and (
        not isinstance(waveform, list) or not 2 <= len(waveform) <= 128
        or any(not _finite_number(value) or not 0 <= value <= 1 for value in waveform)
    ):
        errors.append(f"{prefix}: waveform must contain 2–128 amplitudes in 0–1")
    return errors


def _valid_url(value, repository, filename):
    if not isinstance(value, str) or any(character.isspace() for character in value):
        return False
    try:
        url = urllib.parse.urlsplit(value)
        prefix = f"/{repository}/releases/download/"
        if (url.scheme != "https" or url.netloc.lower() != "github.com"
                or url.query or url.fragment or not url.path.startswith(prefix)):
            return False
        tag, separator, asset = url.path[len(prefix):].rpartition("/")
        return bool(tag and separator and asset == filename and ".." not in urllib.parse.unquote(tag))
    except ValueError:
        return False


def validate_manifest(root, repository=DEFAULT_REPOSITORY):
    """Return actionable errors without changing the catalog or any asset."""
    root = pathlib.Path(root)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return ["repository must be owner/name"]
    try:
        manifest = _read_json((root / "manifest.json").read_bytes())
    except (OSError, ValueError, UnicodeError, RecursionError):
        return ["manifest.json is missing or invalid JSON"]
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]
    errors = []
    if not isinstance(manifest.get("version"), str) or not manifest["version"].strip():
        errors.append("manifest version must be nonempty text")
    if not isinstance(manifest.get("sounds"), list):
        return errors + ["manifest sounds must be an array"]
    seen = set()
    indexed_files = set()
    for sound in manifest["sounds"]:
        if not isinstance(sound, dict):
            errors.append("sound entry must be an object")
            continue
        identifier = sound.get("id")
        prefix = identifier if isinstance(identifier, str) else "<unknown>"
        if not _safe_id(identifier):
            errors.append(f"{prefix}: catalog id must be a safe nonempty identifier")
        elif identifier in seen:
            errors.append(f"{prefix}: duplicate catalog id")
        else:
            seen.add(identifier)
        name = sound.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            errors.append(f"{prefix}: name must contain 1–80 characters")
        version = sound.get("version")
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", version) or ".." in version:
            errors.append(f"{prefix}: version must be a safe nonempty identifier")
        errors.extend(_presentation_errors(sound.get("presentation"), prefix))
        asset = sound.get("asset")
        if not isinstance(asset, dict):
            errors.append(f"{prefix}: asset must be an object")
            continue
        filename = asset.get("path")
        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.clinkpack", filename):
            errors.append(f"{prefix}: asset path must be a safe .clinkpack filename")
            continue
        indexed_files.add(filename)
        if identifier != pathlib.Path(filename).stem:
            errors.append(f"{prefix}: manifest id must match filename")
        if not _valid_url(asset.get("url"), repository, filename):
            errors.append(f"{prefix}: asset URL must be an HTTPS GitHub release asset in {repository}")
        try:
            raw = (root / "Sounds" / filename).read_bytes()
        except OSError:
            errors.append(f"{prefix}: asset is missing")
            continue
        digest = asset.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest) or digest != hashlib.sha256(raw).hexdigest():
            errors.append(f"{prefix}: SHA-256 is incorrect")
        byte_count = asset.get("byteCount")
        if type(byte_count) is not int or not 0 < byte_count <= MAX_PACK_BYTES or byte_count != len(raw):
            errors.append(f"{prefix}: byteCount is incorrect or exceeds {MAX_PACK_BYTES}")
        errors.extend(_payload_errors(raw, sound))
    published_files = {path.name for path in (root / "Sounds").glob("*.clinkpack") if not path.name.startswith(".")}
    for filename in sorted(published_files - indexed_files):
        errors.append(f"{filename}: release asset is missing from the manifest")
    return errors


if __name__ == "__main__":
    errors = validate_manifest(pathlib.Path(__file__).resolve().parents[1],
                               os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY))
    if errors:
        raise SystemExit("\n".join(errors))
