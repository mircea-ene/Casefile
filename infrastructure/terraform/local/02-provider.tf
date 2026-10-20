# Points the AWS provider at the local Floci emulator instead of real AWS.
provider "aws" {
  region     = var.aws_region
  access_key = "test"
  secret_key = "test"

  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  s3_use_path_style           = true

  endpoints {
    cognitoidp = var.floci_endpoint
    events     = var.floci_endpoint
    iam        = var.floci_endpoint
    s3         = var.floci_endpoint
    sqs        = var.floci_endpoint
    sts        = var.floci_endpoint
  }

  default_tags {
    tags = local.common_tags
  }
}
