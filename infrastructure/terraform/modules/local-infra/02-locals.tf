locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

locals {
  cognito_user_pool_name  = coalesce(var.cognito_user_pool_name, "${local.name_prefix}-users")
  cognito_web_client_name = coalesce(var.cognito_web_client_name, "${local.name_prefix}-web-client")
  cognito_oauth_enabled   = length(var.cognito_callback_urls) > 0

  cognito_client_attributes = distinct(concat(
    [
      "email",
      "email_verified",
      "given_name",
      "family_name",
      "middle_name",
      "nickname",
      "preferred_username",
      "phone_number",
      "phone_number_verified",
      "birthdate",
      "gender",
      "locale",
      "zoneinfo",
      "address",
      "picture",
      "updated_at",
    ],
    [for name in keys(var.cognito_custom_attributes) : "custom:${name}"],
  ))
}

locals {
  backend_bucket_name = coalesce(var.backend_bucket_name, "${local.name_prefix}-backend")
}

locals {
  uploads_queue_name = coalesce(var.uploads_queue_name, "${local.name_prefix}-uploads")
  uploads_dlq_name   = "${local.uploads_queue_name}-dlq"
}

locals {
  langfuse_bucket_name = coalesce(var.langfuse_bucket_name, "${local.name_prefix}-langfuse")
}
