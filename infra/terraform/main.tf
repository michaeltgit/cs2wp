# AWS side of the platform. NOT APPLIED: no AWS account exists yet. Stages: docs/DEPLOYMENT.md.
#   tofu init && tofu plan -var-file=env/dev.tfvars        (or terraform)
#
# api_mode = "host"    (stage 1, default): one EC2 Linux host runs Redpanda (Kafka), the API, the
#                      pipeline + ML workers and the live runtime from the same image as docker compose.
#                      S3, RDS Postgres, CloudFront and Secrets Manager are managed. No NAT, no ALB.
# api_mode = "fargate" (stage 2): the API moves to ECS Fargate behind an ALB (scales out, rolling
#                      deploys); the host keeps Kafka, the workers and the runtime. Adds a NAT gateway.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.70" }
  }
  # Stage 1, step 1 creates this bucket + table once by hand (see docs/DEPLOYMENT.md), then uncomment:
  # backend "s3" { bucket = "cs2wp-tfstate-<account_id>", key = "cs2wp/terraform.tfstate", region = "us-east-1", dynamodb_table = "cs2wp-tflock" }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "cs2wp", env = var.env, owner = "cs2wp" } }
}

data "aws_availability_zones" "available" { state = "available" }
data "aws_caller_identity" "current" {}

locals {
  name    = "cs2wp-${var.env}"
  azs     = slice(data.aws_availability_zones.available.names, 0, 2)
  fargate = var.api_mode == "fargate"
}
