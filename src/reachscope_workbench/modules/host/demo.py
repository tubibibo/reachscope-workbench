"""Original synthetic host exports and logs; never observations of a live host."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any


def input_template() -> dict[str, Any]:
    """Safe example format. The caller supplies their own export and timestamp."""
    return {"schema_version": "reachscope-host/1", "host_id": "srv-web-01", "collected_at": "2026-11-02T00:00:00Z",
            "ssh": {"connection_context": "global", "effective_config": "permitrootlogin no\npasswordauthentication no\npermitemptypasswords no\nmaxauthtries 3\n"},
            "nginx": {"config_dump": "http {\n server_tokens off;\n autoindex off;\n server {\n listen 443 ssl;\n server_name example.invalid;\n ssl_protocols TLSv1.2 TLSv1.3;\n }\n}\n"}}


def baseline_bytes(host_id: str = "demo-host-01", *, hardened: bool = False) -> bytes:
    document = input_template()
    document["host_id"] = host_id
    if not hardened:
        document["ssh"]["effective_config"] = "permitrootlogin yes\npasswordauthentication yes\npermitemptypasswords yes\nmaxauthtries 10\n"
        document["nginx"]["config_dump"] = "http {\n server_tokens on;\n autoindex on;\n server {\n listen 443 ssl;\n server_name example.invalid;\n ssl_protocols TLSv1 TLSv1.1 TLSv1.2;\n }\n}\n"
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def access_bytes() -> bytes:
    start = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    lines = [f'192.0.2.10 - - [{(start + timedelta(seconds=i)).strftime("%d/%b/%Y:%H:%M:%S +0000")}] "GET /private?token=SYNTHETIC_ONLY HTTP/1.1" 401 0 "-" "Synthetic fixture"'
             for i in range(12)]
    lines += [f'198.51.100.20 - - [01/Nov/2026:00:00:{30+i:02d} +0000] "GET /health HTTP/1.1" 503 0 "-" "Synthetic fixture"' for i in range(5)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def auth_bytes() -> bytes:
    lines = [f"2026-11-01T00:00:{i:02d}+00:00 synthetic-host sshd[1234]: Failed password for invalid user SYNTHETIC_USER from 192.0.2.20 port 41234 ssh2" for i in range(7)]
    return ("\n".join(lines) + "\n").encode("utf-8")
