"""Synthetic Terraform-style input, distributed as Python data without cloud access."""

from __future__ import annotations

from typing import Any


def demo_document() -> dict[str, Any]:
    return {
        "format_version": "1.2", "terraform_version": "synthetic",
        "planned_values": {"root_module": {"resources": [
            {"address": "aws_security_group.demo", "type": "aws_security_group", "name": "demo",
             "values": {"ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]},
                                     {"protocol": "tcp", "from_port": 443, "to_port": 443, "cidr_blocks": ["0.0.0.0/0"]}]}},
            {"address": "aws_iam_policy.demo", "type": "aws_iam_policy", "name": "demo",
             "values": {"policy": {"Version": "2012-10-17", "Statement": [
                 {"Effect": "Allow", "Action": "s3:*", "Resource": "*"},
                 {"Effect": "Deny", "Action": "s3:DeleteBucket", "Resource": "*"}]}}},
            {"address": "aws_iam_role.partner", "type": "aws_iam_role", "name": "partner",
             "values": {"assume_role_policy": {"Statement": [{"Effect": "Allow", "Principal": {"AWS": "*"},
                          "Action": "sts:AssumeRole", "Condition": {"StringEquals": {"sts:ExternalId": "synthetic-condition"}}}]}}},
            {"address": "aws_s3_bucket_public_access_block.demo", "type": "aws_s3_bucket_public_access_block", "name": "demo",
             "values": {"block_public_acls": True, "block_public_policy": False, "ignore_public_acls": True, "restrict_public_buckets": True}},
            {"address": "aws_s3_bucket_server_side_encryption_configuration.demo", "type": "aws_s3_bucket_server_side_encryption_configuration", "name": "demo",
             "values": {"rule": [{"apply_server_side_encryption_by_default": [{"sse_algorithm": "AES256"}]}]}},
            {"address": "aws_instance.inventory_only", "type": "aws_instance", "name": "inventory_only",
             "values": {"user_data": "intentionally never persisted in evidence"}},
        ]}},
    }
