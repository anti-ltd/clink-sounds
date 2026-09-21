<p align="center">
  <img src="README-assets/clink-icon.png" width="96" alt="Clink app icon">
</p>

<h1 align="center">Clink sounds</h1>

<p align="center">Open key-sound packs for Clink.</p>

This repository is where people can publish short, conditioned key-click packs for Clink. Packs are ordinary `.clinkpack` files containing metadata and WAV samples; they are data only and cannot run code in Clink.

## Official Clink repositories

[Language packs](https://github.com/anti-ltd/clink-language-packs) · [Layouts](https://github.com/anti-ltd/clink-layouts) · [Profiles](https://github.com/anti-ltd/clink-profiles) · [Themes](https://github.com/anti-ltd/clink-themes) · [Panels](https://github.com/anti-ltd/clink-panels) · [Actions](https://github.com/anti-ltd/clink-actions) · [Fonts](https://github.com/anti-ltd/clink-fonts) · [Sounds](https://github.com/anti-ltd/clink-sounds)

## Included sounds

The repository contains 18 packs. The original four remain unchanged:

- **Clicky Blue** — sharp, springy click with a crisp tail
- **Tactile Brown** — deep, rounded thock of a lubed brown switch
- **Typewriter** — mechanical hammer strike and carriage ring
- **Marble** — soft, glassy tap for an understated sound

Thirteen new procedural packs add 52 freshly generated variations:

| Pack | Character |
|---|---|
| **Velvet** | Cushioned low tap with a soft fabric finish |
| **Walnut** | Warm wooden knock with a small hollow aftertap |
| **Bamboo** | Light, dry wooden tick with a crisp upper edge |
| **Porcelain** | Clean ceramic tap with a delicate, uneven ring |
| **Copper** | Rounded metal knock with a warm, muted ring |
| **Titanium** | Tight metallic snap with a fast shimmer |
| **Pebble** | Dense stone-like knock with a compact, grainy body |
| **Rain** | Soft cluster of tiny, bright pattering taps |
| **Bubble** | Rounded pop that drops into a soft low note |
| **Parchment** | Dry papery press with a brief textured rustle |
| **Relay** | Two crisp mechanical contacts in one compact click |
| **Arcade** | Tiny digital blip with a soft, falling edge |
| **Shot** | A 12-gauge blast that racks the pump between shots |

Each new pack has four deterministic variations. Packs live under [`Sounds/`](Sounds)
and become verified release assets through the existing publishing workflow.

**Retro Phone** is the one sampled pack here, and the only one the generator does
not render: a single dry midrange tock from an older phone keypad, conditioned
from a source WAV published under the WTFPL. Its energy sits almost entirely
between 1.6 and 6.4 kHz, with nothing below 800 Hz and nothing above 6.4 kHz,
which is what makes it read as small and plasticky rather than as a struck
object. It ships one sample rather than four variations on purpose: the phones
it comes from played the same tock on every key, and that sameness is the
effect.

**Shot** is the joke of the set, in the spirit of the keyboards that fire a
gunshot on every key. A report is not a struck object, so it is built the other
way around from the material packs: broadband noise with an instant attack and a
fast two-stage decay, only lightly weighted by a low body, then three darkening
echo taps at 57, 118 and 196 ms that place it in a space. After the blast the
pump racks back at 175 ms and forward at 250 ms. That makes it by far the longest
pack here (about 385 ms against the 65 to 140 ms of the others, still inside
Clink's 0.5 s sample limit) and the loudest, 1.1 dB above the median of the
original four. Typing quickly overlaps the shots, which is the point. It is the
same renderer and the same recipe format as everything else, with no recordings
of any kind.

## Audition and regenerate

Open [`preview/index.html`](preview/index.html) locally to compare individual
clicks or short typing bursts. It contains the actual pack audio and works
offline. [`preview/reel.wav`](preview/reel.wav) is a 24-second comparison of the
new packs, with its order and timings in [`preview/timeline.json`](preview/timeline.json).
Nothing plays automatically. These are review files; the release workflow still
uploads only `.clinkpack` assets and the manifest.

The checked-in page covers the twelve material packs. It is a few megabytes of
inlined audio, so it is not rebuilt for every pack; run `tools/build-preview.py`
to regenerate it locally when you want to hear Shot beside the others.

The new renderer uses the procedural techniques explored in Clonk's
`Sources/ClonkCore/Synth.swift`: noise excitation, resonant bodies, short contact
transients, and pre-rendered variations. Its Python implementation and parameter
sets are newly authored. No Clonk audio, recordings, or presets are reused.
Additional inharmonic modes, timed noise grains, and band-limited pitch bends
give the new families distinct shapes and textures. Three optional recipe fields
shape a sound that is not a struck body: `direct` mixes part of the excitation in
without sending it through the resonators, so noise stays flat instead of ringing;
`echoes` adds fixed, darkening reflections of the dry click; and `drive` applies
soft saturation normalised to the existing peak. A recipe that omits them renders
exactly as before, which the regression tests check.

[`tools/sound-recipes.json`](tools/sound-recipes.json) defines the materials and
their switch colors. [`tools/generate-sounds.py`](tools/generate-sounds.py) renders
the thirteen packs using only Python's standard library and fixed noise seeds.
It refuses recipes that replace the original four pack IDs. Generation uses
short onset/tail fades, DC correction, a 0.75 PCM peak ceiling, and level matching
between each pack's variations. Pack gains use a fixed per-click energy reference
measured from the original Clink packs; this is a level proxy, not a claim of
equal perceived loudness on every speaker. Listen at your normal typing volume
before choosing favorites.

From this repository directory:

```sh
python3 tools/generate-sounds.py
python3 tools/build-manifest.py
python3 tools/validate-manifest.py
python3 -m unittest discover -s tests
python3 tools/generate-sounds.py --check
python3 tools/analyze-sounds.py
python3 tools/build-preview.py
```

`--check` verifies generated output byte-for-byte without writing it. The
generator preserves all packs outside its explicit recipe list. Reports under
[`validation/`](validation) record synthesis provenance, asset hashes, format
checks, and measured audio characteristics. Existing payload hashes and the
legacy catalog contract remain protected by regression tests.

## Sound card artwork

New clients can display a colored switch and the first sample's waveform using
the manifest's optional `presentation` object. `Sounds/presentation.json` maps
stable pack IDs to an optional `switchTint` in `#RRGGBB` sRGB format. The manifest
generator derives 48 normalized peak-envelope amplitudes directly from the first
conditioned WAV. It focuses on the region above -36 dB relative to the peak, with
0.6 ms of leading and 2 ms of trailing context, so a quiet tail does not hide the
click's detail. Values remain raw amplitudes; clients can apply perceptual display
scaling. The generator does not synthesize a waveform or alter the audio.

The artwork is catalog metadata only. The original four `.clinkpack` payloads, pack IDs,
names, versions, URLs, SHA-256 hashes and byte counts remain unchanged. Older
clients ignore `presentation`; new clients accept older manifests without it.
Community repositories can omit `Sounds/presentation.json` entirely. The iOS
reader also ignores malformed optional artwork so audio downloads remain usable.
There are no added sound categories or new sound packs implied by a switch color.

Run the offline checks after changing the catalog tools:

```sh
python3 tools/build-manifest.py
python3 tools/validate-manifest.py
python3 -m unittest discover -s tests
```

`tests/fixtures/legacy-manifest.json` captures the download contract before artwork
was added. Its regression test verifies the existing release assets are identical.
Update that fixture deliberately only when an intended audio release changes the
corresponding contract; artwork alone must never require updating it.

## Make your first sound pack

1. Open Clink and go to **Customize → Feel**.
2. Create a custom sound pack and record or import up to four short sounds.
3. Export the pack as a `.clinkpack` file.
4. Put the exported file inside this repository's `Sounds` folder.
5. Push your changes to `main`.

The included GitHub workflow calculates the SHA-256 hash and byte count, builds `manifest.json`, and publishes the pack in the `latest` release. You do not need to create the manifest or release by hand.

A sound pack contains the pack metadata and conditioned mono 44.1 kHz WAV samples. Clink limits each sample to 0.5 seconds and each pack to four samples so the keyboard extension stays small and responsive.

## Add your repository to Clink

The official repository is available automatically under **Customize → Feel → Sound**. For a community repository, open **General → Repositories**, add `owner/repository`, then return to the sound source tabs and choose it.

## Make a sound pack with an AI agent

[`PROMPT.md`](PROMPT.md) is a ready-to-use brief for an AI coding agent. Fork the repository, open the fork in your agent, and say:

```text
Read PROMPT.md and add a sound pack with [describe its character and the samples I have].
```

The prompt directs the agent to the pack limits and manifest tools. Use it with sound files you created or may redistribute, then listen to the pack in Clink before publishing.

Clink downloads only public HTTPS GitHub release assets from the repository named in the manifest. It verifies the manifest, file size, SHA-256 hash, pack metadata, sample names, and WAV headers before copying the samples into the shared keyboard container.

## Licensing

Only publish sounds you created or have permission to redistribute. Add any attribution and licence information to this README or the pack description before publishing.

The thirteen new packs are original procedural audio created for Clink, with no
sampled third-party recordings. Their recipes, renderer, and generated assets
are covered by this repository's existing [Clink Community Assets License](LICENSE.md).

**Retro Phone** is the exception: it is a conditioned copy of a keypad tock WAV
that was published under the [WTFPL](http://www.wtfpl.net/), which permits
redistribution of verbatim or modified copies. Only the trim, fade, level and
format conditioning described above was applied to it. If you fork this
repository into a context where that provenance is not good enough for you,
delete `Sounds/retro-phone.clinkpack`, remove its `presentation.json` entry, and
rerun `tools/build-manifest.py`.
