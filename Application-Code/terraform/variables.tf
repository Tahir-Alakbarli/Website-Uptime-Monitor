variable "aws_region" {
  description = "AWS region used for the infrastructure"
  type        = string
  default     = "eu-central-1"
}

variable "aws_profile" {
  description = "Local AWS CLI profile used by Terraform"
  type        = string
  default     = "tahir-terraform-admin"
}

variable "project_name" {
  description = "Name applied to project resources"
  type        = string
  default     = "website-uptime-monitoring"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.small"
}

variable "root_volume_size" {
  description = "EC2 root volume size in GiB"
  type        = number
  default     = 12

  validation {
    condition     = var.root_volume_size >= 8
    error_message = "The root volume must be at least 8 GiB."
  }
}

variable "dashboard_allowed_cidr" {
  description = "Public IPv4 address allowed to access the dashboard"
  type        = string

  validation {
    condition     = can(cidrhost(var.dashboard_allowed_cidr, 0)) && can(regex("/32$", var.dashboard_allowed_cidr))
    error_message = "Enter one IPv4 address in CIDR format ending in /32."
  }
}

variable "gitlab_project_path" {
  description = "GitLab namespace and project path"
  type        = string
  default     = "Tahir-Alakbarli/website-uptime-monitoring-app"
}