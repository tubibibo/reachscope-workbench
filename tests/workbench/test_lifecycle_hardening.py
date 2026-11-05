"""E 审计修复的行为契约：读端点线程化（F-001）与工作区锁所有权移交（F-002）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reachscope_workbench.api.app import create_app
from reachscope_workbench.core.models import WorkbenchError


def test_evidence_reads_run_in_worker_threads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """F-001：evidence 的 repository 读取必须经 asyncio.to_thread，不得在事件循环里同步执行。"""
    real_to_thread = asyncio.to_thread
    observed: list[Any] = []

    async def spy(fn: Any, *args: Any, **kwargs: Any) -> Any:
        observed.append(fn)
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy)
    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{'f' * 32}/evidence/{'0' * 32}")
    assert response.status_code == 404, "不存在的任务应得到受控 404"
    assert any(getattr(fn, "__name__", "") == "completed" for fn in observed), "completed() 必须经 to_thread 调用"


def test_second_create_app_on_same_workspace_fails_controlled(tmp_path: Path) -> None:
    """F-002：create_app 持锁直到 lifespan 结束或 GC；同目录第二个实例必须受控报 WORKSPACE_BUSY。"""
    first = create_app(tmp_path)
    try:
        with pytest.raises(WorkbenchError) as failure:
            create_app(tmp_path)
        assert failure.value.code == "WORKSPACE_BUSY"
    finally:
        del first
    import gc

    gc.collect()


def test_lock_survives_until_lifespan_exit(tmp_path: Path) -> None:
    """F-002：app 构造后即持有锁（无需进入 lifespan 也拦住第二个实例）；lifespan 退出后放行。"""
    app = create_app(tmp_path)
    with TestClient(app) as client:
        with pytest.raises(WorkbenchError) as failure:
            create_app(tmp_path)
        assert failure.value.code == "WORKSPACE_BUSY"
        assert client.get("/api/health").status_code == 200
    reopened = create_app(tmp_path)
    assert reopened is not None, "lifespan 退出释放锁后，同目录可再次构造"
    del reopened
    import gc

    gc.collect()
