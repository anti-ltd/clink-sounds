

https://github.com/user-attachments/assets/9ba9c02e-50f7-4a7d-92b6-615211f9bec5



https://github.com/user-attachments/assets/c96cf0f6-bd7e-4e41-b2db-03ad127bdb8e



https://github.com/user-attachments/assets/0708b19b-c36d-4673-98cf-bdfc477e34a4



https://github.com/user-attachments/assets/eb67028c-bf2c-4571-9c47-dd61da9021e6

# Add a Clink sound pack

You are contributing one key-sound pack to this repository. Read `README.md`, inspect an existing `Sounds/*.clinkpack`, `tools/build-manifest.py`, and `tools/validate-manifest.py` before editing. Add or update exactly one `.clinkpack` in `Sounds/`.

Prefer exporting the pack from Clink. A pack is data-only JSON containing its metadata and conditioned WAV samples. Keep it suitable for a keyboard: mono 44.1 kHz samples, at most four samples, each no longer than 0.5 seconds, with safe unique sample names using only letters, numbers, `_`, and `-`. Use only sounds that the contributor created or is permitted to redistribute. Give the pack a clear visible name and a stable kebab-case filename.

Parse the pack JSON, confirm the declared sample names match the sample count, and run:

```sh
python3 tools/build-manifest.py
python3 tools/validate-manifest.py
```

Include regenerated `manifest.json`; do not hand-edit its hashes or byte counts. Do not modify workflows. Finish with the sound character, sample count, licence/attribution status, and validation result.
