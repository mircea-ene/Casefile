output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.web.id
}

output "cognito_user_pool_arn" {
  value = aws_cognito_user_pool.web.arn
}

output "cognito_user_pool_endpoint" {
  description = "Issuer URL for JWT validation."
  value       = "https://${aws_cognito_user_pool.web.endpoint}"
}

output "cognito_web_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "cognito_web_client_secret" {
  value     = aws_cognito_user_pool_client.web.client_secret
  sensitive = true
}

output "cognito_hosted_ui_domain" {
  value = var.cognito_domain_prefix == null ? null : "https://${aws_cognito_user_pool_domain.web[0].domain}.auth.${data.aws_region.current.region}.amazoncognito.com"
}

output "backend_bucket_name" {
  value = aws_s3_bucket.backend.bucket
}

output "backend_bucket_arn" {
  value = aws_s3_bucket.backend.arn
}

output "backend_s3_access_policy_arn" {
  value = aws_iam_policy.backend_s3_access.arn
}

output "backend_role_arn" {
  value = aws_iam_role.backend.arn
}

output "uploads_queue_url" {
  value = aws_sqs_queue.uploads.id
}

output "uploads_queue_arn" {
  value = aws_sqs_queue.uploads.arn
}

output "uploads_dlq_url" {
  value = aws_sqs_queue.uploads_dlq.id
}

output "langfuse_bucket_name" {
  value = aws_s3_bucket.langfuse.bucket
}
