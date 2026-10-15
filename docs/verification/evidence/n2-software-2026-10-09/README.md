# N2 software acceptance evidence — October 9, 2026

Selected original artifacts copied byte-for-byte from the ignored `yamcs/run/` tree for team review. [Snapshot hashes](snapshot-sha256.json) identify every copied file. Original local runs are preserved.

Start with the [acceptance summary](acceptance-completion-storage-20261009-4be9e7/acceptance-summary.json), [source fingerprint](acceptance-completion-storage-20261009-4be9e7/implementation-source-sha256.json), and [human-readable acceptance record](../../COMPLETION_STORAGE.md#october-9-acceptance-record). The six completion/storage scenarios and A/C/B/pulse regressions passed through Yamcs. Earlier C/B records and selected native test/build logs are also included where linked by the development plans.

The original JSON retains historical absolute paths, build hashes, source HEAD plus dirty state, and run IDs. Resolve an original `.../yamcs/run/<run>/<file>` to `<run>/<file>` below this directory when a copy is present. This is a selected snapshot, not a full runtime archive; nested diagnostic paths may refer to files retained only in the original local runs. Do not execute archived paths as commands. The current baseline commit packages the previously uncommitted implementation; it does not rewrite the historical source identity.

Scope: host-native FSW, synthetic raw science, Yamcs commands and independent object readback, process restart. No target deployment, real payload, SatNOGS/SDR, RF, power-loss qualification, or flight acceptance is established here.
