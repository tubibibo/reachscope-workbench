# ReachScope Workbench engineering contract

Layout and naming: docs/development/repository-layout.md; rules: config/repository-layout.json.
Run python scripts/quality/check_repository.py after moving files or changing documentation links.
Local outputs belong in artifacts/ and caches in .cache/; private workspaces are not disposable.

Core domain models and ports do not import HTTP, UI, concrete modules or external integrations.
Analysis modules remain independent and honor the checks selected by the user.
Adapters handle I/O; routes and React components do not own business rules or lifecycle state.

Do not execute target APKs or silently broaden explicitly authorized network scope.
Credentials stay out of source, browser storage, databases, logs and exported evidence.
Keep copied code's copyright, license and provenance; use synthetic inputs in tests and demos.
Inferred paths, imported findings and missing headers are not verified vulnerabilities.
Unknown, failed, partial or skipped observations cannot prove a fix; closure requires human review.
Cloud files and operator-supplied host identity do not establish authenticated runtime state.
Preserve existing workspace history, immutable job inputs, idempotency and audit consistency.

Before submission run python scripts/check_all.py and python scripts/quality/check_repository.py.
Exercise affected API/UI flows with local targets and document actual commands and limitations.
Keep feature-matrix, project-status, API contracts and relevant ADRs aligned with behavior changes.
Separate component tests, protocol fixtures, real-provider and installed-package acceptance results.
