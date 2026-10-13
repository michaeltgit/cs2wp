# Stage 2 (api_mode = "fargate"): the API on ECS Fargate behind an ALB, so it scales out and deploys
# without downtime. Kafka, the workers and the live runtime stay on the host. Nothing here exists
# in stage 1 (every resource has count = 0).
resource "aws_ecs_cluster" "main" {
  count = local.fargate ? 1 : 0
  name  = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "api" {
  count             = local.fargate ? 1 : 0
  name              = "/cs2wp/${var.env}/api"
  retention_in_days = 30
}

resource "aws_security_group" "alb" {
  count  = local.fargate ? 1 : 0
  name   = "${local.name}-alb"
  vpc_id = aws_vpc.main.id
  ingress {
    description     = "CloudFront origin-facing IPs only"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "api" {
  count  = local.fargate ? 1 : 0
  name   = "${local.name}-api"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb[0].id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "api" {
  count              = local.fargate ? 1 : 0
  name               = local.name
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb[0].id]
  idle_timeout       = 3600 # long-lived WebSockets
}

resource "aws_lb_target_group" "api" {
  count       = local.fargate ? 1 : 0
  name        = "${local.name}-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"
  health_check { path = "/healthz" }
  # the WS gateway is stateless in Kafka mode: no stickiness needed
}

# CloudFront terminates HTTPS for viewers and talks HTTP to the ALB. Expansion point: a domain +
# ACM certificate, a 443 listener here and origin_protocol_policy = "https-only" in web.tf.
resource "aws_lb_listener" "http" {
  count             = local.fargate ? 1 : 0
  load_balancer_arn = aws_lb.api[0].arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task" {
  count              = local.fargate ? 1 : 0
  name               = "${local.name}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task_s3" {
  count  = local.fargate ? 1 : 0
  role   = aws_iam_role.task[0].id
  policy = data.aws_iam_policy_document.data_buckets_rw.json
}

resource "aws_iam_role" "execution" {
  count              = local.fargate ? 1 : 0
  name               = "${local.name}-api-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  count      = local.fargate ? 1 : 0
  role       = aws_iam_role.execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The execution role pulls the private image (GHCR secret) and injects the DB password
data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.ghcr.arn, aws_db_instance.main.master_user_secret[0].secret_arn]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  count  = local.fargate ? 1 : 0
  role   = aws_iam_role.execution[0].id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_ecs_task_definition" "api" {
  count                    = local.fargate ? 1 : 0
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  task_role_arn            = aws_iam_role.task[0].arn
  execution_role_arn       = aws_iam_role.execution[0].arn
  container_definitions = jsonencode([{
    name                  = "api"
    image                 = var.image
    repositoryCredentials = { credentialsParameter = aws_secretsmanager_secret.ghcr.arn }
    portMappings          = [{ containerPort = 8000 }]
    environment = [
      { name = "CS2WP_STORAGE", value = "s3" },
      { name = "CS2WP_BUS", value = "kafka" },
      { name = "CS2WP_KAFKA_BOOTSTRAP", value = "${aws_instance.host.private_ip}:19092" },
      { name = "CS2WP_EMBEDDED_WORKERS", value = "0" },
      { name = "CS2WP_DATABASE_URL", value = "postgresql+psycopg://cs2wp:{password}@${aws_db_instance.main.address}:5432/cs2wp" },
      { name = "CS2WP_S3_BUCKET_DEMOS", value = aws_s3_bucket.b["demos"].bucket },
      { name = "CS2WP_S3_BUCKET_GS", value = aws_s3_bucket.b["gs"].bucket },
      { name = "CS2WP_S3_BUCKET_MODELS", value = aws_s3_bucket.b["models"].bucket },
      { name = "CS2WP_CORS_ORIGINS", value = "" },
    ]
    secrets = [
      { name = "CS2WP_DATABASE_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = { awslogs-group = aws_cloudwatch_log_group.api[0].name, awslogs-region = var.region,
      awslogs-stream-prefix = "api" }
    }
  }])
}

resource "aws_ecs_service" "api" {
  count           = local.fargate ? 1 : 0
  name            = "api"
  cluster         = aws_ecs_cluster.main[0].id
  task_definition = aws_ecs_task_definition.api[0].arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.api[0].id]
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api[0].arn
    container_name   = "api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.http]
}
