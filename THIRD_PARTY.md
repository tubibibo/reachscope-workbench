# Sources, dependencies and design references

## Workbench 0.13 defensive configuration and log semantics

The host input parser, limited baseline rules, fixed-window log indicators,
original synthetic examples and manual guide text are original implementation.
No external SIEM, agent, detection rule corpus or third-party runtime package is
added. Official documentation informs the supported semantics and limitations:

- OpenSSH server configuration and effective-export behavior:
  https://man.openbsd.org/sshd_config and https://man.openbsd.org/sshd
- Nginx logging/combined fields: https://nginx.org/en/docs/http/ngx_http_log_module.html
- Nginx HTTP configuration contexts, directory listing and TLS declarations:
  https://nginx.org/en/docs/http/ngx_http_autoindex_module.html and
  https://nginx.org/en/docs/http/ngx_http_ssl_module.html
- Sigma's portable-rule approach informed the decision to make log sources,
  coverage and fixed detection parameters explicit; no Sigma rules are copied
  or executed: https://sigmahq.io/docs/guide/getting-started.html

Wazuh, DefectDojo and Prowler were studied as product references for baseline
assessment, evidence lifecycle and remediation. Their code and full services
are not embedded or silently installed. Future result connectors remain planned.


## Workbench 0.12 Android and cloud guidance

Reviewed on 2026-11-02. MobSF and Androguard were inspected as architectural
references for separated configuration, component and code evidence views:
https://github.com/MobSF/Mobile-Security-Framework-MobSF and
https://github.com/androguard/androguard. No source/rule corpus or assets from
either project were copied, installed or executed in this iteration. In
particular, MobSF's GPL-3.0 code is not incorporated into this MIT repository.

Android rule prose and implementation are original, informed by public Android
manifest, Network Security Config, backup and App Links documentation. Cloud
manual guides are original summaries linked to the applicable public AWS
security-group, IAM and S3 documentation. Their references are included per
saved control. Neither guidance catalogue is a copied vendor detection corpus.


## Workbench 0.11 developer tooling

OpenAPI TypeScript (MIT, openapi-typescript 7.13.0) is a lockfile-pinned build/dev
dependency used to generate request declarations; its implementation is not in the
runtime bundle. See https://openapi-ts.dev/introduction and frontend/package-lock.json.
Local teaching HTML and reviewed guide prose are original. Nginx/OWASP documentation
informs directive syntax and applicability; no upstream server, platform code or
proprietary rule corpus is copied. The project does not deploy these snippets.


## Workbench 0.7.0 design references

The asset/test separation was informed by DefectDojo's asset/engagement/test
documentation; Prowler informed check/service categorization, and Checkov informed
explicit rule selection and resource/source evidence. Their official repositories
and documentation were inspected on 2026-11-01. No source, rule corpus or visual
assets from those projects are bundled or executed. The new cloud checks are a
limited local implementation based on documented AWS configuration semantics,
not a claim to implement the coverage of these upstream tools.
See `docs/research/open-source-references.md` and `docs/modules/cloud/configuration-review.md`.

## Workbench 0.5.0

The `reachscope` engine is retained from the user's ReachScope 0.4.1 project.
`reachscope_workbench/modules/web/legacy` copies selected MIT-licensed src-recon
files and YAML rules, with its original LICENSE and PROVENANCE.md. The original
local projects remain independent and unchanged. See `docs/research/open-source-references.md`
for the integration decisions and current upstream references.

Runtime dependencies now include FastAPI (MIT), Uvicorn (BSD-3-Clause), HTTPX
(BSD-3-Clause), PyYAML (MIT) and python-multipart (Apache-2.0), besides Jinja2.
The frontend uses React/React DOM (MIT), Lucide icons (ISC), and is built with
Vite (MIT) and TypeScript (Apache-2.0). Their package distributions retain their
notices. Because the compiled frontend embeds dependency implementations,
full applicable frontend copyright/permission notices are also reproduced below
and included in the Python wheel through this file. The npm lockfile records
exact versions. No ProjectDiscovery httpx or
Nuclei executable, source or vulnerability-template corpus is bundled. Their
JSONL output formats are accepted as imported data.

