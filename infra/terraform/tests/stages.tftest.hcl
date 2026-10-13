# Plans both stages against a mocked AWS provider (no credentials, nothing created):
#   tofu init -backend=false && tofu test
mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-1a", "us-east-1b"] }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_ssm_parameter" {
    defaults = { value = "ami-0123456789abcdef0" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_iam_role" }
  }
  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_lb_target_group" }
  }
  mock_resource "aws_lb" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_lb" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_secretsmanager_secret" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_cloudwatch_log_group" }
  }
  mock_resource "aws_cloudfront_distribution" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_cloudfront_distribution" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_s3_bucket" }
  }
  mock_resource "aws_ecs_cluster" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_ecs_cluster" }
  }
  mock_resource "aws_iam_instance_profile" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_iam_instance_profile" }
  }
  mock_resource "aws_ecs_task_definition" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_ecs_task_definition" }
  }
  mock_resource "aws_cloudfront_origin_access_control" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_cloudfront_origin_access_control" }
  }
  mock_resource "aws_lb_listener" {
    defaults = { arn = "arn:aws:iam::123456789012:mock/aws_lb_listener" }
  }
  mock_resource "aws_db_instance" {
    defaults = { master_user_secret = [{ secret_arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:rds", kms_key_id = "", secret_status = "active" }] }
  }
}

run "stage1_host" {
  command = plan
  variables { api_mode = "host" }
  assert {
    condition     = length(aws_nat_gateway.main) == 0 && length(aws_lb.api) == 0 && length(aws_ecs_service.api) == 0
    error_message = "stage 1 must not create a NAT gateway, ALB or ECS service"
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.host_api_from_cloudfront) == 1
    error_message = "stage 1 must open the API port on the host to CloudFront"
  }
  assert {
    condition     = strcontains(aws_instance.host.user_data, "COMPOSE_PROFILES=api")
    error_message = "stage 1 host must run the api profile"
  }
}

run "stage2_fargate" {
  command = plan
  variables { api_mode = "fargate" }
  assert {
    condition     = length(aws_nat_gateway.main) == 1 && length(aws_ecs_service.api) == 1 && length(aws_lb_listener.http) == 1
    error_message = "stage 2 must create the NAT gateway, ALB listener and ECS service"
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.host_api_from_cloudfront) == 0 && length(aws_vpc_security_group_ingress_rule.host_kafka_from_api) == 1
    error_message = "stage 2 host must expose Kafka to the API, not the API to CloudFront"
  }
  assert {
    condition     = strcontains(aws_instance.host.user_data, "COMPOSE_PROFILES=\n")
    error_message = "stage 2 host must not run the api profile"
  }
}

run "bad_mode_rejected" {
  command = plan
  variables { api_mode = "kubernetes" }
  expect_failures = [var.api_mode]
}
