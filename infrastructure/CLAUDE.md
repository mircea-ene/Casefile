# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Terraform for a local AWS environment that runs entirely inside the [Floci](https://floci.io) emulator (`localhost:4566`). Nothing here talks to a real AWS account; credentials are the dummy `test`/`test`. Today it provisions a Cognito user pool + public app client for a Next.js (Amplify, SRP) frontend, a private S3 bucket with an IAM policy/role for a FastAPI backend (`30-s3.tf`), and an S3 -> EventBridge -> SQS pipeline (with DLQ) that queues every object created under `uploads/` for a worker (`40-uploads-queue.tf`), plus a private bucket for self-hosted Langfuse with `events/` expiring after 3 days (`31-langfuse-s3.tf`). It is the `infrastructure/` folder of the Casefile monorepo (`../backend`, `../frontend` use these resources by name); the Floci compose is here and the Terraform is under `terraform/`. Usage walkthrough: `README.md`.

## Commands

All Terraform commands run from `terraform/local/` (the only root module).

```bash
docker compose up -d               # Floci on :4566 (UI :4500); must be running before plan/apply

cd terraform/local
terraform init
terraform fmt -recursive ..        # format root + modules
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
terraform output                   # Cognito ids, bucket names, queue URLs
terraform destroy
```

There are no tests. Verify changes with `terraform validate` and `terraform plan`, then inspect resources with the AWS CLI pointed at Floci:

```bash
export AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
aws cognito-idp list-user-pools --max-results 10
```

## Architecture

- `terraform/local/` — root module. Configures the AWS provider to target Floci, sets locals (`project_name = "local-infra"`, `environment = "local"`, `common_tags`), and calls `module "core"` with per-environment overrides. Provider vars: `aws_region` (default `us-east-1`), `floci_endpoint`.
- `terraform/modules/local-infra/` — the reusable module holding the actual resources. Variables are grouped and prefixed by service (`cognito_*`, `backend_bucket_*`, `uploads_*`, `langfuse_*`); names derive from `local.name_prefix` = `<project>-<environment>`.
- Resource names (`local-infra-local-*`) are referenced by the backend's `.env` and `docker/langfuse/langfuse.env`; renaming them means updating those too.

Conventions:

- Files use numeric prefixes by role: `00-backend`, `01-versions`, `02-provider`/`02-locals`, `10-main`, `20-<service>`, `90-outputs`, `98-locals`, `99-variables`. New services in the module get their own `NN-<service>.tf` file.
- Provider `~> 6.68.0`, Terraform `>= 1.16.5`; both the root and module pin versions — keep them in sync.
- Module outputs must be re-exported in `terraform/local/90-outputs.tf` to be visible from `terraform output`.

## Gotchas

- **Adding a new AWS service requires an `endpoints { ... }` entry in `terraform/local/02-provider.tf`**, otherwise the provider calls real AWS. Currently only `cognitoidp`, `events`, `iam`, `s3`, `sqs`, `sts` are mapped.
- State is local (`terraform/local/terraform.tfstate`, gitignored). Floci persists to `floci-data/` (gitignored); if that is wiped, delete `terraform.tfstate*` before applying again.
- Changing `cognito_required_attributes` (or custom attribute schema) after creation forces Cognito to **recreate the user pool**, losing all users.
- OAuth / hosted UI on the app client is toggled implicitly: it is enabled only when `cognito_callback_urls` is non-empty (`local.cognito_oauth_enabled`). The hosted UI domain is created only when `cognito_domain_prefix` is set.
- `cognito_generate_client_secret` must stay `false` for browser-side Amplify auth; set `true` only for server-side flows (e.g. NextAuth).
