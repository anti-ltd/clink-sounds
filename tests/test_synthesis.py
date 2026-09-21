"""Offline regressions for original synthesis and preservation of existing packs."""
import base64
import hashlib
import importlib.util
import io
import json
import math
import pathlib
import statistics
import struct
import tempfile
import unittest
import wave

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("generate_sounds", ROOT / "tools/generate-sounds.py")
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)
EXPECTED_IDS = {
    "velvet", "walnut", "bamboo", "porcelain", "copper", "titanium",
    "pebble", "rain", "bubble", "parchment", "relay", "arcade", "shot",
}


class SynthesisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recipes = GENERATOR.load_recipes()
        cls.generated = {recipe["id"]: GENERATOR.make_pack(recipe) for recipe in cls.recipes}

    def test_new_catalog_is_complete_and_separate_from_originals(self):
        self.assertEqual(set(self.generated), EXPECTED_IDS)
        self.assertTrue(EXPECTED_IDS.isdisjoint(GENERATOR.PROTECTED_IDS))

    def test_checked_in_payloads_reproduce_byte_for_byte(self):
        for identifier, payload in self.generated.items():
            with self.subTest(pack=identifier):
                self.assertEqual(GENERATOR.json_bytes(payload),
                                 (ROOT / "Sounds" / f"{identifier}.clinkpack").read_bytes())

    def test_noise_is_seeded_independently_of_render_order(self):
        recipe = self.recipes[0]
        first = GENERATOR.render_variant(recipe, 1)
        GENERATOR.render_variant(self.recipes[-1], 3)
        self.assertEqual(first, GENERATOR.render_variant(recipe, 1))

    def test_variants_are_unique_and_safe_for_keyboard_playback(self):
        all_pcm_hashes = set()
        for identifier, payload in self.generated.items():
            pack = payload["pack"]
            self.assertEqual(len(payload["samples"]), 4)
            self.assertEqual(len(set(pack["sampleNames"])), 4)
            self.assertEqual(pack["fileExtension"], "wav")
            self.assertGreater(pack["gain"], 0)
            for index, sample in enumerate(payload["samples"]):
                with self.subTest(pack=identifier, variant=index):
                    with wave.open(io.BytesIO(base64.b64decode(sample, validate=True)), "rb") as audio:
                        self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()),
                                         (1, 2, 44_100))
                        self.assertGreater(audio.getnframes(), 0)
                        self.assertLessEqual(audio.getnframes(), 22_050)
                        pcm_bytes = audio.readframes(audio.getnframes())
                    pcm = [item[0] for item in struct.iter_unpack("<h", pcm_bytes)]
                    self.assertEqual((pcm[0], pcm[-1]), (0, 0))
                    self.assertLessEqual(abs(statistics.fmean(pcm)), 2)
                    self.assertGreater(max(map(abs, pcm)), 0)
                    # Pack balancing may attenuate a variant; the ceiling is
                    # retained without forcing every variant to the same peak.
                    self.assertLessEqual(max(map(abs, pcm)), round(0.75 * 32767))
                    digest = hashlib.sha256(pcm_bytes).hexdigest()
                    self.assertNotIn(digest, all_pcm_hashes)
                    all_pcm_hashes.add(digest)
        self.assertEqual(len(all_pcm_hashes), len(EXPECTED_IDS) * 4)

    def test_variant_energy_is_balanced_to_each_pack_reference(self):
        for recipe in self.recipes:
            payload = self.generated[recipe["id"]]
            energies = []
            for sample in payload["samples"]:
                with wave.open(io.BytesIO(base64.b64decode(sample)), "rb") as audio:
                    values = struct.iter_unpack("<h", audio.readframes(audio.getnframes()))
                    energies.append(sum((value[0] / 32768) ** 2 for value in values))
            with self.subTest(pack=recipe["id"]):
                # Small tolerance for PCM16 rounding after per-variant gain.
                self.assertLess(10 * math.log10(max(energies) / min(energies)), 0.05)
                calibrated = statistics.median(energies) * payload["pack"]["gain"] ** 2
                self.assertAlmostEqual(calibrated, recipe["target_energy"],
                                       delta=recipe["target_energy"] * 0.002)

    def test_neutral_shaping_fields_change_nothing_and_active_ones_do(self):
        base = dict(self.recipes[0], id="probe")
        plain = GENERATOR.render_variant(base, 0)
        self.assertEqual(plain, GENERATOR.render_variant(dict(base, direct=0, drive=1, echoes=[]), 0))
        for field, value in (("direct", 0.5), ("drive", 3), ("echoes", [[20, 0.4, 3000]])):
            with self.subTest(field=field):
                self.assertNotEqual(plain, GENERATOR.render_variant(dict(base, **{field: value}), 0))

    def test_shaping_fields_outside_their_range_are_rejected(self):
        base = dict(self.recipes[0], id="probe")
        cases = [({"direct": 2.5}, "direct excitation"), ({"drive": 0.5}, "drive"),
                 ({"drive": 13}, "drive"), ({"echoes": [[500, 0.4, 3000]]}, "echo"),
                 ({"echoes": [[20, 1.4, 3000]]}, "echo"), ({"echoes": [[20, 0.4, 0]]}, "echo")]
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "recipes.json"
            for overrides, message in cases:
                with self.subTest(overrides=overrides):
                    path.write_text(json.dumps({"version": 1, "packs": [dict(base, **overrides)]}))
                    with self.assertRaisesRegex(ValueError, message):
                        GENERATOR.load_recipes(path)

    def test_an_echo_extends_the_tail_without_feeding_back(self):
        recipe = dict(self.recipes[0], id="probe", duration_ms=200, echoes=[[60, 0.5, 20000]])
        dry = GENERATOR.render_variant(dict(recipe, echoes=[]), 0)
        wet = GENERATOR.render_variant(recipe, 0)
        self.assertGreater(len(wet), len(dry))
        self.assertLessEqual(len(wet), round(200 * 44_100 / 1000))
        # A tap that a variant's stretch pushes past the buffer is dropped,
        # not wrapped around or fed back. Variant 3 stretches 199 ms to 204 ms.
        beyond = dict(recipe, echoes=[[60, 0.5, 20000], [199, 0.5, 20000]])
        self.assertEqual(GENERATOR.render_variant(recipe, 3), GENERATOR.render_variant(beyond, 3))

    def test_generator_rejects_overwriting_a_protected_pack(self):
        recipe = dict(self.recipes[0], id="tactile")
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "recipes.json"
            path.write_text(json.dumps({"version": 1, "packs": [recipe]}))
            with self.assertRaisesRegex(ValueError, "must not replace"):
                GENERATOR.load_recipes(path)

    def test_out_of_range_variant_indices_are_rejected(self):
        for index in (-1, 4):
            with self.assertRaisesRegex(ValueError, "out of range"):
                GENERATOR.render_variant(self.recipes[0], index)

    def test_original_payloads_still_match_frozen_release_hashes(self):
        legacy = json.loads((ROOT / "tests/fixtures/legacy-manifest.json").read_text())
        for pack in legacy["sounds"]:
            with self.subTest(pack=pack["id"]):
                raw = (ROOT / "Sounds" / pack["asset"]["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), pack["asset"]["sha256"])
                self.assertEqual(len(raw), pack["asset"]["byteCount"])

    def test_new_manifest_entries_match_payloads_and_recipe_tints(self):
        catalog = json.loads((ROOT / "manifest.json").read_text())
        entries = {pack["id"]: pack for pack in catalog["sounds"]}
        for recipe in self.recipes:
            identifier = recipe["id"]
            with self.subTest(pack=identifier):
                entry = entries[identifier]
                raw = (ROOT / "Sounds" / f"{identifier}.clinkpack").read_bytes()
                self.assertEqual(entry["asset"]["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(entry["asset"]["byteCount"], len(raw))
                self.assertEqual(entry["presentation"]["switchTint"], recipe["tint"])
                self.assertEqual(len(entry["presentation"]["waveform"]), 48)


if __name__ == "__main__":
    unittest.main()
