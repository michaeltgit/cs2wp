variable "region" {
  type    = string
  default = "us-east-1"
}

variable "env" {
  type    = string
  default = "dev"
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "api_mode" {
  description = "host = API on the EC2 Linux host (stage 1); fargate = API on ECS Fargate behind an ALB (stage 2)"
  type        = string
  default     = "host"
  validation {
    condition     = contains(["host", "fargate"], var.api_mode)
    error_message = "api_mode must be \"host\" or \"fargate\"."
  }
}

variable "image" {
  description = "Python services image built by CI (.github/workflows/python.yml)"
  type        = string
  default     = "ghcr.io/michaeltgit/cs2wp:latest"
}

variable "host_instance_type" {
  description = "Linux host: Redpanda + workers + runtime (+ API in host mode). Parsing a demo needs a few GB of RAM."
  type        = string
  default     = "t3.large"
}

variable "host_volume_gb" {
  description = "Root volume of the host: Docker images + the local cache in front of S3"
  type        = number
  default     = 60
}

variable "api_desired_count" {
  description = "Fargate API tasks (api_mode = fargate only)"
  type        = number
  default     = 2
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}
