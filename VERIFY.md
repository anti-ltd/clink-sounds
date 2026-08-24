# Verify this Clink sounds repository

Read `README.md`, `PROMPT.md`, existing `Sounds/*.clinkpack`, `tools/build-manifest.py`, and `tools/validate-manifest.py`. Audit without modifying files unless asked to fix a specific issue.

Parse every `.clinkpack` and run:

```sh
python3 tools/build-manifest.py
python3 tools/validate-manifest.py
```

Confirm every pack is data-only JSON with a clear visible name and stable kebab-case filename. Verify its declared sample count and names match the bundled samples; names may contain only letters, numbers, `_`, and `-`; there are no more than four samples; and each is mono, 44.1 kHz WAV no longer than 0.5 seconds. Check that sounds have clear creator/redistribution permission, licence, and attribution status. Inspect the generated manifest for correct assets, hashes, and byte counts rather than accepting hand-edited values.

Confirm release workflows remain intact. Report each pack, sample count, audio-format results, licence/attribution status, commands and validation output, and exact paths with recommended fixes for every issue or unavailable check.
