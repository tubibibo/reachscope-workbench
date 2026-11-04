# Public defence references and boundaries

Reviewed: 2026-11-01. The control catalogue is original project guidance with
attribution links. It contains no copied vendor detection database, signature,
executable rule or exploit payload. Only the official public sources below were
used for this catalogue; no installed endpoint-product files, private management
interfaces or computer-specific protection rules were read or exported.

The source data lives in `core/defense_catalog.py`. `catalog()` returns an
independent JSON-compatible list with stable IDs. The server owns the review,
action, verification and limitation text. An advisory model may select/rank
allowlisted control IDs and existing evidence IDs; arbitrary model prose is not
substituted for catalogue instructions.

## Applicability and observable signals

| Applicability | Controls | What the application can substantiate |
|---|---|---|
| `web_config` | `web.tls`, `web.csp`, `web.frame`, `web.cookies`, `web.cors`, `web.mixed_content`, `web.forms`, `web.mime`, `web.referrer` | Only mapped checks in saved bounded Web responses, including their incomplete/failed/unknown states. |
| `manual_review` | `app.input_validation`, `app.access_control`, `ops.logging`, `ops.patching` | A human review topic. There is no automatic detection signal for these controls. |
| `endpoint_hygiene` | `endpoint.hygiene` | A separate manual endpoint-governance topic, not a website observation or installed-product assessment. |

`signals` contains existing check IDs only. An empty list is intentional; it must
not be filled by a model with invented evidence. A mapping is context for review,
not proof of exploitability, a missing control, compliance or overall security.
Human verification steps are not commands the tool executes. The red-review text
is limited to authorized high-level questions, with no exploitation instructions.

## OWASP public guidance

| Official source | Catalogue use |
|---|---|
| [Transport Layer Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html) | HTTPS lifecycle, certificate maintenance and avoiding insecure page-resource transport. |
| [HTTP Headers Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html) | HSTS, framing, MIME handling, referrer and CORS configuration review. |
| [Content Security Policy Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html) | Resource-source review, staged deployment and the distinction between policy text and application safety. |
| [Clickjacking Defense Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Clickjacking_Defense_Cheat_Sheet.html) | Intended page-embedding boundaries and framing policy. |
| [Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) | Cookie scope/attributes and a separate human review of the session lifecycle. |
| [CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html) | Authentication context, trusted destinations and server-side controls beyond cookie attributes. |
| [Input Validation Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html) | Bounded server-side validation, trust boundaries and the need for distinct data-access/output defences. |
| [Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) | Default denial, per-request object authorization and permission-matrix review. |
| [Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) | Structured security events, sensitive-data minimization and event-review ownership. |
| [Vulnerable Dependency Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Vulnerable_Dependency_Management_Cheat_Sheet.html) | Maintaining dependency context, reviewing fixes and documenting exceptions and deployment verification. |

These are conceptual summaries, not a claim that the workbench implements every
recommendation in those documents. In particular it does not perform authenticated
authorization testing, a complete dependency/CVE assessment or live log ingestion.

## Kaspersky public component overviews

The following are versioned public KES help pages. They are used as background
for separating endpoint defence from site configuration and for human-reviewed
operations; they are not current-version installation instructions.

| Official source | Principle used | Explicit non-equivalence |
|---|---|---|
| [About Web Threat Protection — KES 11](https://support.kaspersky.com/KESWin/11/en-US/128016.htm) | Endpoint web-traffic protection is a distinct control layer. | Saved website headers do not prove endpoint traffic scanning, malicious-URL detection or product policy status. |
| [Exploit Prevention — KES 11.5](https://support.kaspersky.com/keswin/11.5.0/en-US/151109.htm) | Endpoint protection can complement maintained applications and patching. | The workbench does not monitor execution or memory, stop exploit attempts, or inherit this component's capabilities. |
| [Adaptive Anomaly Control — KES 11.4](https://support.kaspersky.com/KESWin/11.4.0/en-US/173855.htm) | Observation, human review and explicit handling of operational exceptions matter. | There is no learning of endpoint behaviour, vendor-rule replication, process blocking or automatic policy change here. |

No Kaspersky code, rule identifiers, signatures or proprietary settings are
bundled. Product capabilities, licensing and version-specific behaviour remain
the vendor's own, and no endorsement or integration is implied. The catalogue
does not implement antivirus, EDR or WAF functionality.

## Engineering checks and current experiment

Catalogue tests check exact schema/IDs, uniqueness, bounded JSON-compatible text,
defensive copies, official-reference allowlists, existing signal mappings and
the absence of HTTP/API/module/I/O dependencies in the core source. Tests cannot
prove that a site or endpoint follows the referenced practices.

See [ADR 0004](../architecture/adr/0004-ai-evidence-advisory.md) for the proposed advisory trust
boundary and [project status](../releases/project-status.md) for the validated 0.8 baseline
and ongoing 0.9 experiment. API keys and real-provider integrations are not yet
connected or validated; final integrated acceptance counts remain pending.
