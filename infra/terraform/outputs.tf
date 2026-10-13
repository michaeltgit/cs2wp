output "web_url" { value = "https://${aws_cloudfront_distribution.web.domain_name}" }
output "api_mode" { value = var.api_mode }
output "api_origin" { value = local.fargate ? aws_lb.api[0].dns_name : "${aws_eip.host.public_dns}:8000" }
output "host_instance_id" { value = aws_instance.host.id }
output "host_shell" { value = "aws ssm start-session --target ${aws_instance.host.id}" }
output "db_endpoint" { value = aws_db_instance.main.endpoint }
output "buckets" { value = { for k, b in aws_s3_bucket.b : k => b.bucket } }
output "cloudfront_id" { value = aws_cloudfront_distribution.web.id }
output "ghcr_secret" { value = aws_secretsmanager_secret.ghcr.name }
