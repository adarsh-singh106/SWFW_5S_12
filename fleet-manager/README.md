# Fleet Manager

**Know what's wrong before you act.**

Planned workflow: onboarding → monitoring → investigation → controlled action → verification.

The production application registers and lists node records and can explicitly verify one registered endpoint's SSH host key and login. It stores inventory and append-only observations in SQLite. A single-operator development token protects the API. Node registration stays `NOT_CHECKED`; SSH outcomes are separate observations. It does not offer a browser page, collect metrics, execute remote commands, or establish whole-host health. The four official requirements are not complete.

- [Charter](docs/PROJECT-CHARTER.md): requirements, constraints, and unknowns.
- [Documentation map](docs/README.md): learning guides, source material, and where decisions/evidence belong.
- [Start learning node inventory](docs/learn/node-inventory/README.md): the first feature's request flow and exercise.
- [Current checkpoint](docs/LEARNING-STATE.md): evidence and next action.
- [Roadmap](docs/ROADMAP.md): small working increments and acceptance criteria.
- [Video plan](docs/VIDEO-PLAN.md): meaningful demonstration checkpoints.
- [Engineering instructions](AGENTS.md): product-specific constraints.

## Working directories

```text
fleet-manager/
  src/fleet_manager/main.py      Application lifecycle and HTTP error mapping
  src/fleet_manager/config.py    Validated process settings
  src/fleet_manager/inventory/  HTTP routes, schemas, rules, and SQLite storage
  src/fleet_manager/connectivity/  SSH observation use case, transport, and storage
  src/fleet_manager/security/   Bearer-token boundary
  tests/              Isolated API and database checks
  docs/      Charter, roadmap, learning checkpoint, and video plan
```

Older `.gitkeep` placeholders remain harmless. Runtime data belongs in ignored
`.local/`. Practice code under `docs/learn/` is separate from this package.

## Reproducible local setup (PowerShell)

Install uv and use its Python 3.12 interpreter. From `fleet-manager/`:

```powershell
uv sync --locked
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
uv run --no-sync python -m mypy src
uv run --no-sync pytest -q
uv run --no-sync python -c "from fleet_manager.main import app; print(app.title)"
```

On this Windows machine, Application Control blocked the prebuilt mypy executable
and extension. The verified local workaround is to set `$env:MYPY_USE_MYPYC='0'`,
run `uv sync --locked --no-binary-package mypy --reinstall-package mypy`, and use
`python -m mypy` as above. A clean setup on the same policy should use the same
environment variable and `--no-binary-package mypy` on its first sync. This builds
the locked mypy release from source; it does not change the lockfile.

The API contract is generated at `/openapi.json`. The inventory API requires
`Authorization: Bearer <token>`. Configure a 32-128 character URL-safe token
outside the repository before starting the server. For a disposable local token,
the following PowerShell assignment captures a cryptographically random value
without printing it:

```powershell
$env:FLEET_MANAGER_API_TOKEN = uv run --no-sync python -c "import secrets; print(secrets.token_urlsafe(32))"
uv run --no-sync python -m uvicorn fleet_manager.main:app --host 127.0.0.1 --port 8000
```

In another shell, supply the same token through a secure local channel and send
it in the header. Never place it in a tracked file, URL, command-line argument,
or example value:

```powershell
$headers = @{ Authorization = "Bearer $env:FLEET_MANAGER_API_TOKEN" }
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/nodes -Headers $headers -ContentType application/json -Body '{"name":"lab-01","address":"192.0.2.10","ssh_port":22}'
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/api/nodes -Headers $headers
```

`POST /api/nodes` returns 201 with `id`, normalized `name` and `address`,
`ssh_port`, and `observation_state: NOT_CHECKED`. `GET /api/nodes` returns 200
with a `nodes` array in insertion order. Missing, malformed, or incorrect
credentials return 401 with `WWW-Authenticate: Bearer`. Invalid input returns
422, a duplicate
normalized address and port returns 409, and storage failure returns 503. Errors
use `{"error":{"code":"...","message":"..."}}`. The default database is
`.local/inventory.db`; tests use temporary databases and do not touch that file.

## Explicit SSH verification

Before a real check, configure a dedicated non-root SSH account with the
least permissions your server can grant. Set `FLEET_MANAGER_SSH_USERNAME`,
`FLEET_MANAGER_SSH_KNOWN_HOSTS`, and `FLEET_MANAGER_SSH_PRIVATE_KEY` in the
server process environment. The last two are paths to an explicitly reviewed
known_hosts file and a private key outside tracked source. Restrict file access
to the operator. Verify each host-key fingerprint through a trusted independent
channel before adding it to known_hosts; first-contact scans alone are not
identity verification. For a nonstandard port, use `[hostname]:port` in
known_hosts. Keep the HTTP API on loopback.

With the bearer header from above, `POST /api/nodes/{id}/connectivity-check`
attempts one SSH handshake and returns an observation.
`GET /api/nodes/{id}/connectivity` returns the latest observation or `null` if no
check exists. Outcomes include `CONNECTED`, `HOST_KEY_UNKNOWN`,
`HOST_KEY_MISMATCH`, `AUTH_FAILED`, `CONNECTION_REFUSED`, `TIMEOUT`,
`DNS_ERROR`, and `UNKNOWN_ERROR`. Missing SSH configuration returns 503;
an unknown node ID returns 404. `CONNECTED` means host-key verification and
authentication succeeded for that attempt; it does not mean the host is healthy.
Each SSH check runs in a short-lived child process. The default maximum is four
concurrent checks per application process (`FLEET_MANAGER_SSH_MAX_CONCURRENT`,
range 1-16). The total elapsed-time budget defaults to 12 seconds
(`FLEET_MANAGER_SSH_TOTAL_TIMEOUT_SECONDS`, range 1-60). A deadline expires
across DNS, address attempts, and SSH authentication; the child is killed and
reaped before a `TIMEOUT` observation is saved. A full pool returns 429
`connectivity_busy`; a second simultaneous check of the same node returns 409
`connectivity_in_progress`. Neither rejection creates an observation. During
shutdown, active children are killed and reaped; interrupted requests receive
503 without a fabricated SSH result. Configured limits are validated at startup.
Run one application worker: admission and same-node exclusion are process-local.
See [ADR 0003](docs/decisions/0003-verified-ssh-observations.md).

Startup fails if the token is absent, too short, or malformed. Format validation
cannot establish actual entropy, so generate it randomly. The token is shared by one
development operator: it does not identify people or implement RBAC. It is sent
on each request, so keep the server on loopback and use TLS plus real operator
identity before any remote deployment. See [ADR 0002](docs/decisions/0002-local-inventory-authentication.md)
for the threat model, rotation limit, and future authorization path.

The inventory slice was checked on Windows with Python 3.12. The bounded SSH
slice passed locked dependency sync, lint, format, typing, and 68 tests on Debian 12 under WSL2,
including a disposable loopback SSH server and API persistence test. An earlier
inventory-only two-process loopback HTTP smoke check also passed there. Native Linux
deployment and managed-node behavior remain unverified; WSL2 is not an independent
node failure domain. Keep credentials out of source and large recordings in ignored
`recordings/` or outside the repository. Ignore patterns are convenience, not a secret
scanner.
