# Offline cloud example

`aws-plan.synthetic.json` is a synthetic Terraform-style AWS plan input. It uses
no real account, infrastructure or credential. Upload it through **云资产 → 上传云配置**
and choose network, IAM and storage checks; or use the built-in cloud sample mode.

It intentionally includes a public-source SSH rule, a broad IAM Allow policy,
a wildcard trust principal constrained by a condition, a disabled S3 public-access
flag, an explicit encryption declaration and an unsupported instance inventory item.
The module preserves these limits instead of treating the example as deployed or
exploitable infrastructure. Condition values and instance user data do not appear
in saved result evidence. See `docs/modules/cloud/configuration-review.md` for format and semantics.
