# CDR TCP adapter plan

Current implementation status and acceptance boundaries live in the [canonical CDR TCP/Yamcs plan](CDR_TCP_YAMCS_IMPLEMENTATION_PLAN.md): final local native acceptance and legacy regressions PASS. See the [runbook](../operations/CDR_TCP.md) and [portable evidence pack](../verification/evidence/n2-cdr-tcp-2026-10-20/README.md), including its [structured acceptance record](../verification/evidence/n2-cdr-tcp-2026-10-20/acceptance.json). CDR uses stock ComCcsds/TCP and FileDownlink; physical UART mux channel 2 remains dedicated to Teensy/PDU RPC.
