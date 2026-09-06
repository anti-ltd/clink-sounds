"""Release validation rejects invalid variants before publishing any catalog."""
import base64
import copy
import hashlib
import importlib.util
import io
import json
import pathlib
import struct
import tempfile
import unittest
import wave

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_manifest", ROOT / "tools" / "validate-manifest.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
REPOSITORY = "anti-ltd/clink-sounds"


def wav_bytes(frames=64, channels=1, width=2, rate=44_100):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes((b"\x01" * width) * frames * channels)
    return output.getvalue()


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        (self.root / "Sounds").mkdir()
        encoded = base64.b64encode(wav_bytes()).decode("ascii")
        self.payload = {
            "pack": {"id": "test", "name": "Test", "blurb": "Original synthesis.",
                     "source": "bundled", "fileExtension": "wav", "gain": 0.25,
                     "sampleNames": ["take-1", "take-2"]},
            "samples": [encoded, encoded],
        }
        self.manifest = {"version": "latest", "sounds": [{
            "id": "test", "name": "Test", "version": "latest",
            "asset": {"path": "test.clinkpack",
                      "url": f"https://github.com/{REPOSITORY}/releases/download/latest/test.clinkpack"},
            "presentation": {"switchTint": "#123ABC", "waveform": [0, 1, 0.25]},
        }]}
        self.publish_payload()

    def publish_payload(self, raw=None):
        raw = raw if raw is not None else json.dumps(self.payload).encode()
        (self.root / "Sounds" / "test.clinkpack").write_bytes(raw)
        self.manifest["sounds"][0]["asset"].update(sha256=hashlib.sha256(raw).hexdigest(), byteCount=len(raw))
        self.publish_manifest()

    def publish_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))

    def assert_invalid(self, message):
        errors = VALIDATOR.validate_manifest(self.root)
        self.assertTrue(any(message in error for error in errors), errors)

    def test_repository_catalog_and_every_existing_variant_are_valid(self):
        self.assertEqual(VALIDATOR.validate_manifest(ROOT), [])

    def test_valid_pack_accepts_positive_gain_below_editor_slider_range(self):
        self.assertEqual(VALIDATOR.validate_manifest(self.root), [])

    def test_optional_payload_defaults_and_additive_metadata_remain_valid(self):
        for key in ["gain", "source", "fileExtension", "blurb"]:
            del self.payload["pack"][key]
        self.payload["futureField"] = {"notes": "ignorable metadata"}
        self.publish_payload()
        self.assertEqual(VALIDATOR.validate_manifest(self.root), [])

    def test_source_uses_only_existing_client_enum_cases(self):
        for source in ["bundled", "custom", "external"]:
            self.payload["pack"]["source"] = source
            self.publish_payload()
            self.assertEqual(VALIDATOR.validate_manifest(self.root), [])
        self.payload["pack"]["source"] = "synthesized"
        self.publish_payload()
        self.assert_invalid("source must be")

    def test_every_variant_is_decoded_not_just_the_preview_sample(self):
        for options in [{"channels": 2}, {"width": 1}, {"width": 3}, {"rate": 48_000}]:
            with self.subTest(options=options):
                self.payload["samples"][1] = base64.b64encode(wav_bytes(**options)).decode()
                self.publish_payload()
                self.assert_invalid("sample 2: expected mono 16-bit PCM")

    def test_sample_duration_boundary_and_truncation(self):
        self.payload["samples"][1] = base64.b64encode(wav_bytes(frames=22_050)).decode()
        self.publish_payload()
        self.assertEqual(VALIDATOR.validate_manifest(self.root), [])
        self.payload["samples"][1] = base64.b64encode(wav_bytes(frames=22_051)).decode()
        self.publish_payload()
        self.assert_invalid("at most 0.5 seconds")
        truncated = wav_bytes()[:-2]
        # Match the container's byte count but leave the data chunk incomplete.
        truncated = truncated[:4] + struct.pack("<I", len(truncated) - 8) + truncated[8:]
        self.payload["samples"][1] = base64.b64encode(truncated).decode()
        self.publish_payload()
        self.assert_invalid("WAV sample data is truncated")

    def test_malformed_base64_riff_and_decoded_size_are_rejected(self):
        for sample, expected in [("not base64!", "invalid base64"),
                                 (None, "base64 text"),
                                 (base64.b64encode(b"x" * 100).decode(), "RIFF/WAVE"),
                                 (base64.b64encode(wav_bytes()[:-1]).decode(), "RIFF size"),
                                 (base64.b64encode(b"x" * 80_001).decode(), "45–80000 bytes")]:
            with self.subTest(expected=expected):
                self.payload["samples"][1] = sample
                self.publish_payload()
                self.assert_invalid(expected)

    def test_names_are_unique_safe_and_match_one_to_four_samples(self):
        for names, expected in [(["take-1", "take-1"], "must be unique"),
                                (["../take", "take-2"], "unsafe characters"),
                                ([{}, "take-2"], "unsafe characters"),
                                (["take-1"], "count does not match"),
                                ([], "one to four sample names"),
                                ([f"take-{i}" for i in range(5)], "one to four sample names")]:
            with self.subTest(names=names):
                self.payload["pack"]["sampleNames"] = names
                self.publish_payload()
                self.assert_invalid(expected)

    def test_gain_is_numeric_positive_and_finite(self):
        for gain in [0, -1, True, "1", None, 10 ** 400, float("inf"), float("nan")]:
            with self.subTest(gain=str(gain)[:30]):
                self.payload["pack"]["gain"] = gain
                self.publish_payload()
                self.assertTrue(VALIDATOR.validate_manifest(self.root))

    def test_payload_metadata_and_byte_limit(self):
        for key, value, expected in [("id", "../test", "payload id"),
                                     ("name", "Changed", "name does not match"),
                                     ("blurb", [], "blurb must be text"),
                                     ("fileExtension", "mp3", "fileExtension must be wav")]:
            with self.subTest(key=key):
                old = self.payload["pack"][key]
                self.payload["pack"][key] = value
                self.publish_payload()
                self.assert_invalid(expected)
                self.payload["pack"][key] = old
        self.payload["pack"]["blurb"] = "x" * 512_000
        self.publish_payload()
        self.assert_invalid("payload must contain 1–512000 bytes")

    def test_raw_json_requires_objects_and_unambiguous_keys(self):
        for raw in [b"[]", b'{"pack":null}', b'{"pack":{},"pack":{}}', b"broken", b"\xff"]:
            with self.subTest(raw=raw):
                self.publish_payload(raw)
                self.assertTrue(VALIDATOR.validate_manifest(self.root))
        (self.root / "manifest.json").write_text('{"version":"latest","sounds":[],"sounds":[]}')
        self.assert_invalid("invalid JSON")

    def test_catalog_identity_and_shape_are_checked(self):
        sound = self.manifest["sounds"][0]
        self.manifest["sounds"].append(copy.deepcopy(sound))
        self.publish_manifest()
        self.assert_invalid("duplicate catalog id")
        self.manifest["sounds"].pop()
        for key, value, expected in [("id", "../test", "catalog id"),
                                     ("id", "different", "id must match filename"),
                                     ("name", "x" * 81, "1–80 characters"),
                                     ("name", " ", "1–80 characters"),
                                     ("version", "../latest", "version must be")]:
            with self.subTest(key=key, value=value):
                old = sound[key]
                sound[key] = value
                self.publish_manifest()
                self.assert_invalid(expected)
                sound[key] = old

    def test_assets_require_safe_paths_exact_hash_sizes_and_repository_urls(self):
        asset = self.manifest["sounds"][0]["asset"]
        for key, value, expected in [("path", "../test.clinkpack", "safe .clinkpack filename"),
                                     ("sha256", "a" * 64, "SHA-256 is incorrect"),
                                     ("byteCount", True, "byteCount is incorrect"),
                                     ("byteCount", 512_001, "byteCount is incorrect")]:
            with self.subTest(key=key):
                old = asset[key]
                asset[key] = value
                self.publish_manifest()
                self.assert_invalid(expected)
                asset[key] = old
        for url in ["http://github.com/anti-ltd/clink-sounds/releases/download/latest/test.clinkpack",
                    "https://github.com/unapproved/sounds/releases/download/latest/test.clinkpack",
                    "https://github.com/anti-ltd/clink-sounds/blob/main/test.clinkpack",
                    "https://github.com/anti-ltd/clink-sounds/releases/download/latest/other.clinkpack",
                    "https://github.com/anti-ltd/clink-sounds/releases/download/%2E%2E/test.clinkpack",
                    "https://github.com/anti-ltd/clink-sounds/releases/download/latest/test.clinkpack?file=other"]:
            with self.subTest(url=url):
                asset["url"] = url
                self.publish_manifest()
                self.assert_invalid("HTTPS GitHub release asset")

    def test_missing_assets_and_unindexed_release_files_are_rejected(self):
        (self.root / "Sounds" / "extra.clinkpack").write_bytes(b"{}")
        self.assert_invalid("release asset is missing from the manifest")
        (self.root / "Sounds" / "test.clinkpack").unlink()
        self.assert_invalid("asset is missing")

    def test_optional_presentation_bounds_do_not_allow_bools_or_nonfinite_values(self):
        sound = self.manifest["sounds"][0]
        for presentation in [[], {"switchTint": "red"}, {"waveform": [True, 1]},
                             {"waveform": [0, 1.1]}, {"waveform": [0]},
                             {"waveform": [0, 10 ** 400]}]:
            with self.subTest(presentation=str(presentation)[:60]):
                sound["presentation"] = presentation
                self.publish_manifest()
                self.assertTrue(VALIDATOR.validate_manifest(self.root))
        del sound["presentation"]
        self.publish_manifest()
        self.assertEqual(VALIDATOR.validate_manifest(self.root), [])


if __name__ == "__main__":
    unittest.main()
