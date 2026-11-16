output "vpc_id" {
  description = "ID of the isolated AI Creative Studio VPC"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private Subnet IDs across eu-west-2a and eu-west-2b"
  value       = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

output "dynamodb_table_name" {
  description = "Provisioned Free-Tier DynamoDB History Table"
  value       = aws_dynamodb_table.history.name
}

output "sqs_queue_url" {
  description = "Amazon SQS Queue URL decoupling AI Proxy from VPC Backend"
  value       = aws_sqs_queue.jobs.url
}

output "ecr_repository_url" {
  description = "Amazon ECR Private Repository URI for the AI Proxy Container"
  value       = aws_ecr_repository.ai_proxy.repository_url
}

output "s3_website_endpoint" {
  description = "Public S3 Static Website URL for the 4-in-1 AI Creative Studio"
  value       = aws_s3_bucket_website_configuration.frontend_site.website_endpoint
}
