# Fleet Manager

**Know what's wrong before you act.**

Planned workflow: onboarding → monitoring → investigation → controlled action → verification.

No application feature has been implemented yet. First proposed feature: register and list node endpoints through a local web page, with persistent inventory and an honest "Not checked" observation state. Implementation awaits approval.

- [Charter](docs/PROJECT-CHARTER.md): requirements, constraints, and unknowns.
- [Current checkpoint](docs/LEARNING-STATE.md): evidence and next action.
- [Roadmap](docs/ROADMAP.md): small working increments and acceptance criteria.
- [Video plan](docs/VIDEO-PLAN.md): meaningful demonstration checkpoints.
- [Engineering instructions](AGENTS.md): product-specific constraints.

## Working directories

```text
fleet-manager/
  src/       Application source for the first approved feature
  tests/     Reproducible checks for implemented behavior
  docs/      Charter, roadmap, learning checkpoint, and video plan
```

The empty source and test directories contain `.gitkeep` placeholders so Git can
retain them. Replace these placeholders when real files are added. This layout
does not select a framework or introduce separate services. Runtime data belongs
in ignored `.local/` when the application needs it.

## Runtime baseline

On 2026-10-09, Codex observed Windows PowerShell 5.1, `python --version` reporting Python 3.14.6, and `git --version` reporting 2.55.0.windows.3. `wsl --list --verbose` showed Debian and Ubuntu stopped, both WSL2. These commands can reproduce the inventory check without starting either distribution.

Application runtime/dependencies and Linux execution remain unverified. No install or run command is claimed yet. Establish executable setup commands with the first approved feature. Reserve `.local/` for ignored runtime data; keep credentials out of source and large recordings in ignored `recordings/` or outside the repository. Ignore patterns are convenience, not a secret scanner.
