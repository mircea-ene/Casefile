module "core" {
  source = "../modules/local-infra"

  project_name = local.project_name
  environment  = local.environment
  team_name    = local.team_name
  common_tags  = local.common_tags

  # Cognito (web auth for the Next.js app: email + password)
  cognito_allow_self_signup   = true
  cognito_required_attributes = ["email", "given_name", "family_name"]
  cognito_callback_urls       = ["http://localhost:3000/api/auth/callback/cognito"]
  cognito_logout_urls         = ["http://localhost:3000"]

  # S3 bucket for the FastAPI backend
  force_destroy_buckets               = true
  backend_bucket_cors_allowed_origins = ["http://localhost:3000"]
}
