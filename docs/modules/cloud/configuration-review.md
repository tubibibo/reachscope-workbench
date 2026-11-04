# Cloud configuration module

The `cloud` module reviews **offline AWS configuration JSON**. It never calls a
cloud API, requires no cloud credential and does not execute Terraform or a scanner.
An IP/domain identifies an external service but cannot supply IAM/security-group
settings; the asset wizard therefore offers external service observation separately.

## Inputs

`config` accepts `mode: demo|import` and a nonempty `checks` subset of
`network`, `iam`, `storage`. An import additionally needs an uploaded JSON file ID
and `.json` filename. The defaults select all three groups. Unselected groups are
not invoked, and their execution entries are explicitly skipped.

Supported input shapes:

- Terraform Plan JSON with `planned_values.root_module`, including nested
  `child_modules`; `resource_changes[].change.after_unknown/after_sensitive` and
  each resource's `sensitive_values` are preserved as explicit markers.
- A standalone IAM identity-policy object with `Statement` (one object or a list).
- AWS `describe-security-groups` style JSON with `SecurityGroups`.
- S3 `get-public-access-block` style JSON with `PublicAccessBlockConfiguration`.

Terraform JSON major format version 1 is supported. This implementation expects
planned values, not arbitrary Terraform state JSON or HCL. Unknown/empty formats
fail explicitly. Supported Terraform resource types:

| Group | Resource types |
|---|---|
| Network | `aws_security_group`, `aws_security_group_rule`, `aws_vpc_security_group_ingress_rule` |
| IAM | `aws_iam_policy`, role/user/group inline policies, `aws_iam_role` trust policy |
| Storage | S3 public-access-block, bucket policy, encryption-configuration and bucket context |

Other resource types remain visible as unsupported inventory entries; their
settings are not automatically called secure. Terraform data sources are excluded.
Configuration/resource identity must be unique to bind evidence unambiguously.

## Rules and interpretation

- **Network:** list rules allowing all IPv4/IPv6 sources to selected TCP management
  or data-service ports (22, 23, 3389, 3306, 5432, 6379, 9200, 27017), including
  all-protocol ingress. This is a rule-allowance observation. It does not evaluate
  routes, public addresses, listening services or all associated controls. It does
  not comprehensively model UDP exposure or arbitrary protocol numbers.
- **IAM:** review Allow `*`/service-wide actions with wildcard Resource, and wildcard
  principals in supported role/bucket policies. Conditions are context requirements,
  not silently ignored proof of access; condition values are omitted from evidence.
  Deny counts and unsupported NotAction/NotResource/NotPrincipal expressions are
  explicit. The module does not calculate effective permissions or policy intersections.
- **S3:** review explicitly disabled public-access-block flags; missing/unknown
  flags are unknown, not false. A disabled flag is not proof of public access.
  Encryption declarations are inventory information only; missing declarations
  do not prove unencrypted data because provider defaults and deployed state matter.
  A bucket resource without companion settings produces an explicit coverage gap.

Statuses are `pass`, `review`, `info`, `unknown`, `not_applicable`. Pass is limited
to the specific supported rule and supplied fields. For IAM, absence of the narrow
broad-permission pattern yields info rather than a least-privilege claim.

## Evidence, limits and privacy

Each check contains a stable rule ID, resource identity, source JSON pointer,
selected values, description/recommendation and evidence IDs. Resources retain
addresses/types/names, support state and their source pointer. The shared evidence
record contains only allowlisted relevant fields, with a SHA-256 of the input for
integrity comparison. JSON pointers identify source locations rather than line
numbers. Execution entries say which groups actually ran or were skipped.

The parser rejects duplicate JSON keys, non-finite numbers, invalid syntax,
resource-address collisions and unsupported main structures. Budgets are 2 MiB,
500 managed resources, 1,000 policy statements in total, 40,000 JSON nodes, nesting
depth 35, Terraform module depth 20 and 300 ingress rules per security group.
Projected strings above 1,024 characters become unknown rather than being silently
analyzed as complete. Oversized projected field names/lists fail explicitly.

Terraform sensitive fields are replaced before analysis; missing/unknown planned
fields and list positions stay unknown. Resource tags, user data and arbitrary
irrelevant input fields are not copied to result evidence. IAM Condition values
are omitted. Resource names/addresses and relevant policy ARNs can still identify
private infrastructure. The original uploaded JSON is retained locally by the
workbench upload service; this module does not promise to erase it.

Only static configuration is reviewed. The result does not prove deployment state,
effective permission, public reachability, exploitability, compliance or overall
safety. The bundled demo is synthetic and requires no cloud account.

## Official references and reuse

The implementation is original project code, not copied Checkov rule source.
Checkov's resource/rule/evidence organization and explicit check selection informed
the adapter design. No Checkov executable or external rules are downloaded/run.

- [AWS IAM evaluation logic](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html)
- [S3 Block Public Access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [Terraform JSON format](https://developer.hashicorp.com/terraform/internals/json-format)
- [Checkov source](https://github.com/bridgecrewio/checkov) — Apache-2.0 upstream;
  reference only, no bundled Checkov code.

References checked on 2026-11-01. Popularity does not transfer an upstream tool's
capabilities or validation to this implementation.
# 0.12 input preview and implementation guidance

The four-step workflow now saves a new cloud input for local coverage preview
before task creation. Preflight verifies the uploaded digest, parses supported
JSON and shows resource-type counts, selected-group applicability and explicit
missing/unknown/redacted/invalid field gaps. It returns no resource addresses,
names, policy values or unrelated input. Normalization is not a security check.
Malformed input blocks execution; a missing field remains a coverage gap rather
than evidence of an unsafe or safely configured deployment.

Each of the seven existing rule IDs now stores original manual guidance alongside
its actual resource, pointer, state and evidence IDs: prerequisites, red-team
review, blue-team steps, verification and rollback. Only selected rules execute.
No cloud credentials, API requests, changes or effective-permission claims are
introduced. Saved cloud-external HTTP probes can separately use deterministic Web
guides with an explicit HTTP-only boundary; paid AI remains website-only.
