variable "project_name" {
  description = "Project name used for naming resources."
  type        = string
}

variable "environment" {
  description = "Environment name (e.g., production, staging, dev)."
  type        = string
}

variable "common_tags" {
  description = "Common tags to be applied to all resources."
  type        = map(string)
}

variable "team_name" {
  description = "Owning team (used for tagging by the root provider default_tags)."
  type        = string
}

variable "force_destroy_buckets" {
  description = "Whether to allow Terraform to destroy S3 buckets even if they contain objects."
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# Cognito
# -----------------------------------------------------------------------------

variable "cognito_user_pool_name" {
  description = "Name of the Cognito user pool. Defaults to <project>-<environment>-users."
  type        = string
  default     = null
}

variable "cognito_web_client_name" {
  description = "Name of the Cognito app client used by the Next.js web app. Defaults to <project>-<environment>-web-client."
  type        = string
  default     = null
}

variable "cognito_deletion_protection" {
  description = "Whether to enable deletion protection on the user pool."
  type        = bool
  default     = false
}

variable "cognito_allow_self_signup" {
  description = "Allow users to sign up themselves. When false, only admins can create users."
  type        = bool
  default     = true
}

variable "cognito_required_attributes" {
  description = "Standard attributes users must provide at sign-up. Changing this after creation recreates the user pool."
  type        = list(string)
  default     = ["email", "given_name", "family_name"]
}

variable "cognito_custom_attributes" {
  description = "Optional custom string attributes (exposed as custom:<name>), keyed by name."
  type = map(object({
    max_length = optional(number, 256)
  }))
  default = {}
}

variable "cognito_password_minimum_length" {
  description = "Minimum password length."
  type        = number
  default     = 8
}

variable "cognito_password_require_lowercase" {
  description = "Require at least one lowercase letter in passwords."
  type        = bool
  default     = true
}

variable "cognito_password_require_uppercase" {
  description = "Require at least one uppercase letter in passwords."
  type        = bool
  default     = true
}

variable "cognito_password_require_numbers" {
  description = "Require at least one number in passwords."
  type        = bool
  default     = true
}

variable "cognito_password_require_symbols" {
  description = "Require at least one symbol in passwords."
  type        = bool
  default     = false
}

variable "cognito_temporary_password_validity_days" {
  description = "Days an admin-issued temporary password stays valid."
  type        = number
  default     = 7
}

variable "cognito_mfa_configuration" {
  description = "MFA setting for the user pool: OFF, OPTIONAL or ON (TOTP)."
  type        = string
  default     = "OFF"

  validation {
    condition     = contains(["OFF", "OPTIONAL", "ON"], var.cognito_mfa_configuration)
    error_message = "cognito_mfa_configuration must be OFF, OPTIONAL or ON."
  }
}

variable "cognito_ses_source_arn" {
  description = "ARN of a verified SES identity for sending emails. When null, Cognito's default sender is used (limited to 50 emails/day)."
  type        = string
  default     = null
}

variable "cognito_from_email_address" {
  description = "From address for Cognito emails. Only used together with cognito_ses_source_arn."
  type        = string
  default     = null
}

variable "cognito_reply_to_email_address" {
  description = "Reply-to address for Cognito emails."
  type        = string
  default     = null
}

variable "cognito_verification_email_subject" {
  description = "Subject of the sign-up verification email."
  type        = string
  default     = "Your verification code"
}

variable "cognito_verification_email_message" {
  description = "Body of the sign-up verification email. Must contain {####}."
  type        = string
  default     = "Your verification code is {####}."
}

variable "cognito_generate_client_secret" {
  description = "Generate a client secret for the app client. Keep false for browser-side (Amplify) auth."
  type        = bool
  default     = false
}

variable "cognito_explicit_auth_flows" {
  description = "Auth flows enabled on the app client."
  type        = list(string)
  default     = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
}

variable "cognito_access_token_validity_minutes" {
  description = "Access token lifetime in minutes."
  type        = number
  default     = 60
}

variable "cognito_id_token_validity_minutes" {
  description = "ID token lifetime in minutes."
  type        = number
  default     = 60
}

variable "cognito_refresh_token_validity_days" {
  description = "Refresh token lifetime in days."
  type        = number
  default     = 30
}

variable "cognito_callback_urls" {
  description = "OAuth callback URLs (e.g. http://localhost:3000/api/auth/callback/cognito). Leave empty to disable the hosted UI / OAuth."
  type        = list(string)
  default     = []
}

variable "cognito_logout_urls" {
  description = "OAuth sign-out redirect URLs."
  type        = list(string)
  default     = []
}

variable "cognito_oauth_scopes" {
  description = "OAuth scopes allowed for the app client."
  type        = list(string)
  default     = ["openid", "email", "profile", "phone"]
}

variable "cognito_domain_prefix" {
  description = "Prefix for the Cognito hosted UI domain (<prefix>.auth.<region>.amazoncognito.com). Null skips the domain."
  type        = string
  default     = null
}

# -----------------------------------------------------------------------------
# S3 (backend bucket)
# -----------------------------------------------------------------------------

variable "backend_bucket_name" {
  description = "Name of the S3 bucket used by the FastAPI backend. Defaults to <project>-<environment>-backend."
  type        = string
  default     = null
}

variable "backend_bucket_versioning" {
  description = "Enable object versioning on the backend bucket."
  type        = bool
  default     = false
}

variable "backend_bucket_cors_allowed_origins" {
  description = "Origins allowed to call the bucket directly from the browser (presigned URLs). Empty disables CORS."
  type        = list(string)
  default     = []
}

variable "backend_role_trusted_services" {
  description = "AWS services allowed to assume the backend IAM role."
  type        = list(string)
  default     = ["ecs-tasks.amazonaws.com"]
}

# -----------------------------------------------------------------------------
# Uploads queue (S3 -> EventBridge -> SQS)
# -----------------------------------------------------------------------------

variable "uploads_queue_name" {
  description = "Name of the SQS queue receiving upload events. Defaults to <project>-<environment>-uploads (DLQ gets a -dlq suffix)."
  type        = string
  default     = null
}

variable "uploads_key_prefix" {
  description = "Only objects whose key starts with this prefix produce queue messages. Empty string matches every object."
  type        = string
  default     = "uploads/"
}

variable "uploads_queue_visibility_timeout_seconds" {
  description = "How long a received message stays hidden from other workers. Should exceed the worker's processing time."
  type        = number
  default     = 300
}

variable "uploads_queue_message_retention_seconds" {
  description = "How long unprocessed messages stay in the queue."
  type        = number
  default     = 345600 # 4 days
}

variable "uploads_queue_max_receive_count" {
  description = "Receives before a message is moved to the dead-letter queue."
  type        = number
  default     = 5
}

# -----------------------------------------------------------------------------
# S3 (Langfuse bucket)
# -----------------------------------------------------------------------------

variable "langfuse_bucket_name" {
  description = "Name of the S3 bucket used by Langfuse. Defaults to <project>-<environment>-langfuse."
  type        = string
  default     = null
}

variable "langfuse_events_expiration_days" {
  description = "Days after which objects under events/ are deleted. 0 disables the lifecycle rule."
  type        = number
  default     = 3
}
