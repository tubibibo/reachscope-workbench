# ReachScope Workbench

**A local, single-user workbench that turns security findings into evidence,
remediation, and a verified close.**

> Status: 0.14.1, maintained by one person. Bug reports welcome; feature requests
> are usually declined. See [CONTRIBUTING.md](CONTRIBUTING.md).

English | [简体中文](README.zh-CN.md)

![Local teaching loop: collect, harden, re-test, close](docs/images/local-teaching.png)

## Why it exists

Most security tools stop at the finding. ReachScope Workbench carries the result
one step further: the same evidence can enter a remediation workspace, be assigned,
be re-tested against a comparable condition, and only then be closed by a human.

Four analysis modules — Android, Web, Cloud, Host — share one job queue, one
evidence structure, one SQLite workspace and one frontend. A check you run today
is still there after a restart, and a re-test is compared against the exact
observation it is meant to replace.

## Quick start

**Windows** — from the repository root:

```powershell
.\start-workbench.ps1
```

**Other platforms:**

```bash
python -m venv .venv
# Activate .venv using your shell.
python -m pip install .
reachscope-workbench doctor --data .workbench
reachscope-workbench serve --port 8765 --data .workbench
```

**Docker** — the application binds loopback only by design, so it needs host
networking rather than port mapping:

```bash
docker build -t reachscope-workbench .
docker run --rm -it --network host \
  -v "$PWD/.workbench:/app/.workbench" reachscope-workbench
```

Then open **http://127.0.0.1:8765**.

Host networking requires Docker Engine on Linux, or Docker Desktop 4.34+ with Linux containers and host networking enabled in Settings > Resources > Network. It is incompatible with Enhanced Container Isolation.

The frontend is prebuilt and ships in the repository — no Node.js required.
No AI key, no scanning API key, no account.

## Try it without any data

| Entry | What you get |
|---|---|
| `#/lab` | A real loopback teaching site. Collect → harden → re-test → manual close, with actual HTTP responses. |
| Android samples (5) | Cross-component, JS bridge, permission leak, key mismatch, missing component. No APK or Java needed. |
| Cloud sample | `examples/cloud/aws-plan.synthetic.json` |

## What it does

| Module | Input | Output |
|---|---|---|
| Android client | APK upload / 5 source samples | Configuration review, components, permissions, deep links, candidate paths, source lookup, comparable re-test |
| Web probing | Up to 20 exact HTTP(S) URLs | Status, title, server, IP, TLS, redirects, headers, timing, body summary |
| Web review & history | Imported scan results, two completed probes | Fingerprint grouping, config checks, cookie/form profile, field-level change between runs |
| Cloud configuration | AWS Terraform Plan / IAM / supported export JSON | Network, permission and storage rules with field-level evidence and implementation guidance |
| Host defense | SSH/Nginx config JSON, Nginx access logs, SSH auth logs | 7 baseline checks, 3 bounded log rules, redacted events, reinforcement guidance, config re-test |
| Shared workbench | Any of the above | Job progress, logs, cancellation, history, evidence query, JSON / HTML / CSV export |

## What it is not

- **Not a vulnerability scanner.** Static leads, imported findings and rule
  suggestions are not confirmed vulnerabilities and are never presented as such.
- **Not a hosted platform.** It binds `127.0.0.1` only, runs for one user, and has
  no accounts, roles or multi-tenant isolation.
- **Not an attack tool.** No crawling, no directory brute forcing, no exploit
  execution, no APK execution. Web probing sends a GET to addresses you list
  explicitly, and private-network targets are disabled unless you opt in.
- **The rule tables are a reading aid.** The bundled investigation rules list
  checkpoints a human can review — what to look at, what would count as a result,
  and what would be a false positive. Nothing in this application carries those
  steps out; they are text you read and act on yourself.
- **Does not read your cloud account.** The cloud module parses offline JSON files.
  A static configuration does not establish deployed reachability or effective IAM.
- **Does not claim measured detection rates.** Nothing here is validated against a
  realistic corpus, and a missing observation is not evidence that an asset is safe.

## Documentation

Full documentation is written in Chinese — start at [docs/](docs/README.md).

The English README is a curated summary, not a translation; where the two differ,
the Chinese documentation is authoritative.

- [Project status](docs/releases/project-status.md) · [Feature matrix](docs/reference/feature-matrix.json)
- [Architecture](docs/architecture/workbench.md) · [API reference](docs/reference/workbench-api.md)
- [Quality gates](docs/development/quality-gates.md) · [Security model](SECURITY.md)
- [Third-party sources](THIRD_PARTY.md)

## Development

```bash
python -m pip install -e ".[dev,ui]"
cd frontend && npm ci && npm run check && npm run build && cd ..
python scripts/check_all.py
```

`scripts/check_all.py` runs the repository gate, ruff, strict mypy, the test suite
with an 85% coverage floor, the OpenAPI drift check, and the frontend type check
and build. CI runs the same set on Ubuntu and Windows across Python 3.11 and 3.13.

## License

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY.md](THIRD_PARTY.md).
