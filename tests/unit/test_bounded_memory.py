"""The bounded decoder child keeps a conservative configurable address-space cap."""
from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from reachscope.ingest import bounded_process, windows_job


@pytest.mark.parametrize(("platform", "default_gib"), [("nt", 4), ("posix", 8)])
def test_platform_memory_limit_defaults_and_override(
    monkeypatch: pytest.MonkeyPatch, platform: str, default_gib: int,
) -> None:
    environment: dict[str, str] = {}
    monkeypatch.setattr(windows_job, "os", SimpleNamespace(name=platform, environ=environment))
    assert windows_job.worker_memory_limit_bytes() == default_gib * 1024**3
    environment["REACHSCOPE_WORKER_MEMORY_MB"] = "6144"
    assert bounded_process.worker_memory_limit_bytes() == 6144 * 1024**2


@pytest.mark.parametrize(("platform", "default_gib"), [("nt", 4), ("posix", 8)])
@pytest.mark.parametrize("value", ["abc", "0", "-1"])
def test_invalid_memory_override_uses_platform_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    platform: str, default_gib: int, value: str,
) -> None:
    monkeypatch.setattr(windows_job, "os", SimpleNamespace(
        name=platform, environ={"REACHSCOPE_WORKER_MEMORY_MB": value},
    ))
    assert windows_job.worker_memory_limit_bytes() == default_gib * 1024**3
    assert f"using {default_gib * 1024} MiB" in caplog.text


def test_windows_job_limit_fields_include_process_memory() -> None:
    limits = windows_job._ExtendedLimits()
    windows_job.apply_job_limits(limits, 4 * 1024**3)
    assert limits.BasicLimitInformation.LimitFlags & 0x100
    assert limits.BasicLimitInformation.LimitFlags & 0x2000
    assert limits.ProcessMemoryLimit == 4 * 1024**3


@pytest.mark.skipif(os.name == "nt", reason="RLIMIT_AS is POSIX-only")
def test_posix_child_receives_default_address_space_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REACHSCOPE_WORKER_MEMORY_MB", raising=False)
    limit = bounded_process.worker_memory_limit_bytes()
    assert limit >= 8 * 1024**3
    process = bounded_process.run_bounded(
        [sys.executable, "-c", "import resource; print(resource.getrlimit(resource.RLIMIT_AS)[0])"],
        timeout=10,
    )
    assert process.returncode == 0
    assert int(process.stdout.strip()) == limit


@pytest.mark.skipif(os.name == "nt", reason="RLIMIT_AS is POSIX-only")
def test_posix_child_receives_configured_address_space_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    import resource

    limit = 4 * 1024**3
    monkeypatch.setenv("REACHSCOPE_WORKER_MEMORY_MB", str(limit // (1024**2)))
    process = subprocess.run(
        [sys.executable, "-c", "import resource; print(resource.getrlimit(resource.RLIMIT_AS)[0])"],
        capture_output=True, text=True, preexec_fn=bounded_process.memory_limit_preexec(), check=True,
    )
    assert int(process.stdout.strip()) == limit
    assert resource.RLIMIT_AS >= 0
