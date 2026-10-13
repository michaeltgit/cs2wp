# Same bucket roles and key prefixes as the local stack (core storage routing); names get env + account id.
locals {
  buckets = {
    demos  = "cs2wp-demo-archive"    # raw/<demo_id>.dem, uploads/
    gs     = "cs2wp-gs-data"         # parsed/ features/ scores/ kalshi/ hltv/ catalog/
    models = "cs2wp-model-artifacts" # models/<v>/..., models/registry.json
    web    = "cs2wp-web-assets"      # Vue build (CloudFront origin)
  }
}

resource "aws_s3_bucket" "b" {
  for_each = local.buckets
  bucket   = "${each.value}-${var.env}-${data.aws_caller_identity.current.account_id}" # globally unique
}

resource "aws_s3_bucket_public_access_block" "b" {
  for_each                = aws_s3_bucket.b
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "b" {
  for_each = aws_s3_bucket.b
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_versioning" "models" {
  bucket = aws_s3_bucket.b["models"].id
  versioning_configuration { status = "Enabled" }
}

# Raw demos are parsed once and rarely re-read: move them to Glacier Instant Retrieval after 30 days.
# Uploads are deleted by the ingest job; anything left over is cleaned after 7 days.
resource "aws_s3_bucket_lifecycle_configuration" "demos" {
  bucket = aws_s3_bucket.b["demos"].id
  rule {
    id     = "raw-to-glacier-ir"
    status = "Enabled"
    filter { prefix = "raw/" }
    transition {
      days          = 30
      storage_class = "GLACIER_IR"
    }
  }
  rule {
    id     = "expire-stale-uploads"
    status = "Enabled"
    filter { prefix = "uploads/" }
    expiration { days = 7 }
  }
}

# Read/write on the data buckets: the host's instance role and (stage 2) the Fargate API task role.
data "aws_iam_policy_document" "data_buckets_rw" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = flatten([for k, b in aws_s3_bucket.b : [b.arn, "${b.arn}/*"] if k != "web"])
  }
}
