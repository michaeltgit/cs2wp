# The Linux host: one EC2 instance running host/compose.yml (Redpanda, pipeline worker, live
# runtime, ML worker, and the API in host mode). No SSH: operators use SSM Session Manager.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_cloudwatch_log_group" "host" {
  name              = "/cs2wp/${var.env}/host"
  retention_in_days = 30
}

resource "aws_security_group" "host" {
  name   = "${local.name}-host"
  vpc_id = aws_vpc.main.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Host mode: CloudFront -> API on :8000 (origin-facing CloudFront IPs only)
resource "aws_vpc_security_group_ingress_rule" "host_api_from_cloudfront" {
  count             = local.fargate ? 0 : 1
  security_group_id = aws_security_group.host.id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol       = "tcp"
  from_port         = 8000
  to_port           = 8000
}

# Fargate mode: the API tasks reach Kafka (Redpanda) on the host
resource "aws_vpc_security_group_ingress_rule" "host_kafka_from_api" {
  count                        = local.fargate ? 1 : 0
  security_group_id            = aws_security_group.host.id
  referenced_security_group_id = aws_security_group.api[0].id
  ip_protocol                  = "tcp"
  from_port                    = 19092
  to_port                      = 19092
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "host" {
  name               = "${local.name}-host"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "host_ssm" {
  role       = aws_iam_role.host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "host" {
  source_policy_documents = [data.aws_iam_policy_document.data_buckets_rw.json]
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.main.master_user_secret[0].secret_arn, aws_secretsmanager_secret.ghcr.arn, aws_secretsmanager_secret.app.arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.host.arn}:*"]
  }
}

resource "aws_iam_role_policy" "host" {
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.host.json
}

resource "aws_iam_instance_profile" "host" {
  name = "${local.name}-host"
  role = aws_iam_role.host.name
}

resource "aws_instance" "host" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.host_instance_type
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.host.id]
  iam_instance_profile   = aws_iam_instance_profile.host.name

  root_block_device {
    volume_size = var.host_volume_gb
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2 # containers reach the instance role through IMDSv2
  }

  user_data = templatefile("${path.module}/host/user_data.sh.tftpl", {
    compose_b64      = base64encode(file("${path.module}/host/compose.yml"))
    region           = var.region
    image            = var.image
    compose_profiles = local.fargate ? "" : "api"
    log_group        = aws_cloudwatch_log_group.host.name
    db_address       = aws_db_instance.main.address
    db_secret_arn    = aws_db_instance.main.master_user_secret[0].secret_arn
    ghcr_secret_arn  = aws_secretsmanager_secret.ghcr.arn
    bucket_demos     = aws_s3_bucket.b["demos"].bucket
    bucket_gs        = aws_s3_bucket.b["gs"].bucket
    bucket_models    = aws_s3_bucket.b["models"].bucket
    # CloudFront serves the UI and /api on one origin: no cross-origin callers
    cors_origins = ""
  })
  # Changing user_data does not replace the host; redeploy with /opt/cs2wp/start.sh instead.
  lifecycle { ignore_changes = [user_data, ami] }

  tags = { Name = "${local.name}-host" }
}

# Stable public address for the CloudFront origin across stop/start
resource "aws_eip" "host" {
  instance = aws_instance.host.id
  domain   = "vpc"
}
