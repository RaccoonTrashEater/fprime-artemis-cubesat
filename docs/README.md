# Neutron 2 documentation

Start with the guide for your task. Current N2 software uses Yamcs with a host-native simulated spacecraft; real payload, Pi, SatNOGS/SDR and RF integration remain separate gates.

| Your task | Start here |
| --- | --- |
| Mission ops: first-time local setup | [Local setup](operations/LOCAL_SETUP.md) |
| Mission ops: run a prepared laptop | [Daily quickstart](operations/QUICKSTART.md) |
| Mission ops: a command or display failed | [Operator troubleshooting](operations/TROUBLESHOOTING.md) |
| Develop or test N2 FSW | [Build and test](development/BUILD_AND_TEST.md) |
| Understand the implementation | [System architecture](architecture/SYSTEM_ARCHITECTURE.md), [mission modes](architecture/MISSION_MODES.md) |
| Connect hardware | [Integration status and contracts](integration/README.md) |
| Check what passed | [Software baseline](verification/SOFTWARE_BASELINE.md), [verification index](verification/README.md) |
| Understand priorities/open work | [Development intent](planning/DEVELOPMENT_INTENT.md), [SDD gap plan](planning/SDD_GAP_PLAN.md) |

## Keep the mission context clear

- **Current N2:** `operations/`, `development/`, `architecture/`, `integration/`, `verification/`, and `planning/`. A document may describe planned behavior; check its status before treating it as implemented.
- **Shared Artemis hardware:** [Artemis references](reference/artemis/README.md). Board/firmware revision and measurements determine applicability.
- **C3M comparisons:** [C3M references](reference/c3m/README.md). They inform N2 engineering and do not establish N2 acceptance.
- **Original design inputs:** [SDD references](reference/sdd/README.md), [glossary](reference/GLOSSARY.md), and [ground-interface background](reference/FPRIME_GROUND_INTERFACES_PRIMER.md).
- **Old workflows and investigations:** [Archive](archive/README.md). GDS/RFM23BP demo procedures are retained there for the older baseline; current mission ops starts above.

macOS arm64 local emulation is validated. Running the full stack on Windows requires WSL and remains unvalidated; native Windows browser access to a separately configured shared server is a different operator workflow. The current local launcher binds localhost.

Maintained guides use stable names. Dated acceptance evidence remains dated and preserves the original source/run identity. No hardware or flight-readiness claim follows from a successful local software run.
