"""Independent semantic/privacy checks at the collector-to-rule boundary."""

from __future__ import annotations

from typing import Any

import pytest

from reachscope_workbench.collectors.host.projection import (
    ProjectionUnsupported,
    project_nginx,
    project_ssh,
)
from reachscope_workbench.modules.host.baseline import assess_baseline


def statuses(text: str) -> dict[str, str]:
    result = assess_baseline({"host_id": "projection-contract-host", "nginx": {"config_dump": text}}, ["nginx"])
    return {row["id"]: row["status"] for row in result["checks"]}


@pytest.mark.parametrize("text", [
    "events {} http { autoindex off; server_tokens off; server { listen 80; server_name private.example; location /private/ {} } }",
    "http { autoindex off; server_tokens off; server { listen 80; server_name private.example; location /private/ { autoindex on; } } }",
    "http { autoindex on; server_tokens on; server { listen 443 ssl; server_name private.example; ssl_protocols TLSv1; } }",
    "http { autoindex off; server_tokens off; server { listen 443 ssl; server_name private.example; ssl_protocols TLSv1.2 TLSv1.3; } }",
    "http { autoindex off; server_tokens off; server { listen 443 default_server; server_name private.example; } server { listen 443 ssl; server_name second.example; ssl_protocols TLSv1.2; } }",
    "http { server { listen 80; server_name private.example; } }",
])
def test_supported_projection_preserves_all_rule_outcomes(text: str) -> None:
    projected = project_nginx(text.encode())
    assert statuses(projected) == statuses(text)
    assert "private.example" not in projected and "/private/" not in projected


@pytest.mark.parametrize("text", [
    "http { server { listen 443 ssl; server_name $private; autoindex off; server_tokens off; ssl_protocols TLSv1.2; } }",
    "http { autoindex off; server_tokens off; server { listen 80; location / { if ($secret) { autoindex on; } } } }",
    "http { autoindex off; server_tokens off; include /missing/private.conf; }",
    'http { autoindex off; server_tokens off; server { listen 80; server_name "unterminated; } }',
])
def test_unsupported_scope_cannot_be_sanitized_into_safe_configuration(text: str) -> None:
    with pytest.raises(ProjectionUnsupported):
        project_nginx(text.encode())


def test_private_directives_and_comments_never_appear_in_projected_material() -> None:
    text = """http { autoindex off; server_tokens off; server {
      listen 80; server_name private.example;
      # canary-secret-comment
      proxy_set_header Authorization "Bearer canary-secret-token";
      ssl_certificate_key /private/canary-secret-key;
      location /private/ { proxy_pass http://canary-secret-backend; }
    } }"""
    projected = project_nginx(text.encode())
    assert "canary-secret" not in projected and "private.example" not in projected
    assert "Authorization" not in projected and "certificate" not in projected


def test_context_aliases_stay_stable_across_reviewed_value_changes() -> None:
    weak = "http { autoindex on; server_tokens on; server { listen 80; server_name private.example; location /private/ {} } }"
    strong = weak.replace("autoindex on", "autoindex off").replace("server_tokens on", "server_tokens off")

    def identity(text: str) -> list[dict[str, Any]]:
        value = {"host_id": "same-host", "nginx": {"config_dump": project_nginx(text.encode())}}
        return [row["comparison_identity"] for row in assess_baseline(value, ["nginx"])["checks"]]

    assert identity(weak) == identity(strong)


def test_ssh_projection_keeps_effective_values_and_excludes_unreviewed_secrets() -> None:
    raw = b"permitrootlogin yes\npasswordauthentication no\npermitemptypasswords no\nmaxauthtries 3\nsetenv TOKEN=canary-secret\n"
    projected = project_ssh(raw)
    assert "permitrootlogin yes" in projected and "canary-secret" not in projected
    assert len(projected.splitlines()) == 4
