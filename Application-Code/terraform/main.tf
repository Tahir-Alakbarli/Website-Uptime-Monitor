locals {
  project_directory     = "/opt/${var.project_name}"
  mysql_database        = "website_monitoring"
  mysql_user            = "user_monitoring"
  gitlab_registry_image = "registry.gitlab.com/${lower(var.gitlab_project_path)}"
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "random_password" "mysql_password" {
  length           = 24
  special          = true
  override_special = "_-"
}

resource "aws_vpc" "monitoring" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.project_name}-vpc"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.monitoring.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-public-subnet"
  }
}

resource "aws_internet_gateway" "internet" {
  vpc_id = aws_vpc.monitoring.id

  tags = {
    Name = "${var.project_name}-internet-gateway"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.monitoring.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.internet.id
  }

  tags = {
    Name = "${var.project_name}-public-routes"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "dashboard_security_group" {
  name        = "website-monitoring-security-group"
  description = "Controls access to the monitoring dashboard"
  vpc_id      = aws_vpc.monitoring.id

  tags = {
    Name = "website-monitoring-security-group"
  }
}

resource "aws_vpc_security_group_ingress_rule" "dashboard" {
  security_group_id = aws_security_group.dashboard_security_group.id
  description       = "Dashboard access from the configured address"
  cidr_ipv4         = var.dashboard_allowed_cidr
  from_port         = 8000
  to_port           = 8000
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "internet" {
  security_group_id = aws_security_group.dashboard_security_group.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_iam_role" "website_server_role" {
  name = "website-monitoring-server-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "ec2.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "website_server_ssm" {
  role       = aws_iam_role.website_server_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "website_server_profile" {
  name = "website-monitoring-server-profile"
  role = aws_iam_role.website_server_role.name
}

resource "aws_instance" "website_server" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.dashboard_security_group.id]
  iam_instance_profile        = aws_iam_instance_profile.website_server_profile.name
  associate_public_ip_address = true
  user_data_replace_on_change = true

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    aws_region            = var.aws_region
    project_directory     = local.project_directory
    compose_file_base64   = filebase64("${path.module}/../compose.aws.yaml")
    gitlab_registry_image = local.gitlab_registry_image
    mysql_database        = local.mysql_database
    mysql_user            = local.mysql_user
    mysql_password        = random_password.mysql_password.result
  })

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = "Website-Uptime-Monitoring-Server"
  }

  depends_on = [
    aws_route_table_association.public,
    aws_iam_role_policy_attachment.website_server_ssm
  ]
}

resource "aws_iam_openid_connect_provider" "gitlab_oidc_provider" {
  url = "https://gitlab.com"

  client_id_list = [
    "sts.amazonaws.com"
  ]
}

resource "aws_iam_role" "gitlab_deployer_role" {
  name                 = "gitlab-website-monitoring-deployer"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Federated = aws_iam_openid_connect_provider.gitlab_oidc_provider.arn
        }

        Action = "sts:AssumeRoleWithWebIdentity"

        Condition = {
          StringEquals = {
            "gitlab.com:aud" = "sts.amazonaws.com"
            "gitlab.com:sub" = "project_path:${var.gitlab_project_path}:ref_type:branch:ref:main"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "gitlab_deployer" {
  name = "website-monitoring-deployment"
  role = aws_iam_role.gitlab_deployer_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "ec2:DescribeInstances"
        ]

        Resource = "*"
      },
      {
        Effect = "Allow"

        Action = [
          "ssm:DescribeInstanceInformation",
          "ssm:GetCommandInvocation"
        ]

        Resource = "*"
      },
      {
        Effect = "Allow"

        Action = [
          "ssm:SendCommand"
        ]

        Resource = [
          aws_instance.website_server.arn,
          "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript"
        ]
      }
    ]
  })
}