# Roadmap and honest limits

## Workbench 0.7

The current release provides independent Android/Web/cloud modules, an asset-first
wizard, durable asset history/jobs and genuinely selected check execution. Cloud
review covers bounded offline AWS JSON; external service addresses retain bounded
Web observations. Earlier releases added Web response review and saved comparisons.
Current
contracts are in `docs/architecture/workbench.md` and `docs/reference/workbench-api.md`.

Next priorities are grounded in these implemented workflows:

1. Profile large APK indexing and source-query latency before changing caches.
2. Expand independently reviewed Android and Web input fixtures, including
   ambiguous imports and classifier near misses; keep certainty labels explicit.
3. Add filtering/export options only when real tasks demonstrate a missing view.
   Cloud historical comparison should first define matching resource identities
   and how changed unknown/sensitive markers affect comparability.
4. Add another client module through the same contract when its concrete input,
   evidence model and validation cases are defined. No additional client platform
   is implemented in this release.
5. Build an AI consumer adapter only for a concrete workflow, using the existing
   query/report APIs and measuring evidence use instead of claiming AI improvement.

This is a local single-user product. Authentication, hosted collaboration, crawling
and exploit execution are outside the current implementation. The following
section preserves the 0.4 engine research notes; it is not the workbench feature list.

## Retained engine research notes (0.4)

0.4 delivers a local evidence workflow: durable sources, bounded queries,
report-scoped claims, reproducible examples and packaging. It retains the
previous bounded analysis engine. It does not establish a general program proof
or automatically verify a real-world vulnerability.

The next work should be driven by observed failures:

1. **Independent evaluation.** Curate reviewed source cases that were not used
   to design rules. Compare direct code reading with tool-assisted reading using
   the same input access, fixed model versions and budgets, repeated runs and
   saved transcripts. Measure answer correctness, evidence accuracy, unsupported
   claims, useful abstentions, latency and cost. Do not let a single model author
   the implementation, expected answer and final grade without independent checks.
2. **Analysis precision.** Investigate branch-exclusive data, Intent instance
   identity and unresolved dispatch. Add discriminating positive/near-miss cases
   before extending propagation. Missing paths remain inconclusive.
3. **Scale.** Profile decoding/indexing/analysis/storage on a documented machine.
   Consider reusing the in-memory index and reducing cold-open verification costs
   while preserving explicit integrity semantics. Large APK memory remains a limit;
   file-size budgets are not hard process memory isolation.
4. **Adapters.** Add a thin MCP adapter only when a concrete consumer needs it.
   It must call the same query API and preserve scope, errors, budgets and evidence.
5. **Risk rules.** Design a separate WebView URL-injection risk family with explicit
   preconditions and false-positive cases. Candidate paths alone cannot justify it.

Do not expand FOFA integrations, build a multi-user platform, create a universal
scanner, add a model orchestration framework or grow the sink vocabulary before
the evidence workflow has demonstrated value.

The historical APK benchmark has only two in-scope positive expectations. The
five bundled examples are synthetic regression demonstrations. Neither supports
an overall detection-accuracy claim. No before/after model-performance result has
been measured for this release.
