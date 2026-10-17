"""Offline checks for the additive catalog artwork and existing download contract."""
import base64
import hashlib
import importlib.util
import io
import json
import pathlib
import shutil
import struct
import tempfile
import unittest
import wave

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_manifest", ROOT / "tools" / "build-manifest.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
REPOSITORY = "anti-ltd/clink-sounds"


def encoded_wav(values):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44_100)
        audio.writeframes(struct.pack("<" + "h" * len(values), *values))
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class ManifestTests(unittest.TestCase):
    def test_existing_production_download_contract_is_unchanged(self):
        """Every pack must still deliver the same bytes under the same id.

        Releases are content-addressed now, so the tag in the version and the
        asset URL is expected to differ from the legacy fixture. Everything a
        client actually verifies a download against - id, name, path, digest
        and byte count - must survive untouched.
        """
        legacy = json.loads((ROOT / "tests" / "fixtures" / "legacy-manifest.json").read_text())
        current = BUILDER.build_manifest(ROOT, REPOSITORY)
        version = current["version"]
        self.assertTrue(version.startswith("sounds-"), version)
        self.assertEqual(len(version), len("sounds-") + 64)
        indexed = {pack["id"]: pack for pack in current["sounds"]}
        for original in legacy["sounds"]:
            pack = indexed[original["id"]]
            expected = {key: value for key, value in original.items() if key != "asset"}
            expected["version"] = version
            self.assertEqual({key: value for key, value in pack.items()
                              if key not in {"presentation", "asset", "platform"}}, expected)
            # The URL may only differ from the legacy one by its release tag.
            self.assertEqual(pack["asset"]["url"],
                             original["asset"]["url"].replace("/download/%s/" % legacy["version"],
                                                              "/download/%s/" % version))
            self.assertEqual({key: value for key, value in pack["asset"].items() if key != "url"},
                             {key: value for key, value in original["asset"].items() if key != "url"})
            raw = (ROOT / "Sounds" / pack["asset"]["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), original["asset"]["sha256"])
            self.assertEqual(len(raw), original["asset"]["byteCount"])

    def test_generated_manifest_is_reproducible(self):
        self.assertEqual(BUILDER.build_manifest(ROOT, REPOSITORY),
                         json.loads((ROOT / "manifest.json").read_text()))

    def test_official_waveforms_retain_actual_first_sample_detail(self):
        for pack in BUILDER.build_manifest(ROOT, REPOSITORY)["sounds"]:
            payload = json.loads((ROOT / "Sounds" / pack["asset"]["path"]).read_text())
            with wave.open(io.BytesIO(base64.b64decode(payload["samples"][0])), "rb") as audio:
                values = struct.unpack("<" + "h" * audio.getnframes(), audio.readframes(audio.getnframes()))
            waveform = pack["presentation"]["waveform"]
            self.assertEqual(len(waveform), 48)
            self.assertEqual(max(waveform), 1)
            # Extending a file's already silent tail must not shrink its click.
            self.assertEqual(BUILDER.sample_waveform(encoded_wav([*values, *([0] * 22_050)])), waveform)
            self.assertGreater(sum(value > 0.03 for value in waveform), 20)

    def test_short_click_uses_width_and_preserves_raw_amplitude(self):
        # A 10 ms click surrounded by almost half a second of silence. The two
        # plateaus must remain distinguishable, not disappear into the first bin.
        click = [30_000] * 220 + [7_500] * 221
        waveform = BUILDER.sample_waveform(encoded_wav([0] * 2_205 + click + [0] * 19_404))
        self.assertGreater(sum(value > 0 for value in waveform), 32)
        self.assertGreater(waveform.index(1.0), 0)
        self.assertIn(0.25, waveform)  # No square-root/log scaling in metadata.
        self.assertEqual(waveform[-1], 0)

    def test_a_gap_between_clicks_stays_silent(self):
        values = [12_000] * 100 + [0] * 441 + [-24_000] * 100
        waveform = BUILDER.sample_waveform(encoded_wav(values))
        self.assertEqual(waveform[0], 0.5)
        self.assertEqual(waveform[24], 0)
        self.assertEqual(waveform[-1], 1)

    def test_silent_and_single_frame_audio_are_supported(self):
        self.assertEqual(BUILDER.sample_waveform(encoded_wav([0] * 500)), [0.0] * 48)
        self.assertEqual(BUILDER.sample_waveform(encoded_wav([-32_768])), [1.0] * 48)

    def test_community_pack_needs_no_presentation_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "Sounds").mkdir()
            shutil.copyfile(ROOT / "Sounds" / "clicky.clinkpack", root / "Sounds" / "custom.clinkpack")
            pack = BUILDER.build_manifest(root, "community/sounds")["sounds"][0]
            self.assertNotIn("switchTint", pack["presentation"])
            self.assertEqual(len(pack["presentation"]["waveform"]), 48)
            self.assertIn("/community/sounds/", pack["asset"]["url"])

    def test_invalid_tint_fails_before_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "Sounds").mkdir()
            shutil.copyfile(ROOT / "Sounds" / "clicky.clinkpack", root / "Sounds" / "clicky.clinkpack")
            (root / "Sounds" / "presentation.json").write_text('{"clicky":{"switchTint":"blue"}}')
            with self.assertRaisesRegex(ValueError, "switchTint must be #RRGGBB"):
                BUILDER.build_manifest(root, REPOSITORY)


if __name__ == "__main__":
    unittest.main()
