#!/usr/bin/env python3
"""Independent PCM measurements for generated packs; never rewrites audio.

Uses only Python's standard library. Numerical similarity and signal statistics
are review evidence, not claims about perceived sound quality or loudness.
"""
import argparse
import base64
import cmath
import hashlib
import io
import json
import math
import pathlib
import statistics
import struct
import wave

NEW_PACK_IDS = (
    "velvet", "walnut", "bamboo", "porcelain", "copper", "titanium",
    "pebble", "rain", "bubble", "parchment", "relay", "arcade",
)
BASELINE_IDS = ("clicky", "marble", "tactile", "typewriter")
SAMPLE_RATE = 44_100
SPECTRAL_BANDS = (("below_250_hz", 0, 250), ("250_to_1000_hz", 250, 1000),
                  ("1000_to_3000_hz", 1000, 3000),
                  ("3000_to_8000_hz", 3000, 8000),
                  ("above_8000_hz", 8000, math.inf))


def db(value):
    return round(20 * math.log10(value), 5) if value > 0 else None


def fft(values):
    """Unwindowed radix-two FFT, zero-padded without altering input audio."""
    length = 1 << (len(values) - 1).bit_length()
    result = [complex(value) for value in values] + [0j] * (length - len(values))
    reversed_index = 0
    for index in range(1, length):
        bit = length >> 1
        while reversed_index & bit:
            reversed_index ^= bit
            bit >>= 1
        reversed_index ^= bit
        if index < reversed_index:
            result[index], result[reversed_index] = result[reversed_index], result[index]
    size = 2
    while size <= length:
        multiplier = cmath.exp(-2j * math.pi / size)
        half = size // 2
        for start in range(0, length, size):
            phase = 1 + 0j
            for index in range(start, start + half):
                lower = result[index]
                upper = result[index + half] * phase
                result[index] = lower + upper
                result[index + half] = lower - upper
                phase *= multiplier
        size *= 2
    return result


