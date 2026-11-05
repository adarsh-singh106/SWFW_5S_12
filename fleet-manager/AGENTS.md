# Fleet Manager engineering constraints

Apply the root working instructions; these rules add product-specific constraints.

## Session continuity

Read [the charter](docs/PROJECT-CHARTER.md) and [current checkpoint](docs/LEARNING-STATE.md), then follow the checkpoint's lesson link and approval boundary. Use [the documentation map](docs/README.md) for organization and [the roadmap](docs/ROADMAP.md) for feature direction. Keep learning material under `docs/learn/<topic>/`; separate external references and student notes from AI-drafted explanations as the map specifies. Update the checkpoint after meaningful progress with observed evidence, learning status, unresolved questions, and one exact next action. Do not infer approval from a guide's proposed design.

## Official scope

Project `SWFW_5S_12`: Distributed Linux Fleet Management.

Overarching specification: a web-based system managing multiple remote Linux nodes, including VMs or bare-metal machines.

Four enumerated requirements, paraphrased from the user's supplied assignment description:

1. Node onboarding and management.
2. Collection, storage, and visualization of system metrics using Prometheus and Grafana.
3. Node availability detection and graceful failure handling.
4. Controlled remote command execution.

Prometheus and Grafana are mandatory. Prioritize official requirements (P0), essential security/correctness/reliability/testing (P1), validated differentiation (P2), then optional research (P3). Correctness, system design, observability, and Linux understanding take priority over UI aesthetics. Do not invent official deadlines, rubric, or additional requirements.

## Engineering rules

- Keep HTTP and lifecycle wiring at the application boundary, validation and use cases independent of FastAPI, and SQL inside inventory persistence. Preserve the documented `/api/nodes` contract, bearer-token gate, and SQLite schema unless a separately approved change requires migration.
- Distinguish probe outcomes from node health. Successful collection proves only that observation; authentication failure or an unreachable endpoint does not prove host failure. SSH exit code 255 does not uniquely identify a cause.
- Missing metrics are not zero. Represent stale observations and uncertainty explicitly. Use Prometheus for time-series storage unless another need is demonstrated.
- Verify SSH host identity securely; protect credentials and private keys. Use least privilege and explicitly authorized, structured operations. Do not expose unrestricted remote shell access through the web application.
- Bound execution with explicit timeouts, handle errors safely, and record meaningful audit events without sensitive data.
- Verify success, relevant failure paths, and recovery with reproducible commands/tests. Use independently isolated Linux machines for realistic multi-node failure experiments; WSL2 distributions sharing a kernel do not qualify as independent hosts.
- Justify technology by requirements, simplicity, reproducibility, and learning value. Introduce infrastructure or package boundaries only when a concrete need exists.
- Treat product differentiation as hypotheses. Publication/IP permissions remain unverified; do not copy restricted ZohoLearn material into the repository.
- Preserve original prerequisite material and WSL configuration. Obtain permission before starting a stopped WSL distribution. Inspect experimental scripts for secrets before preserving copies; never substitute lesson examples for uninspected originals.
