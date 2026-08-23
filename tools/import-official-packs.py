#!/usr/bin/env python3
"""Import the four sound packs shipped by Clink into this repository.

Run from the app checkout:
    python3 clink-sounds/tools/import-official-packs.py Resources/Sounds
"""
import argparse
import base64
import json
import pathlib

PACKS = [
    {
        "id": "tactile",
        "name": "Tactile Brown",
        "blurb": "Deep, rounded thock of a lubed brown switch.",
        "gain": 1.10,
        "samples": ["tactile-1", "tactile-2", "tactile-3"],
    },
    {
        "id": "clicky",
        "name": "Clicky Blue",
        "blurb": "Sharp, springy click with a crisp tail.",
        "gain": 0.95,
        "samples": ["clicky-1", "clicky-2", "clicky-3"],
    },
    {
        "id": "typewriter",
        "name": "Typewriter",
        "blurb": "Mechanical hammer strike and carriage ring.",
        "gain": 0.95,
        "samples": ["typewriter-1", "typewriter-2"],
    },
    {
        "id": "marble",
        "name": "Marble",
        "blurb": "Soft, glassy tap. Understated and quiet.",
        "gain": 1.20,
        "samples": ["marble-1", "marble-2", "marble-3"],
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=pathlib.Path, help="Directory containing the bundled WAV files")
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1] / "Sounds",
        help="Repository Sounds directory",
    )
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    for pack in PACKS:
        samples = []
        for sample in pack["samples"]:
            wav = source / f"{sample}.wav"
            if not wav.is_file():
                raise SystemExit(f"missing bundled sample: {wav}")
            samples.append(base64.b64encode(wav.read_bytes()).decode("ascii"))

        payload = {
            "pack": {
                "id": pack["id"],
                "name": pack["name"],
                "blurb": pack["blurb"],
                "sampleNames": pack["samples"],
                "fileExtension": "wav",
                "gain": pack["gain"],
                "source": "bundled",
            },
            "samples": samples,
        }
        destination = output / f"{pack['id']}.clinkpack"
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {destination} ({destination.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