def decode_sample(encoded):
    raw = base64.b64decode(encoded, validate=True)
    with wave.open(io.BytesIO(raw), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        frames = source.getnframes()
        compression = source.getcomptype()
        pcm_bytes = source.readframes(frames)
    if (channels, width, rate, compression) != (1, 2, SAMPLE_RATE, "NONE"):
        raise ValueError(f"Expected mono 16-bit {SAMPLE_RATE} Hz PCM WAV; got "
                         f"channels={channels}, bits={width * 8}, rate={rate}, compression={compression}")
    if not frames or len(pcm_bytes) != frames * 2:
        raise ValueError("Empty or truncated PCM payload")
    integers = [item[0] for item in struct.iter_unpack("<h", pcm_bytes)]
    return {
        "wav_sha256": hashlib.sha256(raw).hexdigest(),
        "pcm_sha256": hashlib.sha256(pcm_bytes).hexdigest(),
        "wav_bytes": len(raw),
        "frames": frames,
        "sample_rate": rate,
        "channels": channels,
        "bits_per_sample": width * 8,
        "rail_sample_count": sum(value in (-32768, 32767) for value in integers),
    }, [value / 32768.0 for value in integers]


def sample_metrics(values, gain=1.0, rate=SAMPLE_RATE):
    count = len(values)
    peak = max(abs(value) for value in values)
    squares = [value * value for value in values]
    energy = math.fsum(squares)
    mean = math.fsum(values) / count
    rms = math.sqrt(energy / count)
    threshold = max(peak * 0.01, 1 / 32768)
    active = [index for index, value in enumerate(values) if abs(value) >= threshold]
    percentile_times = {}
    accumulated = 0.0
    for index, value in enumerate(squares):
        accumulated += value
        for percentile in (0.001, 0.5, 0.9, 0.99, 0.999):
            if energy and percentile not in percentile_times and accumulated >= energy * percentile:
                percentile_times[percentile] = index / rate * 1000
    window = max(1, round(rate * 0.020))
    running = sum(squares[:window])
    maximum_window_energy = running
    for index in range(window, count):
        running += squares[index] - squares[index - window]
        maximum_window_energy = max(maximum_window_energy, running)
    # Both RMS references have fixed time denominators so padding cannot change
    # comparisons. "gain" is the nominal pack trim, before app volume clamping.
    window_rms = math.sqrt(maximum_window_energy / window)
    reference_rms = math.sqrt(energy / (rate * 0.100))
    spectrum = fft([value - mean for value in values])
    bins = [(index * rate / len(spectrum), abs(value))
            for index, value in enumerate(spectrum[:len(spectrum) // 2 + 1]) if index > 0]
    magnitude_sum = math.fsum(magnitude for _, magnitude in bins)
    power_sum = math.fsum(magnitude * magnitude for _, magnitude in bins)
    magnitude_centroid = (math.fsum(frequency * magnitude for frequency, magnitude in bins)
                          / magnitude_sum if magnitude_sum else 0)
    power_centroid = (math.fsum(frequency * magnitude * magnitude for frequency, magnitude in bins)
                     / power_sum if power_sum else 0)
    power_bands = {
        name: round(math.fsum(magnitude * magnitude for frequency, magnitude in bins
                             if lower <= frequency < upper) / power_sum, 6) if power_sum else 0
        for name, lower, upper in SPECTRAL_BANDS
    }
    rolloff = 0.0
    accumulated_power = 0.0
    for frequency, magnitude in bins:
        accumulated_power += magnitude * magnitude
        if power_sum and accumulated_power >= power_sum * 0.85:
            rolloff = frequency
            break
    return {
        "duration_ms": round(count / rate * 1000, 5),
        "peak": round(peak, 8), "peak_dbfs": db(peak),
        "dc_mean": round(mean, 9), "dc_relative_to_rms_db": db(abs(mean) / rms) if rms else None,
        "rms": round(rms, 8), "rms_dbfs": db(rms),
        "crest_factor_db": db(peak / rms) if rms else None,
        "first_sample": values[0], "last_sample": values[-1],
        "onset_above_minus40db_relative_ms": round(active[0] / rate * 1000, 5) if active else None,
        "last_above_minus40db_relative_ms": round(active[-1] / rate * 1000, 5) if active else None,
        "energy_percentile_ms": {str(percentile): round(time, 5)
                                 for percentile, time in percentile_times.items()},
        "energy_duration_0_1_to_99_9_percent_ms": round(
            percentile_times.get(0.999, 0) - percentile_times.get(0.001, 0), 5),
        "energy_centroid_ms": round(math.fsum(index * value for index, value in enumerate(squares))
                                    / energy / rate * 1000, 5) if energy else 0,
        "peak_20ms_rms_dbfs": db(window_rms),
        "nominal_gain_peak_20ms_rms_dbfs": db(window_rms * gain),
        "equivalent_100ms_rms_dbfs": db(reference_rms),
        "nominal_gain_equivalent_100ms_rms_dbfs": db(reference_rms * gain),
        "spectral_magnitude_centroid_hz": round(magnitude_centroid, 3),
        "spectral_power_centroid_hz": round(power_centroid, 3),
        "spectral_power_rolloff85_hz": round(rolloff, 3),
        "spectral_power_bands": power_bands,
    }


def correlation_signal(values):
    # Four-frame box averaging limits work and suppresses some aliasing. These
    # correlations are coarse screening, not a perceptual similarity score.
    return [sum(values[index:index + 4]) / 4 for index in range(0, len(values), 4)]


def similarity(first, second):
    best = 0.0
    # Correlation over the whole overlapping signal, within +/-1.1ms; padding
    # the shorter clip keeps near-zero tiny overlaps from producing false 1s.
    length = max(len(first), len(second))
    left = first + [0.0] * (length - len(first))
    right = second + [0.0] * (length - len(second))
    left_mean, right_mean = sum(left) / length, sum(right) / length
    left = [value - left_mean for value in left]
    right = [value - right_mean for value in right]
    denominator = math.sqrt(sum(value * value for value in left) * sum(value * value for value in right))
    if not denominator:
        return 0.0
    for lag in range(-12, 13):
        start, stop = max(0, -lag), min(length, length - lag)
        covariance = sum(left[index] * right[index + lag] for index in range(start, stop))
        best = max(best, abs(covariance) / denominator)
    return round(min(1.0, best), 6)


def analyze(root, require_new=True):
    errors, review_flags, packs, signals = [], [], {}, {}
    pcm_owners = {}
    for pack_id in (*BASELINE_IDS, *NEW_PACK_IDS):
        path = root / "Sounds" / f"{pack_id}.clinkpack"
        if not path.exists():
            if require_new or pack_id in BASELINE_IDS:
                errors.append(f"Missing expected pack: {pack_id}")
            continue
        payload_bytes = path.read_bytes()
        try:
            payload = json.loads(payload_bytes)
            metadata = payload["pack"]
            samples = payload["samples"]
            gain = float(metadata.get("gain", 1.0))
            if not math.isfinite(gain) or gain <= 0:
                raise ValueError("Pack gain must be finite and positive")
            if len(samples) != len(metadata["sampleNames"]):
                raise ValueError("Sample count differs from sampleNames")
            if pack_id in NEW_PACK_IDS and len(samples) != 4:
                errors.append(f"{pack_id}: expected four new variants, got {len(samples)}")
            if len(set(metadata["sampleNames"])) != len(samples):
                errors.append(f"{pack_id}: duplicate sampleNames")
        except (KeyError, TypeError, ValueError) as error:
            errors.append(f"{pack_id}: invalid payload: {error}")
            continue
        measurements = []
        pack_signals = []
        for index, encoded in enumerate(samples):
            name = metadata["sampleNames"][index]
            try:
                info, values = decode_sample(encoded)
                metrics = sample_metrics(values, gain)
            except (TypeError, ValueError, wave.Error, EOFError, struct.error) as error:
                errors.append(f"{pack_id}/{name}: invalid audio: {error}")
                continue
            sample = {"name": name, **info, **metrics}
            measurements.append(sample)
            pack_signals.append(correlation_signal(values))
            owner = f"{pack_id}/{name}"
            duplicate = pcm_owners.get(info["pcm_sha256"])
            if duplicate and pack_id in NEW_PACK_IDS:
                errors.append(f"Exact duplicate PCM: {owner} and {duplicate}")
            pcm_owners[info["pcm_sha256"]] = owner
            if pack_id in NEW_PACK_IDS:
                if metrics["duration_ms"] > 500:
                    errors.append(f"{owner}: exceeds 0.5-second sample limit")
                if info["rail_sample_count"]:
                    errors.append(f"{owner}: PCM reaches integer clipping rails")
                if not metrics["peak"]:
                    errors.append(f"{owner}: silent sample")
                if max(abs(metrics["first_sample"]), abs(metrics["last_sample"])) > 1 / 32768:
                    review_flags.append(f"{owner}: boundary amplitude above one PCM step; inspect fade")
                if abs(metrics["dc_mean"]) > 0.001:
                    review_flags.append(f"{owner}: absolute mean/DC exceeds 0.001 full scale")
                onset = metrics["onset_above_minus40db_relative_ms"]
                if onset is not None and onset > 5:
                    review_flags.append(f"{owner}: onset above relative -40dB begins after 5ms")
        if not measurements:
            continue
        pairwise = []
        for left in range(len(measurements)):
            for right in range(left + 1, len(measurements)):
                correlation = similarity(pack_signals[left], pack_signals[right])
                pairwise.append({"samples": [measurements[left]["name"], measurements[right]["name"]],
                                 "maximum_absolute_correlation": correlation})
                if correlation > 0.98 and pack_id in NEW_PACK_IDS:
                    review_flags.append(f"{pack_id}: variants {left + 1}/{right + 1} correlate above 0.98")
        def median(key):
            present = [sample[key] for sample in measurements if sample[key] is not None]
            return round(statistics.median(present), 5) if present else None
        levels = [sample["nominal_gain_equivalent_100ms_rms_dbfs"] for sample in measurements
                  if sample["nominal_gain_equivalent_100ms_rms_dbfs"] is not None]
        packs[pack_id] = {
            "name": metadata.get("name"), "baseline": pack_id in BASELINE_IDS,
            "pack_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "pack_bytes": len(payload_bytes), "nominal_gain": gain,
            "sample_count": len(measurements),
            "median_nominal_gain_peak_20ms_rms_dbfs": median("nominal_gain_peak_20ms_rms_dbfs"),
            "median_nominal_gain_equivalent_100ms_rms_dbfs": median("nominal_gain_equivalent_100ms_rms_dbfs"),
            "variant_energy_spread_db": round(max(levels) - min(levels), 5) if levels else 0,
            "median_energy_duration_ms": median("energy_duration_0_1_to_99_9_percent_ms"),
            "median_spectral_power_centroid_hz": median("spectral_power_centroid_hz"),
            "median_spectral_power_bands": {
                name: round(statistics.median(sample["spectral_power_bands"][name] for sample in measurements), 6)
                for name, _, _ in SPECTRAL_BANDS},
            "variant_correlations": pairwise, "samples": measurements,
        }
        signals[pack_id] = pack_signals[0]
        if levels and max(levels) - min(levels) > 3 and pack_id in NEW_PACK_IDS:
            review_flags.append(f"{pack_id}: variant equivalent100ms energy differs by more than 3dB")
    baseline = [packs[name]["median_nominal_gain_equivalent_100ms_rms_dbfs"]
                for name in BASELINE_IDS if name in packs
                and packs[name]["median_nominal_gain_equivalent_100ms_rms_dbfs"] is not None]
    baseline_median = statistics.median(baseline) if baseline else None
    for pack_id, pack in packs.items():
        level = pack["median_nominal_gain_equivalent_100ms_rms_dbfs"]
        difference = (level - baseline_median
                      if baseline_median is not None and level is not None else None)
        pack["energy_difference_from_baseline_median_db"] = round(difference, 5) if difference is not None else None
        if difference is not None and abs(difference) > 6 and pack_id in NEW_PACK_IDS:
            review_flags.append(f"{pack_id}: nominal energy differs by more than 6dB from old-pack median")
    cross_family = []
    identifiers = list(packs)
    for left, first in enumerate(identifiers):
        for second in identifiers[left + 1:]:
            if first in BASELINE_IDS and second in BASELINE_IDS:
                continue
            p, q = packs[first], packs[second]
            correlation = similarity(signals[first], signals[second])
            distance = sum(abs(p["median_spectral_power_bands"][band]
                               - q["median_spectral_power_bands"][band])
                           for band, _, _ in SPECTRAL_BANDS)
            cross_family.append({"packs": [first, second],
                                 "first_variant_maximum_absolute_correlation": correlation,
                                 "median_band_power_l1_distance": round(distance, 6),
                                 "median_energy_duration_difference_ms": round(abs(
                                     p["median_energy_duration_ms"] - q["median_energy_duration_ms"]), 5)})
            if correlation > 0.98:
                review_flags.append(f"{first}/{second}: first variants correlate above 0.98")
    return {
        "passed": not errors, "errors": errors, "review_flags": review_flags,
        "source_sha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (root / "tools/analyze-sounds.py", root / "tools/generate-sounds.py",
                         root / "tools/sound-recipes.json") if path.is_file()
        },
        "method": {
            "runtime": "Python standard library only; no external audio/FFT dependencies",
            "spectral_analysis": "Mean-removed whole-sample unwindowed radix-two FFT with zero padding; one-sided bins excluding DC",
            "correlation": "Absolute normalized correlation on four-frame box-averaged PCM, zero-padded, lags +/-12 reduced-rate samples",
            "levels": "Nominal pack gain applied linearly; app volume curve, system volume compensation and playback-volume clamping excluded",
            "comparison_rms": "Peak rolling20ms RMS and equivalent100ms RMS use fixed-time denominators; trailing silence cannot lower either measurement",
            "review_thresholds": "Review flags are screening prompts, not automatic rejection: endpoint>1LSB, absDC>0.001, onset>5ms, correlation>0.98, variantEnergySpread>3dB, baselineEnergyDifference>6dB",
            "scope": "Quantitative PCM checks; does not establish audible quality, perceived loudness equality, or performance on physical speakers",
        },
        "expected_new_pack_ids": list(NEW_PACK_IDS),
        "baseline_median_nominal_gain_equivalent_100ms_rms_dbfs": round(baseline_median, 5) if baseline_median is not None else None,
        "packs": packs, "cross_family_comparisons": cross_family,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--allow-missing-new", action="store_true", help="Measure baseline before generation")
    args = parser.parse_args()
    report = analyze(args.root, require_new=not args.allow_missing_new)
    output = args.output or args.root / "validation/synthesis-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {len(report['packs'])} packs; "
          f"{len(report['errors'])} errors; {len(report['review_flags'])} review flags")
    print(output)
    for error in report["errors"]:
        print(f"ERROR: {error}")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
