# S3 "Object Created" events -> EventBridge rule -> SQS queue, picked up by a worker.
# Messages received more than uploads_queue_max_receive_count times move to the dead-letter queue.

resource "aws_s3_bucket_notification" "backend" {
  bucket      = aws_s3_bucket.backend.id
  eventbridge = true
}

resource "aws_sqs_queue" "uploads_dlq" {
  name                      = local.uploads_dlq_name
  message_retention_seconds = 1209600 # 14 days, the SQS maximum
  sqs_managed_sse_enabled   = true

  tags = var.common_tags
}

resource "aws_sqs_queue" "uploads" {
  name                       = local.uploads_queue_name
  visibility_timeout_seconds = var.uploads_queue_visibility_timeout_seconds
  message_retention_seconds  = var.uploads_queue_message_retention_seconds
  receive_wait_time_seconds  = 20 # long polling
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.uploads_dlq.arn
    maxReceiveCount     = var.uploads_queue_max_receive_count
  })

  tags = var.common_tags
}

resource "aws_sqs_queue_redrive_allow_policy" "uploads_dlq" {
  queue_url = aws_sqs_queue.uploads_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.uploads.arn]
  })
}

resource "aws_cloudwatch_event_rule" "uploads_object_created" {
  name        = "${local.name_prefix}-uploads-object-created"
  description = "Objects created in the backend bucket under the uploads prefix."

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = merge(
      { bucket = { name = [aws_s3_bucket.backend.bucket] } },
      var.uploads_key_prefix == "" ? {} : { object = { key = [{ prefix = var.uploads_key_prefix }] } },
    )
  })

  tags = var.common_tags
}

resource "aws_cloudwatch_event_target" "uploads_queue" {
  rule      = aws_cloudwatch_event_rule.uploads_object_created.name
  target_id = "uploads-queue"
  arn       = aws_sqs_queue.uploads.arn
}

data "aws_iam_policy_document" "uploads_queue" {
  statement {
    sid       = "AllowEventBridgeRule"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.uploads.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.uploads_object_created.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "uploads" {
  queue_url = aws_sqs_queue.uploads.id
  policy    = data.aws_iam_policy_document.uploads_queue.json
}

# -----------------------------------------------------------------------------
# Access for the worker (attached to the backend role)
# -----------------------------------------------------------------------------

data "aws_iam_policy_document" "uploads_worker" {
  statement {
    sid = "ConsumeUploadsQueue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [aws_sqs_queue.uploads.arn]
  }
}

resource "aws_iam_policy" "uploads_worker" {
  name        = "${local.name_prefix}-uploads-worker"
  description = "Consume messages from the uploads queue."
  policy      = data.aws_iam_policy_document.uploads_worker.json

  tags = var.common_tags
}

resource "aws_iam_role_policy_attachment" "backend_uploads_worker" {
  role       = aws_iam_role.backend.name
  policy_arn = aws_iam_policy.uploads_worker.arn
}
