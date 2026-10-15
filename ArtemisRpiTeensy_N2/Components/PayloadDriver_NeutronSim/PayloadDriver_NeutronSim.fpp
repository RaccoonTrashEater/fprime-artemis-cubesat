module Components {
    @ Raspberry Pi-hosted neutron payload simulator driver.
    active component PayloadDriver_NeutronSim {

        @ Health ping input
        async input port pingIn: Svc.Ping

        @ Health ping output
        output port pingOut: Svc.Ping

        @ Correlated capture request including a one-shot simulator behavior
        async input port requestIn: Components.PayloadDriverCaptureRequest

        @ Opaque synthetic pass-through command input from PayloadManager.
        async input port passthroughIn: Components.PayloadDriverPassthroughRequest

        @ Correlated operation result output for capture and pass-through.
        output port operationResponseOut: Components.PayloadDriverOperationResult

        @ Capture subprocess availability and reuse status.
        output port availabilityOut: Components.PayloadDriverAvailability

        @ Rate-group tick for nonblocking child-process and delayed-response polling.
        async input port run: Svc.Sched

        @ Last requested capture duration in seconds
        telemetry LastDurationSeconds: U32

        @ Rows captured by the simulator
        telemetry LastRowsCaptured: U32

        @ Total neutron counts in the last capture
        telemetry LastTotalCounts: U32

        @ SAA rows in the last capture
        telemetry LastSaaRows: U32

        @ Last captured product size in bytes
        telemetry LastProductBytes: U32

        @ Last simulator exit status
        telemetry LastExitStatus: U32

        @ Last science product identifier
        telemetry LastProductId: U32

        @ Last product CRC16-CCITT value widened to U32 for telemetry
        telemetry LastProductCrc: U32

        @ Whether the capture subprocess slot is idle and reusable.
        telemetry CaptureSlotAvailable: bool

        @ Simulator capture completed
        event CaptureComplete(durationSeconds: U32, rows: U32, productBytes: U32, productId: U32) severity activity high format "Neutron sim capture duration={}s rows={} bytes={} product={}"

        @ Simulator capture failed
        event CaptureFailed(durationSeconds: U32, status: U32) severity warning high format "Neutron sim capture failed duration={}s status={}"

        @ Capture worker was terminated and reaped after its bounded deadline.
        event CaptureWorkerReaped(generation: U32, exitStatus: U32) severity warning high format "Capture worker generation={} reaped status={}"

        @ Port for requesting the current time
        time get port timeCaller

        @ Enables event handling
        import Fw.Event

        @ Enables telemetry channels handling
        import Fw.Channel
    }
}