The historical notes below describe the earlier engine and walkthrough, not the
full set of workbench dependencies.

ReachScope 0.4 builds on the user's existing ReachScope 0.3 source and its
synthetic regression fixtures. Those files remain part of this project. The
new source-only walkthroughs are derived from these fixtures, not downloaded APKs.

No source code, rules or assets from the following external projects have been
copied into this release. They were inspected as design references on 2026-11-01:

| Project | What informed this project | License shown upstream |
|---|---|---|
| [Androguard](https://github.com/androguard/androguard) | Separation of APK/code inspection and higher-level consumers | Apache-2.0 |
| [Ruff](https://github.com/astral-sh/ruff/blob/main/docs/configuration.md) | Explicit CLI operations and machine-readable output | MIT |
| [Semgrep](https://github.com/semgrep/semgrep) | Separating analysis results, integration and documented limitations | LGPL-2.1; rules have separate terms |

These references are not dependencies and their capabilities are not claimed
by ReachScope. If source is copied in a future change, retain the applicable
copyright, license, revision and source URL with that change.

Runtime Python dependency: Jinja2 (BSD-3-Clause), whose distributions include
their own license and dependency notices. APK decoding uses an externally
installed [Apktool](https://github.com/iBotPeaches/Apktool) (Apache-2.0) and Java;
neither binary is bundled. Optional APKiD and development tools retain their
respective licenses. The earlier 0.4 wheel contained the engine, templates
and synthetic sample code; the 0.5 workbench wheel additionally includes the
module adapters, isolated copied rules and compiled frontend.

The complete original `src-recon` application, MobSF installation, third-party
reference repository, APK corpus and scan archives are not included. Only the
explicitly attributed `src-recon` files described above are copied.

The 0.4.1 walkthrough's visual references use these official CSS Design Awards URLs:

- Typography Principles / Obys: https://www.cssdesignawards.com/sites/typography-principles/38301
- The Creative Website Manual: https://www.cssdesignawards.com/sites/the-creative-website-manual/48438/
- Hot Buro: https://www.cssdesignawards.com/sites/hot-buro/42712

These are visual references, not copied implementations. The exact colors, SVG
drawings, layout, controller and motion in ReachScope are original to this
project. No award, endorsement or affiliation is claimed. No external fonts,
artwork, scripts or stylesheets are downloaded by the generated walkthrough.
No code, fonts or artwork from those sites is copied or bundled.

## Compiled frontend: copyright and permission notices

The production JavaScript embeds React, React DOM, Scheduler, selected Lucide
icons and the Vite module-preload polyfill. These notices accompany both source
and binary releases. Build-only tools are installed from their own package
distributions; their implementations are not copied into this workbench bundle.

### React 19.2.0, React DOM 19.2.0, Scheduler 0.27.0

Source: https://github.com/facebook/react. The following identical notice is
copied from each installed package's `LICENSE`.

```text
MIT License

Copyright (c) Meta Platforms, Inc. and affiliates.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Lucide React 0.468.0

Source: https://github.com/lucide-icons/lucide/tree/0.468.0. Copied from the
installed `lucide-react/LICENSE`; its Feather attribution is retained.

```text
ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT). All other copyright (c) for Lucide are held by Lucide Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

### Feather portions referenced by Lucide

The Lucide notice above attributes portions to Feather under MIT. The full MIT
notice from https://github.com/feathericons/feather/blob/v4.29.2/LICENSE is
reproduced as well; the Lucide package's original copyright dates remain above.

```text
The MIT License (MIT)

Copyright (c) 2013-2023 Cole Bemis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Vite 7.3.7 module-preload polyfill

Source: https://github.com/vitejs/vite. The core notice below is copied from
the installed `vite/LICENSE.md`. Vite's build-time bundled dependencies are
not incorporated into this application's frontend bundle.

```text
MIT License

Copyright (c) 2019-present, VoidZero Inc. and Vite contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
