# N2 local demo troubleshooting

Use this page for the local synthetic Yamcs demo. For setup details, see [Local setup](LOCAL_SETUP.md); for the daily flow, see [Quickstart](QUICKSTART.md).

| Symptom | Check |
| --- | --- |
| Yamcs or the science viewer will not open | Confirm `run_pulses.sh` is still running. Use `http://127.0.0.1:8090` for Yamcs and `http://127.0.0.1:8063` for the viewer. If startup reports a port conflict, stop the previous N2 stack with Ctrl+C in its terminal or `./tools/yamcs/stop.sh`; do not terminate an unrelated process. |
| Yamcs shows no current telemetry or commands do not complete | Confirm the selected instance is `fprime-project` and processor is `realtime`, and check the foreground launcher for startup or runtime errors. Do not issue overlapping commands while one collection is active. |
| Command history reports FAILURE or `CommandComplete_Status=NOK` | Treat the operation as failed. Read the `PayloadTerminal`, `StorageCommitted`, `SenderComplete`, and `GroundReceipt` status/message fields to find the failed stage. A released command or sender completion alone is not success. Use a fresh nonzero token for a later attempt, after the current operation has reached a terminal result. |
| Viewer says there are no verified products | The viewer only displays products after a verified ground receipt for the current local run. Check that `GroundReceipt` and `CommandComplete` are `OK`; wait for an active operation to finish before trying another command. |
| Storage rejects a new capture as full | The durable catalog holds at most 16 products and survives an F′ process restart. Do not delete its data folder as routine troubleshooting. Ask the software maintainer to review storage history and choose an authorized retention action. |

The launcher checks Yamcs and viewer ports `8090` and `8063` plus local transport ports before starting. A second stack cannot use the same ports. Stop the N2 stack cleanly and wait for it to exit before restarting. Daily operation does not require rebuilding or clearing storage.

This emulation uses synthetic data and software links only. A successful local run does not establish payload, SatNOGS, Pi, or RF hardware operation. See [Windows/WSL status](../development/WINDOWS_WSL.md) for platform limitations.
