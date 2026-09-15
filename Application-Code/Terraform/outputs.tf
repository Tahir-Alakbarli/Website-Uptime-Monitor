output "instance_id" {
  description = "EC2 instance used by the monitoring application"
  value       = aws_instance.website_server.id
}

output "dashboard_url" {
  description = "Address of the monitoring dashboard"
  value       = "http://${aws_instance.website_server.public_ip}:8000"
}

output "gitlab_deploy_role_arn" {
  description = "IAM role used by the GitLab deployment job"
  value       = aws_iam_role.gitlab_deployer_role.arn
}