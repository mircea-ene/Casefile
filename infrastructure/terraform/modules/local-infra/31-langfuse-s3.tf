# Bucket for self-hosted Langfuse. Langfuse writes to the events/ and media/
# prefixes itself; no versioning or CORS needed.

resource "aws_s3_bucket" "langfuse" {
  bucket        = local.langfuse_bucket_name
  force_destroy = var.force_destroy_buckets

  tags = var.common_tags
}

resource "aws_s3_bucket_public_access_block" "langfuse" {
  bucket = aws_s3_bucket.langfuse.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "langfuse" {
  bucket = aws_s3_bucket.langfuse.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "langfuse" {
  bucket = aws_s3_bucket.langfuse.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Raw event files are no longer needed once Langfuse has loaded them into ClickHouse.
resource "aws_s3_bucket_lifecycle_configuration" "langfuse" {
  count  = var.langfuse_events_expiration_days > 0 ? 1 : 0
  bucket = aws_s3_bucket.langfuse.id

  rule {
    id     = "expire-events"
    status = "Enabled"

    filter {
      prefix = "events/"
    }

    expiration {
      days = var.langfuse_events_expiration_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
