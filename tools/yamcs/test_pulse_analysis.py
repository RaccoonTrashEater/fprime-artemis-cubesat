import json
import unittest

from pulse_analysis import parse_pulses


def make_event(event_id, timestamp_ns, charge_shape="mixed"):
    samples = [100] * 64
    if charge_shape == "mixed":
        samples[8:20] = [110] * 12
        samples[20:64] = [120] * 44
    elif charge_shape == "small":
        samples[8:64] = [101] * 56
    return {"id": event_id, "timestampNs": timestamp_ns, "channel": 0, "samples": samples}


def make_document(events=None, **overrides):
    document = {
        "schema": "n2-pulses-v1",
        "simulated": True,
        "durationSeconds": 1,
        "seed": 17,
        "sampleIntervalNs": 10,
        "adcBits": 12,
        "baselineSamples": 8,
        "integrationStart": 8,
        "tailStart": 20,
        "integrationEnd": 64,
        "events": [make_event(1, 10), make_event(2, 30, "small")] if events is None else events,
    }
    document.update(overrides)
    return document


def encode(document):
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


class PulseAnalysisTests(unittest.TestCase):
    def test_baseline_charge_waveforms_and_histogram_projections(self):
        result = parse_pulses(encode(make_document()))
        self.assertEqual(result["scienceType"], "pulses")
        self.assertEqual(result["schema"], "n2-pulses-v1")
        self.assertIs(result["simulated"], True)
        self.assertEqual(result["eventCount"], 2)
        first, second = result["events"]
        self.assertEqual((first["totalCharge"], first["tailCharge"], first["psd"]), (1000.0, 880.0, 0.88))
        self.assertEqual((second["totalCharge"], second["tailCharge"]), (56.0, 44.0))

        waveform = result["waveforms"][0]
        self.assertEqual(waveform["baseline"], 100.0)
        self.assertEqual(len(waveform["rawSamples"]), 64)
        self.assertEqual(len(waveform["baselineCorrectedSamples"]), 64)
        self.assertEqual(waveform["sampleTimesNs"], [i * 10 for i in range(64)])
        self.assertEqual(waveform["baselineCorrectedSamples"][:8], [0.0] * 8)
        self.assertEqual(waveform["baselineCorrectedSamples"][8], 10.0)
        self.assertEqual(waveform["baselineCorrectedSamples"][20], 20.0)

        spectrum = result["chargeSpectrum"]
        density = result["psdDensity"]
        self.assertEqual(len(spectrum["counts"]), 32)
        self.assertEqual(len(density["counts"]), 32)
        self.assertTrue(all(len(row) == 32 for row in density["counts"]))
        self.assertAlmostEqual(spectrum["maximum"], 1050.0)
        self.assertEqual(sum(spectrum["counts"]), 2)
        self.assertEqual(sum(map(sum, density["counts"])), 2)
        for event in result["events"]:
            charge_bin = min(31, int(event["totalCharge"] / spectrum["maximum"] * 32))
            psd_bin = min(31, int(event["psd"] * 32))
            self.assertEqual(density["counts"][psd_bin][charge_bin], 1)
            self.assertGreaterEqual(spectrum["counts"][charge_bin], 1)

    def test_event_count_must_match_two_events_per_exposure_second(self):
        with self.assertRaisesRegex(ValueError, "two events per exposure second"):
            parse_pulses(encode(make_document(events=[])))

    def test_rejects_boolean_in_integer_fields(self):
        document = make_document()
        document["durationSeconds"] = True
        with self.assertRaisesRegex(ValueError, "durationSeconds must be an integer"):
            parse_pulses(encode(document))
        document = make_document()
        document["events"][0]["samples"][8] = True
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            parse_pulses(encode(document))

    def test_rejects_invalid_metadata_and_unknown_fields(self):
        for field, value in (("schema", "future"), ("simulated", False), ("durationSeconds", 121),
                             ("sampleIntervalNs", 20), ("tailStart", 64)):
            document = make_document()
            document[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_pulses(encode(document))
        document = make_document()
        document["script"] = "untrusted"
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            parse_pulses(encode(document))

    def test_rejects_bad_samples_zero_area_and_nonfinite_json(self):
        document = make_document()
        document["events"][0]["samples"] = [100] * 63
        with self.assertRaisesRegex(ValueError, "exactly 64"):
            parse_pulses(encode(document))
        document = make_document()
        document["events"][0]["samples"][9] = 4096
        with self.assertRaisesRegex(ValueError, "at most 4095"):
            parse_pulses(encode(document))
        zero_area = make_event(1, 0)
        zero_area["samples"] = [100] * 64
        with self.assertRaisesRegex(ValueError, "zero integrated charge"):
            parse_pulses(encode(make_document(events=[zero_area, make_event(2, 5)])))
        with self.assertRaisesRegex(ValueError, "non-finite"):
            parse_pulses(b'{"value":NaN}')

    def test_rejects_event_count_ids_order_and_exposure_violations(self):
        events = [make_event(1, 0), make_event(2, 1)]
        events[1]["id"] = 1
        with self.assertRaisesRegex(ValueError, "unique"):
            parse_pulses(encode(make_document(events=events)))
        events = [make_event(1, 10), make_event(2, 9)]
        with self.assertRaisesRegex(ValueError, "timestamps must be ordered"):
            parse_pulses(encode(make_document(events=events)))
        events = [make_event(1, 10), make_event(2, 1_000_000_000)]
        with self.assertRaisesRegex(ValueError, "outside the exposure"):
            parse_pulses(encode(make_document(events=events)))
        too_many_for_duration = [make_event(i, i) for i in range(1, 4)]
        with self.assertRaisesRegex(ValueError, "two events per exposure second"):
            parse_pulses(encode(make_document(events=too_many_for_duration, durationSeconds=120)))

    def test_rejects_duplicate_json_keys(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            parse_pulses(b'{"schema":"n2-pulses-v1","schema":"n2-pulses-v1"}')


if __name__ == "__main__":
    unittest.main()
