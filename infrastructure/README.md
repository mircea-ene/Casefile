# Casefile infrastructure

Terraform for the AWS resources Casefile needs, run locally against the [Floci](https://floci.io) AWS emulator. Nothing here talks to a real AWS account: the provider points at `http://localhost:4566` and uses the dummy credentials `test`/`test`.

```
infrastructure/
├── docker-compose.yml               # Floci (localhost:4566) and its UI (localhost:4500)
├── floci-data/                      # Floci's persisted state (not committed)
└── terraform/
    ├── local/                       # root module: run Terraform from here
    └── modules/local-infra/         # the resources
```

## What it creates

Resource names start with `local-infra-local-` (`<project>-<environment>`, set in `terraform/local/98-locals.tf`). The backend's and Langfuse's config refer to these exact names, so changing the prefix means updating `backend/.env` and `backend/docker/langfuse/langfuse.env` too.

| Resource | Name | Used by |
|---|---|---|
| Cognito user pool | `local-infra-local-users` | Sign-up and sign-in (email + password, required `email`, `given_name`, `family_name`) |
| Cognito app client | `local-infra-local-web-client` | The frontend (public client, SRP, no secret); the backend checks its tokens |
| S3 bucket | `local-infra-local-backend` | Uploaded originals; private, encrypted, CORS for `http://localhost:3000` (the browser opens files through presigned URLs) |
| IAM policy + role | `local-infra-local-backend` | Read/write on that bucket; the role trusts `ecs-tasks.amazonaws.com` for later use as an ECS task role |
| EventBridge rule | `local-infra-local-uploads-object-created` | Turns every object created under `uploads/` into an "Object Created" event |
| SQS queue | `local-infra-local-uploads` | Indexing jobs for the backend worker: 300 s visibility, 20 s long polling, 4 days retention |
| SQS dead-letter queue | `local-infra-local-uploads-dlq` | Messages received 5 times without being deleted (14 days retention) |
| S3 bucket | `local-infra-local-langfuse` | Langfuse's event and media store; objects under `events/` expire after 3 days |

The region is `us-east-1` (`terraform/local/99-variables.tf`).

## Usage

Requirements: Terraform >= 1.16.5, Docker, and optionally the AWS CLI to inspect resources.

Start Floci, from this directory:

```bash
docker compose up -d --wait   # emulator on :4566, UI on http://localhost:4500
```

Terraform needs no AWS environment variables: the provider in `terraform/local/02-provider.tf` sets Floci's endpoint and the dummy credentials itself. Apply:

```bash
cd terraform/local
terraform init
terraform plan -out=tfplan
terraform apply tfplan
terraform output
```

Copy the outputs into the app config:

| Output | Goes into |
|---|---|
| `cognito_user_pool_id` | `backend/.env` `COGNITO_USER_POOL_ID` (also in `COGNITO_ISSUER` / `COGNITO_JWKS_URL`), `frontend/.env.local` `NEXT_PUBLIC_COGNITO_USER_POOL_ID` |
| `cognito_web_client_id` | `backend/.env` `COGNITO_CLIENT_ID`, `frontend/.env.local` `NEXT_PUBLIC_COGNITO_CLIENT_ID` |
| `backend_bucket_name` | `backend/.env` `S3_BUCKET` |
| `uploads_queue_url` | `backend/.env` `SQS_QUEUE_URL` |
| `langfuse_bucket_name` | `backend/docker/langfuse/langfuse.env` `LANGFUSE_S3_*_BUCKET` |

The AWS CLI does need the environment, to talk to Floci instead of AWS. Inspect the resources from `terraform/local`:

```bash
export AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
aws cognito-idp list-user-pools --max-results 10
aws s3 ls
aws sqs get-queue-attributes --queue-url "$(terraform output -raw uploads_queue_url)" --attribute-names All
```

Create and confirm a test user without the email code:

```bash
POOL_ID=$(terraform output -raw cognito_user_pool_id)
CLIENT_ID=$(terraform output -raw cognito_web_client_id)
aws cognito-idp sign-up --client-id "$CLIENT_ID" --username jane@example.com --password 'Passw0rd!' \
  --user-attributes Name=email,Value=jane@example.com Name=given_name,Value=Jane Name=family_name,Value=Doe
aws cognito-idp admin-confirm-sign-up --user-pool-id "$POOL_ID" --username jane@example.com
```

## Configuration

The module's variables are in `terraform/modules/local-infra/99-variables.tf`, grouped by prefix (`cognito_*`, `backend_bucket_*`, `uploads_*`, `langfuse_*`). Override them in the `module "core"` block of `terraform/local/10-main.tf`. A few to know about:

- `cognito_required_attributes`: changing it after creation recreates the user pool, and its users are lost.
- `cognito_callback_urls`: OAuth and the hosted UI are enabled only when this is non-empty; `cognito_domain_prefix` adds a hosted UI domain.
- `cognito_generate_client_secret`: keep `false` while the browser signs in directly.
- `uploads_queue_visibility_timeout_seconds` and `uploads_queue_max_receive_count`: the worker reads the receive count from the queue, so the retry count follows this setting.
- `langfuse_events_expiration_days`: `0` turns the expiry off.

A new AWS service also needs an entry in the `endpoints` block of `terraform/local/02-provider.tf`; without one the provider calls real AWS.

## State and teardown

State is local (`terraform/local/terraform.tfstate`, not committed). Floci keeps its data in `floci-data/` next to the compose file. If that data is wiped, delete `terraform/local/terraform.tfstate*` before applying again, or Terraform will assume the resources still exist.

```bash
cd terraform/local && terraform destroy
docker compose down              # from infrastructure/; Floci keeps its data in floci-data/
```
