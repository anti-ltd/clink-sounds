#!/usr/bin/env python3
"""Build the verified manifest for a Clink sound-pack release."""
import base64
import hashlib
import json
import os
import pathlib

root = pathlib.Path(__file__).resolve().parents[1]
repository = os.environ.get("GITHUB_REPOSITORY", "anti-ltd/clink-sounds")
sounds = []

for path in sorted((root / "Sounds").glob("*.clinkpack")):
    raw = path.read_bytes()
    payload = json.loads(raw)
    pack = payload["pack"]
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
    })

(root / "manifest.json").write_text(
    json.dumps({"version": "latest", "sounds": sounds}, indent=2) + "\n",
    encoding="utf-8",
)
