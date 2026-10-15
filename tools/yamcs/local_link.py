"""Software UART-mux/CCSDS adapter; no RFM23BP packetization or size policy."""
from local_emulation_loop import EmulationLoop, crc16_ccitt
import json
import signal
import time
from urllib import request, error
from science_ingest import GroundScienceIngest
from science_viewer import LocalScienceViewer


class LocalLink(EmulationLoop):
    def __init__(self, app_cmd, yamcs_cmd, run_id="local", science_faults=frozenset(),
                 viewer_port=8063):
        # Reuse only PTY/process lifecycle. Override both data paths below.
        super().__init__(app_cmd, yamcs_cmd, 20, "direct")
        self.downlink = bytearray()
        self.run_id = run_id
        self.science_faults = frozenset(science_faults)
        self.viewer_port = viewer_port
        self.viewer = None
        self._shutdown_complete = False
        self.science_ingest = GroundScienceIngest(
            self.run_id,
            self._queue_retry_frame,
            self.science_faults,
            on_result=self._science_receipt_verified,
        )

    def _queue_retry_frame(self, frame):
        if self.app_master_fd is not None:
            self._queue_write(self.app_master_fd, frame)

    def _science_receipt_verified(self, receipt):
        print(
            f"[science-ingest] ground receipt verified product={receipt['productId']} "
            f"object={receipt['objectName']} sha256={receipt['sha256']}",
            flush=True,
        )

    def setup(self):
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        self.app_master_fd, self.app_slave_fd, self.app_uart_device = self._spawn_pty()
        self.gds_master_fd, self.gds_slave_fd, self.gds_uart_device = self._spawn_pty()
        def expand(command):
            return [item.format(app_uart=self.app_uart_device, gds_uart=self.gds_uart_device) for item in command]
        # Ground first so boot telemetry is received instead of replaced by
        # stale values from the previous run in the persistent Yamcs archive.
        self._launch_child(expand(self.gds_cmd), "Yamcs")
        deadline = time.monotonic() + 90
        while True:
            self._poll_children()
            if self.stop_requested:
                raise RuntimeError("Local stack stopped during Yamcs startup")
            try:
                with request.urlopen("http://127.0.0.1:8090/api/instances", timeout=2) as response:
                    instances = json.load(response)
                if any(i["name"] == "fprime-project" and i["state"] == "RUNNING"
                       for i in instances.get("instances", [])):
                    break
            except (error.URLError, TimeoutError, OSError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Local Yamcs did not reach RUNNING before F′ startup")
            time.sleep(0.25)
        self.viewer = LocalScienceViewer(self.run_id, port=self.viewer_port)
        self.viewer.start()
        print(f"[science-viewer] local UI: {self.viewer.url}", flush=True)
        self._launch_child(expand(self.app_cmd), "native F′")

    def _process_app_to_gds(self, data, now):
        self.stats.app_uart_bytes_in += len(data)
        self.downlink.extend(data)
        while len(self.downlink) >= 5:
            start = self.downlink.find(b"\xd4\xc3")
            if start < 0:
                self.downlink[:] = self.downlink[-1:]
                return
            if start:
                del self.downlink[:start]
            if len(self.downlink) < 5:
                return
            size = int.from_bytes(self.downlink[3:5], "little")
            total = size + 7
            if len(self.downlink) < total:
                return
            channel = self.downlink[2]
            payload = bytes(self.downlink[5:5 + size])
            checksum = int.from_bytes(self.downlink[5 + size:total], "little")
            del self.downlink[:total]
            if crc16_ccitt(payload) != checksum:
                self.app_uart_parser.crc_drops += 1
                continue
            self.stats.app_frames_in += 1
            if channel == 0:
                self.stats.gds_bytes_out += len(payload)
                self._queue_write(self.gds_master_fd, payload)
            elif channel == 1:
                self.stats.payload_bytes_observed += len(payload)
                # The UART envelope has already passed its CRC check. Each
                # channel-1 payload is one complete N2 packet, so do not feed a
                # byte-stream serial parser here.
                # Explicit software fault for proving that sender DONE cannot
                # complete a command without independent ground receipt.
                if "withhold-receipt" not in self.science_faults:
                    self.science_ingest.receive(payload)
            else:
                self.stats.local_frames_observed += 1

    def _process_gds_to_app(self, data, now):
        self.stats.gds_uart_bytes_in += len(data)
        # Preserve bytes unchanged. F′'s FrameAccumulator/TcDeframer owns
        # stream synchronization and TC framing; this adds only the existing
        # deployment's UART-channel envelope.
        frame = (b"\xd4\xc3\x00" + len(data).to_bytes(2, "little") + data
                 + crc16_ccitt(data).to_bytes(2, "little"))
        self.stats.gds_messages_in += 1
        self.stats.app_bytes_out += len(frame)
        self._queue_write(self.app_master_fd, frame)

    def run(self) -> int:
        try:
            self.setup()
            print("[emulation] loop running. Ctrl-C to stop.")
            while not self.stop_requested:
                now = time.monotonic()
                self._poll_children()

                events = self.selector.select(timeout=0.01)
                for key, _ in events:
                    fd = key.fd
                    data = self._read_fd(fd)
                    if not data:
                        continue
                    if fd == self.app_master_fd:
                        self._process_app_to_gds(data, now)
                    elif fd == self.gds_master_fd:
                        self._process_gds_to_app(data, now)

                # Serial retry writes are placed on the existing PTY's pending
                # queue. Network publication remains on the bounded worker.
                self.science_ingest.tick()
                if self.link_mode != "direct":
                    uplink_msg = self.gds_burst_aggregator.poll(now)
                    if uplink_msg is not None:
                        self._process_gds_message_to_app(uplink_msg, now)

                    self.app_uart_parser.poll_timeout(now)
                    self.ground_reassembler.poll_timeout(now)
                    self.sat_reassembler.poll_timeout(now)
                self._flush_pending()
        finally:
            self.shutdown()
        return self.exit_code

    def shutdown(self):
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        if self.viewer is not None:
            try:
                self.viewer.close()
            except Exception as exc:
                print(f"[science-viewer] shutdown error: {exc}", flush=True)
        self.science_ingest.close()
        super().shutdown()
