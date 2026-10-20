resource "aws_cognito_user_pool" "web" {
  name                = local.cognito_user_pool_name
  deletion_protection = var.cognito_deletion_protection ? "ACTIVE" : "INACTIVE"

  # Users sign in with their email address instead of a separate username.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  username_configuration {
    case_sensitive = false
  }

  password_policy {
    minimum_length                   = var.cognito_password_minimum_length
    require_lowercase                = var.cognito_password_require_lowercase
    require_uppercase                = var.cognito_password_require_uppercase
    require_numbers                  = var.cognito_password_require_numbers
    require_symbols                  = var.cognito_password_require_symbols
    temporary_password_validity_days = var.cognito_temporary_password_validity_days
  }

  mfa_configuration = var.cognito_mfa_configuration

  dynamic "software_token_mfa_configuration" {
    for_each = var.cognito_mfa_configuration == "OFF" ? [] : [1]
    content {
      enabled = true
    }
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  admin_create_user_config {
    allow_admin_create_user_only = !var.cognito_allow_self_signup
  }

  email_configuration {
    email_sending_account  = var.cognito_ses_source_arn == null ? "COGNITO_DEFAULT" : "DEVELOPER"
    source_arn             = var.cognito_ses_source_arn
    from_email_address     = var.cognito_from_email_address
    reply_to_email_address = var.cognito_reply_to_email_address
  }

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = var.cognito_verification_email_subject
    email_message        = var.cognito_verification_email_message
  }

  user_attribute_update_settings {
    attributes_require_verification_before_update = ["email"]
  }

  # Standard attributes (phone_number, birthdate, gender, ...) are always available
  # and only need a schema entry when they are required. Changing this list after
  # the pool exists forces Cognito to recreate the pool.
  dynamic "schema" {
    for_each = toset(var.cognito_required_attributes)
    content {
      name                     = schema.value
      attribute_data_type      = "String"
      mutable                  = true
      required                 = true
      developer_only_attribute = false

      string_attribute_constraints {
        min_length = 0
        max_length = 2048
      }
    }
  }

  dynamic "schema" {
    for_each = var.cognito_custom_attributes
    content {
      name                     = schema.key
      attribute_data_type      = "String"
      mutable                  = true
      required                 = false
      developer_only_attribute = false

      string_attribute_constraints {
        min_length = 0
        max_length = schema.value.max_length
      }
    }
  }

  tags = var.common_tags
}

resource "aws_cognito_user_pool_client" "web" {
  name         = local.cognito_web_client_name
  user_pool_id = aws_cognito_user_pool.web.id

  # Public client for the Next.js frontend (Amplify / SRP). Browsers cannot keep a secret.
  generate_secret = var.cognito_generate_client_secret

  explicit_auth_flows = var.cognito_explicit_auth_flows

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = var.cognito_access_token_validity_minutes
  id_token_validity      = var.cognito_id_token_validity_minutes
  refresh_token_validity = var.cognito_refresh_token_validity_days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  read_attributes  = local.cognito_client_attributes
  write_attributes = [for attr in local.cognito_client_attributes : attr if attr != "email_verified" && attr != "phone_number_verified"]

  # Hosted UI / OAuth is only enabled when callback URLs are provided.
  supported_identity_providers         = local.cognito_oauth_enabled ? ["COGNITO"] : null
  allowed_oauth_flows_user_pool_client = local.cognito_oauth_enabled
  allowed_oauth_flows                  = local.cognito_oauth_enabled ? ["code"] : null
  allowed_oauth_scopes                 = local.cognito_oauth_enabled ? var.cognito_oauth_scopes : null
  callback_urls                        = local.cognito_oauth_enabled ? var.cognito_callback_urls : null
  logout_urls                          = local.cognito_oauth_enabled ? var.cognito_logout_urls : null
}

resource "aws_cognito_user_pool_domain" "web" {
  count = var.cognito_domain_prefix == null ? 0 : 1

  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.web.id
}
