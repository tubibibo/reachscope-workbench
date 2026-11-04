# Host collector: real Linux acceptance

Status on 2026-11-02: **not executed on Linux**. Unit tests, injected command
fixtures and a successful Windows build are not evidence of actual Linux command
execution. This page records that boundary separately from release gates.

## Local prerequisites observed

Read-only checks on the current Windows workstation found:

- Docker CLI and a `desktop-linux` context using the local Docker Desktop named
  pipe. A bounded `docker --context desktop-linux version` returned exit 1;
  the Linux daemon was unavailable.
- `wsl --list --quiet` returned exit 0 and no installed distributions.
- VirtualBox's read-only running-VM listing was empty. QEMU was not on PATH.
- A VMware VM process existed, but its guest OS and configuration were not
  identifiable from accessible process metadata. It was not contacted or changed.

No Docker GUI, VM, service or distribution was started; no image, root filesystem,
virtualization component or package was downloaded/installed. No real server or
commercial model was contacted. Linux execution remains an explicit acceptance
gap, not a passing result.

## Reproducible harness

`scripts/smoke/check_host_linux.py` is standard-library-only and defaults to a read-only
JSON prerequisite report. `--required` makes unavailable acceptance return exit 2
instead of 0. An ordinary skipped prerequisite report is always
`status: not_executed`, `actual_linux_acceptance: false`.

Actual execution requires all of:

- Linux; real `/usr/sbin/sshd`, `/usr/sbin/nginx`, `/usr/bin/ssh-keygen`.
- An explicitly disposable container with `/.dockerenv` or `/run/.containerenv`,
  `REACHSCOPE_DISPOSABLE_LINUX=1` and `--disposable-container`.
- Sufficient container-local permission for fixture config files; no running
  SSH/NGINX service; no bind mounts for `/etc`, their component directories or
  configuration files. Never point this harness at an operator's server.
- A reviewed collector zipapp and a Python environment containing the matching
  installed workbench package. The harness does not build/install/download them.
- A new/empty `--out` directory containing no existing workspace or user records.

Inside that container only, the harness temporarily replaces its own image's
SSH/NGINX config with bounded fixtures, generates a temporary fixture host key,
executes real `sshd -T` and `nginx -T` without starting either service, and runs
the collector's plan/confirmation protocol for weak and hardened fixtures.
Fixture configurations are restored in `finally`; generated keys stay in a
temporary directory that is removed. The collector itself never writes service
configuration. Collected metadata remains unverified operator-supplied provenance,
not proof of deployed state or identity.

These are actual configuration-test programs, not a claim of zero filesystem
side effects: NGINX tests syntax and opens referenced files, and OpenSSH also
checks key sanity. A system's existing modules/configuration can affect its test
binary. This harness therefore accepts only its controlled disposable fixtures;
it does not introduce a flag for arbitrary config/executable paths.

The result then uses a newly started, loopback-only installed workbench API:
actual file upload → preview without creating a job → selected SSH/NGINX rules →
explicit revised-input association → comparable retest → human note and closure.
It verifies saved baseline immutability, private-value redaction and zero AI
reports. Local proxy inheritance and provider environment credentials are removed.
The API's stdout/stderr and real binary dumps are never artifact fields.

Example invocation **inside an already prepared disposable Linux container**:

```sh
export REACHSCOPE_DISPOSABLE_LINUX=1
python3 /acceptance/verify_host_linux.py \
  --python /venv/bin/python --bundle /acceptance/reachscope-host-collector.pyz \
  --run --disposable-container --required --out /artifacts/host-linux
```

The proof file is `host-linux-acceptance.json`, accompanied by minimal exported
snapshots and the fixture-only local workspace. It records bundle/input hashes,
actual component capture states and the two case outcomes. A failure is not
rewritten as `pass`; raw exception/command/API text is not emitted.

## Linux CI recommendation

Use a reviewed, pinned-digest image prepared with the required official packages,
an installed candidate wheel and collector. Run the disposable container with a
bounded timeout, memory/process/CPU limits, dropped capabilities,
`no-new-privileges`, no privileged mode and `--network none` (loopback still works).
Mount only the reviewed harness/bundle as read-only inputs and an empty artifact
directory. Do not mount Docker sockets, user homes, credentials or host `/etc`.
Do not automatically pull an unreviewed image to make this gate green.

Remote CI has not been run in this work session. Insert actual Linux platform,
package/binary versions, exact command, exit code and proof-file digest here only
after the real job completes. Source/unit/browser gates remain separate evidence.

## Harness verification on Windows

The focused safety tests passed locally: **16 passed, 1 Linux-only test skipped**
(`--no-cov`, 1.72 seconds).
Ruff passed for the harness and its test file. The tests exercise read-only
prerequisite/explicit execution boundaries, existing-workspace refusal, private
error redaction, fixture byte/mode restoration, output/time budgets, a dead leader
with an owned pipe group, and HTTP redirect/response limits. The skipped test
requires real Linux process-group cleanup; it was not reported as passed.
Fixture helpers are injected only in these tests; they
are not evidence of Linux service-binary execution or a successful real export.

Actual local command: `python scripts/smoke/check_host_linux.py --required`. Its
report was `status: not_executed`, `actual_linux_acceptance: false`; the required
gate returns exit 2. It created no artifact directory, service or configuration.

The extended `scripts/smoke/check_installed.py` also passed from outside the checkout
using the existing source environment with `python -I` and a fresh temporary data
directory. It downloaded the real collector and source archives, verified matching
bytes/SHA, ran the isolated zipapp's plan-only entry point, verified no snapshot
or job was created, then uploaded a controlled v2 failed-capture file and kept all
selected SSH rules unknown. Existing four-module, cloud/host case closure and
local teaching flows remained successful. This is source-environment integration
evidence, not final-wheel installation or actual Linux binary acceptance.

## Official command semantics

- [NGINX command-line parameters](https://nginx.org/en/docs/switches.html): `-T`
  performs the configuration test and also dumps the configuration to stdout.
- [OpenSSH sshd manual](https://man.openbsd.org/sshd.8): `-T` validates effective
  configuration and exits, includes key tests, and can apply `Match` rules only
  when a connection specification is explicitly supplied. The current collector
  exports the explicitly labelled global context; it does not guess a user/IP.
