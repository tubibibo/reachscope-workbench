# Reuse and upstream decisions — 2026-11-01

## Platform patterns revisited (0.10)

Official GitHub repositories were opened again for this iteration:

| Reference | License shown | Applied pattern |
|---|---|---|
| [DefectDojo](https://github.com/DefectDojo/django-DefectDojo) | BSD-3-Clause | Keep saved evidence connected to review/remediation and retests |
| [Faraday](https://github.com/infobyte/faraday) | GPL-3.0 | Organize existing results in a workspace; no upstream code is copied |
| [Backstage](https://github.com/backstage/backstage) | Apache-2.0 | Catalogue-first navigation and a focused self-service entry |

Selection is based on fit with the current local workbench, not a claim to reproduce
these platforms. The original React/CSS guide links to our existing three module
flows. No upstream source, UI assets, rule corpus or deployment stack is bundled.

## Asset-first workflow and cloud review (0.7)

The following official sources were inspected for this iteration:

| Reference | Applied decision |
|---|---|
| [DefectDojo asset/test documentation](https://docs.defectdojo.com/asset_modelling/engagements_tests/) and [repository](https://github.com/DefectDojo/django-DefectDojo) | Separate persistent assets from immutable test runs and evidence. The four-step local wizard is our own simpler interaction, not a copied upstream UI. |
| [Prowler](https://github.com/prowler-cloud/prowler) | Organize cloud checks by capabilities/services and show actual selected execution. No scanner, account connector, rule corpus or upstream UI is bundled. |
| [Checkov](https://github.com/bridgecrewio/checkov) | Inspect explicit input formats, check allowlists and resource/source-location evidence. Implement a deliberately small offline AWS rule set rather than implying Checkov's complete coverage. |

Cloud service addresses remain exact HTTP(S) observations through the existing Web
module. Cloud account configuration requires a static file in the implemented
formats; no cloud credentials or live-account connector are accepted. Independent
modules do not import each other to provide the unified user flow. AWS semantics,
input budgets and validation are documented in `docs/modules/cloud/configuration-review.md`.

No source code from the three projects above was copied for this iteration;
attribution describes design references rather than shipped integrations.

## Initial workbench references

The project reuses its existing components and studies mature GitHub projects.
Popularity is a discovery signal, not proof of technical suitability.
The following official repositories and release/issue pages were checked:

| Reference | Decision |
|---|---|
| [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) | Use FastAPI + React/TypeScript/Vite and build the frontend into the application. Avoid copying a cloud/account/Postgres stack into a local single-user tool. |
| [projectdiscovery/httpx](https://github.com/projectdiscovery/httpx) | Adopt explicit probe metadata, bounded per-target results and import compatibility. Do not run a powerful standalone scanner behind an unbounded local web endpoint. |
| [projectdiscovery/nuclei](https://github.com/projectdiscovery/nuclei) | Support JSONL findings as unverified imported evidence. No template execution or copied rule corpus. |

At inspection time, the official pages displayed approximately 10.6k stars for
ProjectDiscovery httpx and 32.5k for Nuclei. Their active release and issue pages
were examined as well. Counts are historical, not pinned product facts. No source
from these projects was copied into the workbench; their capability claims are not
inherited by this project.

Direct local reuse:

- `reachscope` engine from the user's previously delivered 0.4.1 tree: parsing,
  static graph analysis, artifacts, query and protocol. MIT license retained.
- FOFA accounts/cache, old global Web server and template writers are not copied;
  new persistence and module interfaces replace their transport coupling.

Dependencies (FastAPI, Uvicorn, Python HTTPX, PyYAML, Jinja2, React, Vite, TypeScript,
Lucide and development tools) are installed packages with their upstream license
notices. Compiled frontend output is distributed together with its source and
lockfile. `THIRD_PARTY.md` records source and dependency notices. Artwork, fonts
and code from design-award websites are not copied.
