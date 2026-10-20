resource "aws_s3_bucket" "backend" {
  bucket        = local.backend_bucket_name
  force_destroy = var.force_destroy_buckets

  tags = var.common_tags
}

resource "aws_s3_bucket_public_access_block" "backend" {
  bucket = aws_s3_bucket.backend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "backend" {
  bucket = aws_s3_bucket.backend.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backend" {
  bucket = aws_s3_bucket.backend.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "backend" {
  bucket = aws_s3_bucket.backend.id

  versioning_configuration {
    status = var.backend_bucket_versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backend" {
  bucket = aws_s3_bucket.backend.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Needed only when browsers upload/download directly with presigned URLs.
resource "aws_s3_bucket_cors_configuration" "backend" {
  count  = length(var.backend_bucket_cors_allowed_origins) > 0 ? 1 : 0
  bucket = aws_s3_bucket.backend.id

  cors_rule {
    allowed_methods = ["GET", "PUT", "POST", "HEAD"]
    allowed_origins = var.backend_bucket_cors_allowed_origins
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

# -----------------------------------------------------------------------------
# Access for the FastAPI backend
# -----------------------------------------------------------------------------

data "aws_iam_policy_document" "backend_s3_access" {
  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.backend.arn]
  }

  statement {
    sid = "ReadWriteObjects"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.backend.arn}/*"]
  }
}

resource "aws_iam_policy" "backend_s3_access" {
  name        = "${local.name_prefix}-backend-s3-access"
  description = "Read/write access to the backend S3 bucket."
  policy      = data.aws_iam_policy_document.backend_s3_access.json

  tags = var.common_tags
}

data "aws_iam_policy_document" "backend_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = var.backend_role_trusted_services
    }
  }
}

# Role the backend runs as (e.g. ECS task role). The app gets temporary
# credentials from it instead of long-lived access keys.
resource "aws_iam_role" "backend" {
  name               = "${local.name_prefix}-backend"
  assume_role_policy = data.aws_iam_policy_document.backend_assume_role.json

  tags = var.common_tags
}

resource "aws_iam_role_policy_attachment" "backend_s3_access" {
  role       = aws_iam_role.backend.name
  policy_arn = aws_iam_policy.backend_s3_access.arn
}
