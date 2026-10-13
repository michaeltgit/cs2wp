# RDS Postgres: demos catalog + durable jobs table (same schema as the local Postgres container).
# Private subnets; reachable from the host and (stage 2) the Fargate API only.
resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_security_group" "db" {
  name   = "${local.name}-db"
  vpc_id = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_host" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.host.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "db_from_api" {
  count                        = local.fargate ? 1 : 0
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.api[0].id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_db_instance" "main" {
  identifier                  = local.name
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = var.db_instance_class
  allocated_storage           = 20
  db_name                     = "cs2wp"
  username                    = "cs2wp"
  manage_master_user_password = true # password lives in Secrets Manager
  db_subnet_group_name        = aws_db_subnet_group.main.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  storage_encrypted           = true
  backup_retention_period     = 7
  skip_final_snapshot         = var.env != "prod"
}

# Values are set by hand (docs/DEPLOYMENT.md), never in Terraform state.
# GHCR pull credentials for the private image: {"username": "...", "password": "<PAT, read:packages>"}
resource "aws_secretsmanager_secret" "ghcr" {
  name = "${local.name}/ghcr"
}

# App secrets for later: Kalshi / GRID API keys
resource "aws_secretsmanager_secret" "app" {
  name = "${local.name}/app"
}
