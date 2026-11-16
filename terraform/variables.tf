variable "aws_region" {
  description = "AWS Region for all AI Creative Studio resources"
  type        = string
  default     = "eu-west-2"
}

variable "environment" {
  description = "Deployment environment tag"
  type        = string
  default     = "Development"
}

variable "project_name" {
  description = "Base naming prefix for all resources"
  type        = string
  default     = "ai-creative-studio"
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block for the isolated VPC"
  type        = string
  default     = "10.0.0.0/24"
}

variable "history_table_name" {
  description = "DynamoDB table storing per-session generation history"
  type        = string
  default     = "ai-creative-studio-history"
}

variable "sqs_queue_name" {
  description = "SQS Standard queue decoupling AI proxy from VPC persistence"
  type        = string
  default     = "ai-creative-studio-jobs-queue"
}

variable "ecr_repository_name" {
  description = "Private Amazon ECR repository for the containerized AI Proxy Lambda"
  type        = string
  default     = "ai-creative-studio-ai-proxy"
}

variable "frontend_bucket_name" {
  description = "S3 bucket hosting the static 4-in-1 AI Creative Studio SPA"
  type        = string
  default     = "ai-creative-studio-frontend"
}
