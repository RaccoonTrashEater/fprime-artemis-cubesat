from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import socket
import threading
import unittest
from urllib import parse, request

from science_ingest import crc16_ccitt
from science_viewer import LocalScienceViewer, RECEIPT_EVENT


class FakeYamcs(ThreadingHTTPServer):
    daemon_threads = True


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.run_id = "run-test"
        self.raw = b"t_s,counts,flag\n0,5,BG\n1,7,SAA\n2,5,BG\n"
        self.object_name = "n2-science-run-test-00000004-09-test.bin"
        self.receipt_name = self.object_name + ".receipt.json"
        self.manifest = {
            "runId": self.run_id,
            "productId": 4,
            "transferId": 9,
            "bytes": len(self.raw),
            "packetCount": 2,
            "crc16Ccitt": crc16_ccitt(self.raw),
            "sha256": hashlib.sha256(self.raw).hexdigest(),
            "objectName": self.object_name,
            "receiptObject": self.receipt_name,
            "verifiedGroundReceipt": True,
        }
        self.receipt_bytes = (json.dumps(self.manifest) + "\n").encode()
        self.extra = {
            "runId": self.run_id,
            "productId": "4",
            "transferId": "9",
            "bytes": str(len(self.raw)),
            "crc16Ccitt": str(self.manifest["crc16Ccitt"]),
            "sha256": self.manifest["sha256"],
            "objectName": self.object_name,
            "receiptObject": self.receipt_name,
            "verifiedGroundReceipt": "true",
        }

        raw = self.raw
        receipt = self.receipt_bytes
        extra = self.extra

        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner_self):  # noqa: N802
                split = parse.urlsplit(inner_self.path)
                if split.path == "/api/archive/fprime-project/events":
                    body = json.dumps({"events": [{"type": RECEIPT_EVENT, "extra": extra}]}).encode()
                elif split.path.endswith("/" + parse.quote(self.receipt_name, safe="")):
                    body = receipt
                elif split.path.endswith("/" + parse.quote(self.object_name, safe="")):
                    body = raw
                else:
                    inner_self.send_error(404)
                    return
                inner_self.send_response(200)
                inner_self.send_header("Content-Length", str(len(body)))
                inner_self.end_headers()
                inner_self.wfile.write(body)

            def log_message(self, format, *args):
                return

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            yamcs_port = sock.getsockname()[1]
        self.yamcs = FakeYamcs(("127.0.0.1", yamcs_port), Handler)
        self.yamcs_thread = threading.Thread(target=self.yamcs.serve_forever, daemon=True)
        self.yamcs_thread.start()

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            viewer_port = sock.getsockname()[1]
        self.viewer = LocalScienceViewer(self.run_id, port=viewer_port,
                                         yamcs_url=f"http://127.0.0.1:{yamcs_port}")
        self.viewer.start()

    def tearDown(self):
        self.viewer.close()
        self.yamcs.shutdown()
        self.yamcs.server_close()
        self.yamcs_thread.join(timeout=1)

    def test_api_returns_yamcs_identity_hash_and_simulated_frequency(self):
        url = self.viewer.url + "/api/product?" + parse.urlencode({"receipt": self.receipt_name})
        with request.urlopen(url, timeout=2) as response:
            product = json.load(response)
        self.assertEqual(product["objectName"], self.object_name)
        self.assertEqual(product["sha256"], self.manifest["sha256"])
        self.assertEqual(product["readbackSha256"], self.manifest["sha256"])
        self.assertEqual(product["histogram"]["windows"], 3)
        self.assertEqual(product["histogram"]["totalCounts"], 17)
        self.assertEqual(product["histogram"]["frequencies"], {"5": 2, "7": 1})
        self.assertIn("not a detector-energy histogram", product["histogram"]["label"])

    def test_pulse_readback_adds_nested_science_derived_from_verified_bytes(self):
        samples = [100] * 64
        samples[8:20] = [110] * 12
        samples[20:64] = [120] * 44
        small = [100] * 64
        small[8:64] = [101] * 56
        raw = json.dumps({
            "schema": "n2-pulses-v1", "simulated": True, "durationSeconds": 1,
            "seed": 9, "sampleIntervalNs": 10, "adcBits": 12,
            "baselineSamples": 8, "integrationStart": 8, "tailStart": 20,
            "integrationEnd": 64,
            "events": [
                {"id": 1, "timestampNs": 10, "channel": 0, "samples": samples},
                {"id": 2, "timestampNs": 30, "channel": 0, "samples": small},
            ],
        }, separators=(",", ":")).encode()
        manifest = dict(self.manifest)
        manifest.update({
            "bytes": len(raw),
            "crc16Ccitt": crc16_ccitt(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
        receipt_bytes = (json.dumps(manifest) + "\n").encode()
        original_get_bytes = self.viewer._get_bytes

        def get_bytes(path, maximum):
            return receipt_bytes if self.receipt_name in path else raw

        self.viewer._get_bytes = get_bytes
        try:
            product, readback = self.viewer._read_product(self.receipt_name)
        finally:
            self.viewer._get_bytes = original_get_bytes

        self.assertEqual(readback, raw)
        self.assertEqual(product["readbackSha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(product["scienceType"], "pulses")
        self.assertEqual(product["science"]["schema"], "n2-pulses-v1")
        self.assertEqual(product["science"]["events"][0]["totalCharge"], 1000.0)
        self.assertEqual(product["science"]["waveforms"][0]["sampleTimesNs"], [i * 10 for i in range(64)])

    def test_verified_but_invalid_pulse_is_returned_as_listing_error(self):
        raw = json.dumps({
            "schema": "n2-pulses-v1", "simulated": True, "durationSeconds": 1,
            "seed": 9, "sampleIntervalNs": 10, "adcBits": 12,
            "baselineSamples": 8, "integrationStart": 8, "tailStart": 20,
            "integrationEnd": 64, "events": [],
        }, separators=(",", ":")).encode()
        manifest = dict(self.manifest)
        manifest.update({
            "bytes": len(raw),
            "crc16Ccitt": crc16_ccitt(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
        receipt_bytes = (json.dumps(manifest) + "\n").encode()
        extra = dict(self.extra)
        extra.update({"bytes": str(len(raw)), "crc16Ccitt": str(manifest["crc16Ccitt"]),
                      "sha256": manifest["sha256"]})
        original_get_bytes, original_events = self.viewer._get_bytes, self.viewer._events

        def get_bytes(path, maximum):
            return receipt_bytes if self.receipt_name in path else raw

        self.viewer._get_bytes = get_bytes
        self.viewer._events = lambda: [{"type": RECEIPT_EVENT, "extra": extra}]
        try:
            listing = self.viewer.product_listing()
            verified_manifest, readback = self.viewer._read_verified_raw(self.receipt_name)
            raw_url = self.viewer.url + "/api/products/" + parse.quote(self.receipt_name, safe="") + "/raw"
            receipt_url = self.viewer.url + "/api/products/" + parse.quote(self.receipt_name, safe="") + "/receipt"
            with request.urlopen(raw_url, timeout=2) as response:
                downloaded_raw = response.read()
            with request.urlopen(receipt_url, timeout=2) as response:
                downloaded_receipt = response.read()
        finally:
            self.viewer._get_bytes, self.viewer._events = original_get_bytes, original_events

        self.assertEqual(listing["products"], [])
        self.assertEqual(len(listing["errors"]), 1)
        self.assertIn("two events per exposure second", listing["errors"][0]["error"])
        self.assertEqual(readback, raw)
        self.assertEqual(verified_manifest["readbackSha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(downloaded_raw, raw)
        self.assertEqual(downloaded_receipt, receipt_bytes)

    def test_list_and_download_routes_use_yamcs_bytes(self):
        with request.urlopen(self.viewer.url + "/api/products", timeout=2) as response:
            listing = json.load(response)
        self.assertEqual(len(listing["products"]), 1)
        self.assertEqual(listing["errors"], [])
        raw_url = self.viewer.url + listing["products"][0]["rawUrl"]
        with request.urlopen(raw_url, timeout=2) as response:
            self.assertEqual(response.read(), self.raw)
        receipt_url = self.viewer.url + listing["products"][0]["receiptUrl"]
        with request.urlopen(receipt_url, timeout=2) as response:
            self.assertEqual(response.read(), self.receipt_bytes)


if __name__ == "__main__":
    unittest.main()
