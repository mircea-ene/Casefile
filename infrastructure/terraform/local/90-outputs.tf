output "cognito_user_pool_id" {
  value = module.core.cognito_user_pool_id
}

output "cognito_user_pool_endpoint" {
  value = module.core.cognito_user_pool_endpoint
}

output "cognito_web_client_id" {
  value = module.core.cognito_web_client_id
}

output "backend_bucket_name" {
  value = module.core.backend_bucket_name
}

output "backend_role_arn" {
  value = module.core.backend_role_arn
}

output "uploads_queue_url" {
  value = module.core.uploads_queue_url
}

output "uploads_dlq_url" {
  value = module.core.uploads_dlq_url
}

output "langfuse_bucket_name" {
  value = module.core.langfuse_bucket_name
}
