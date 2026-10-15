"""Strict ground-side analysis for simulated Neutron-2 pulse products."""

from __future__ import annotations

import json
import math
from typing import Any


PULSE_SCHEMA = "n2-pulses-v1"
MAX_RAW_BYTES = 1024 * 1024
MAX_EVENTS = 240
SAMPLE_COUNT = 64
SAMPLE_INTERVAL_NS = 10
ADC_BITS = 12
ADC_MAX = (1 << ADC_BITS) - 1
BASELINE_SAMPLES = 8
INTEGRATION_START = 8
TAIL_START = 20
INTEGRATION_END = 64
HISTOGRAM_BINS = 32

_ROOT_KEYS = {
    "schema", "simulated", "durationSeconds", "seed", "sampleIntervalNs",
    "adcBits", "baselineSamples", "integrationStart", "tailStart",
    "integrationEnd", "events",
}
_EVENT_KEYS = {"id", "timestampNs", "channel", "samples"}


def _object_no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _require_int(value: Any, name: str, minimum: int | None = None,
                 maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], name: str) -> None:
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing:
        raise ValueError(f"{name} is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"{name} has unsupported fields: {', '.join(sorted(extra))}")


def _bin_index(value: float, maximum: float, count: int) -> int:
    # Include the maximum legal value in the final bin.
    return min(count - 1, int(value / maximum * count))


def parse_pulses(raw: bytes) -> dict[str, Any]:
    """Validate and derive display products from one raw pulse JSON object.

    All charge values are ADC-sample area. PSD is tailCharge / totalCharge;
    this function intentionally does not assign detector classes.
    """
    if not isinstance(raw, bytes):
        raise ValueError("pulse science product must be bytes")
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("pulse science product exceeds the viewer's size limit")
    try:
        source = raw.decode("utf-8")
        document = json.loads(
            source,
            object_pairs_hook=_object_no_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("pulse science product is not valid UTF-8 JSON") from exc

    if not isinstance(document, dict):
        raise ValueError("pulse science product must be a JSON object")
    _require_exact_keys(document, _ROOT_KEYS, "pulse product")
    if document["schema"] != PULSE_SCHEMA:
        raise ValueError(f"pulse schema must be {PULSE_SCHEMA}")
    if document["simulated"] is not True:
        raise ValueError("pulse product must be explicitly simulated")

    duration = _require_int(document["durationSeconds"], "durationSeconds", 1, 120)
    seed = _require_int(document["seed"], "seed", 0, (1 << 32) - 1)
    fixed_metadata = {
        "sampleIntervalNs": SAMPLE_INTERVAL_NS,
        "adcBits": ADC_BITS,
        "baselineSamples": BASELINE_SAMPLES,
        "integrationStart": INTEGRATION_START,
        "tailStart": TAIL_START,
        "integrationEnd": INTEGRATION_END,
    }
    for name, expected in fixed_metadata.items():
        value = _require_int(document[name], name)
        if value != expected:
            raise ValueError(f"{name} must be {expected}")

    raw_events = document["events"]
    if not isinstance(raw_events, list):
        raise ValueError("events must be an array")
    event_count = len(raw_events)
    if event_count != 2 * duration or event_count > MAX_EVENTS:
        raise ValueError("event count must equal two events per exposure second and stay within 240")

    derived_events: list[dict[str, Any]] = []
    waveforms: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    previous_timestamp = -1
    exposure_ns = duration * 1_000_000_000

    for index, event in enumerate(raw_events):
        if not isinstance(event, dict):
            raise ValueError(f"event {index + 1} must be an object")
        _require_exact_keys(event, _EVENT_KEYS, f"event {index + 1}")
        event_id = _require_int(event["id"], f"event {index + 1} id", 1, event_count)
        if event_id in seen_ids:
            raise ValueError("event ids must be unique")
        seen_ids.add(event_id)
        timestamp_ns = _require_int(event["timestampNs"], f"event {event_id} timestampNs", 0)
        if timestamp_ns >= exposure_ns:
            raise ValueError(f"event {event_id} timestampNs is outside the exposure")
        if timestamp_ns < previous_timestamp:
            raise ValueError("event timestamps must be ordered")
        previous_timestamp = timestamp_ns
        channel = _require_int(event["channel"], f"event {event_id} channel", 0, 0)

        samples = event["samples"]
        if not isinstance(samples, list) or len(samples) != SAMPLE_COUNT:
            raise ValueError(f"event {event_id} samples must contain exactly {SAMPLE_COUNT} ADC values")
        raw_samples = [
            _require_int(sample, f"event {event_id} sample {sample_index}", 0, ADC_MAX)
            for sample_index, sample in enumerate(samples)
        ]

        baseline = sum(raw_samples[:BASELINE_SAMPLES]) / BASELINE_SAMPLES
        corrected = [max(0.0, float(sample) - baseline) for sample in raw_samples]
        total_charge = sum(corrected[INTEGRATION_START:INTEGRATION_END])
        tail_charge = sum(corrected[TAIL_START:INTEGRATION_END])
        if not math.isfinite(baseline) or not math.isfinite(total_charge) or not math.isfinite(tail_charge):
            raise ValueError(f"event {event_id} derived values must be finite")
        if total_charge <= 0:
            raise ValueError(f"event {event_id} has zero integrated charge")
        psd = tail_charge / total_charge
        derived_events.append({
            "id": event_id,
            "channel": channel,
            "timestampNs": timestamp_ns,
            "totalCharge": total_charge,
            "tailCharge": tail_charge,
            "psd": psd,
        })
        waveforms.append({
            "eventId": event_id,
            "channel": channel,
            "timestampNs": timestamp_ns,
            "baseline": baseline,
            "sampleTimesNs": [i * SAMPLE_INTERVAL_NS for i in range(SAMPLE_COUNT)],
            "rawSamples": raw_samples,
            "baselineCorrectedSamples": corrected,
        })

    if seen_ids != set(range(1, event_count + 1)):
        raise ValueError("event ids must be the sequence 1 through eventCount")

    # A 5% margin leaves room beyond the largest event while using the
    # 32-bin charge axis effectively for these product-specific amplitudes.
    charge_maximum = (max(event["totalCharge"] for event in derived_events) * 1.05
                      if derived_events else 1.0)
    if not math.isfinite(charge_maximum) or charge_maximum <= 0:
        raise ValueError("derived charge axis range must be finite and positive")
    charge_spectrum = [0] * HISTOGRAM_BINS
    psd_density = [[0] * HISTOGRAM_BINS for _ in range(HISTOGRAM_BINS)]
    for event in derived_events:
        charge_bin = _bin_index(event["totalCharge"], charge_maximum, HISTOGRAM_BINS)
        psd_bin = min(HISTOGRAM_BINS - 1, int(event["psd"] * HISTOGRAM_BINS))
        charge_spectrum[charge_bin] += 1
        psd_density[psd_bin][charge_bin] += 1

    return {
        "scienceType": "pulses",
        "schema": PULSE_SCHEMA,
        "simulated": True,
        "durationSeconds": duration,
        "seed": seed,
        "sampleIntervalNs": SAMPLE_INTERVAL_NS,
        "adcBits": ADC_BITS,
        "eventCount": event_count,
        "waveforms": waveforms,
        "events": derived_events,
        "chargeSpectrum": {
            "binCount": HISTOGRAM_BINS,
            "minimum": 0,
            "maximum": charge_maximum,
            "binWidth": charge_maximum / HISTOGRAM_BINS,
            "counts": charge_spectrum,
            "xLabel": "Integrated charge (ADC-sample area)",
            "rangePolicy": "1.05 times the largest event totalCharge; 1 when empty",
        },
        "psdDensity": {
            "chargeBinCount": HISTOGRAM_BINS,
            "psdBinCount": HISTOGRAM_BINS,
            "chargeMinimum": 0,
            "chargeMaximum": charge_maximum,
            "psdMinimum": 0,
            "psdMaximum": 1,
            "counts": psd_density,
            "normalization": "event-count",
            "layout": "counts[psdBin][chargeBin]",
            "xLabel": "Integrated charge (ADC-sample area)",
            "yLabel": "PSD (tailCharge / totalCharge)",
        },
    }
