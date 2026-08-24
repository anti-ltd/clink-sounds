#!/usr/bin/env python3
import hashlib
import json
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[1]
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
errors = []
sha256 = re.compile(r"^[0-9a-f]{64}$")

for sound in manifest.get("sounds", []):
    asset = sound.get("asset", {})
    path = root / "Sounds" / asset.get("path", "")
    if not path.is_file():
        errors.append(f"{sound.get('id', '<unknown>')}: asset is missing")
        continue
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
        pack = payload["pack"]
        samples = payload["samples"]
    except (json.JSONDecodeError, KeyError, TypeError):
        errors.append(f"{sound.get('id', '<unknown>')}: invalid .clinkpack JSON")
        continue
    if sound.get("id") != path.stem:
        errors.append(f"{sound.get('id', '<unknown>')}: manifest id must match filename")
    if pack.get("name") != sound.get("name"):
        errors.append(f"{sound.get('id', '<unknown>')}: manifest name does not match payload")
    if not isinstance(samples, list) or not samples or len(samples) != len(pack.get("sampleNames", [])):
        errors.append(f"{sound.get('id', '<unknown>')}: sample count does not match metadata")
    if len(pack.get("sampleNames", [])) > 4:
        errors.append(f"{sound.get('id', '<unknown>')}: at most four samples are allowed")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", name or "") for name in pack.get("sampleNames", [])):
        errors.append(f"{sound.get('id', '<unknown>')}: sample names contain unsafe characters")
    if asset.get("sha256") != hashlib.sha256(raw).hexdigest() or not sha256.fullmatch(asset.get("sha256", "")):
        errors.append(f"{sound.get('id', '<unknown>')}: SHA-256 is incorrect")
    if asset.get("byteCount") != len(raw):
        errors.append(f"{sound.get('id', '<unknown>')}: byteCount is incorrect")
    if not asset.get("path", "").endswith(".clinkpack"):
        errors.append(f"{sound.get('id', '<unknown>')}: asset must be .clinkpack")

if errors:
    raise SystemExit("\n".join(errors))
