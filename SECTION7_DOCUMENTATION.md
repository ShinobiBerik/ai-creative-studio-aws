# 7 Docker Containerization, Amazon ECR & Infrastructure as Code (Terraform)

## 7.1 Project Objective & Architectural Rationale

To transition the AI Creative Studio from manual AWS Management Console provisioning ("ClickOps") to reproducible, enterprise-grade cloud engineering while remaining **100% within the AWS Free Tier (\$0.00/month)**, Section 7 introduces two final engineering layers:

1. **Docker Containerization:** Rather than relying on host-dependent scripts or manual `.zip` uploads, the AI Proxy Lambda (`ai-creative-studio-ai-proxy-fn`) and static SPA frontend (`FrontEnd/index.html`) are packaged into immutable Docker container images (`Dockerfile` and `docker-compose.yml`). Using Amazon's official AWS Lambda Python 3.12 base image (`public.ecr.aws/lambda/python:3.12`) allows local invocation testing via the built-in **Lambda Runtime Interface Emulator (RIE)** before cloud deployment.
2. **Amazon Elastic Container Registry (ECR):** A private container registry (`ai-creative-studio-ai-proxy`) is provisioned in `eu-west-2` using `AES-256` encryption and mutable `latest` tagging, storing the `187.35 MB` container image well within the **500 MB/month Always Free Tier** (\$0.00/month) and avoiding paid ECS Fargate or EKS cluster charges.
3. **Infrastructure as Code (Terraform):** The complete 16-resource AWS architecture (VPC, multi-AZ Public/Private Subnets, Internet Gateway, Route Tables, Gateway VPC Endpoints for S3 and DynamoDB, Backend Security Group, DynamoDB Table, SQS Queue, ECR Repository, and S3 Static Website Bucket) is codified in declarative HashiCorp Configuration Language (`.tf` files) and verified via `terraform init`, `terraform validate`, and `terraform plan`.

---

## 7.2 Local Docker Containerization & Runtime Verification

Two `Dockerfile` configurations and a root `docker-compose.yml` orchestrator were created to run and validate the application stack locally on Apple Silicon (`linux/arm64`):

- **Frontend Container (`ai-creative-studio-frontend`):** Built on `nginx:alpine`, serving `FrontEnd/index.html` on `http://localhost:8080`.
- **AI Proxy Lambda Container (`ai-creative-studio-ai-proxy`):** Built on `public.ecr.aws/lambda/python:3.12`, exposing the AWS Lambda Runtime Interface Emulator on `http://localhost:9000`.

### Visual Verification

**Figure 7.1a — Docker Desktop multi-container runtime status view**

*(Drop your Docker Desktop `Containers` screenshot showing `ai-creative-studio-frontend` on `8080:80` and `ai-creative-studio-ai-proxy` on `9000:8080`)*

Screenshot demonstrates both the Nginx frontend container and the AWS Lambda AI Proxy container running simultaneously in Docker Desktop with a combined memory footprint of `22.86 MB`.

### Immutable CLI Verification

```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
curl -s -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"httpMethod":"POST","path":"/api/generate/text","body":"{\"messages\":[{\"role\":\"user\",\"content\":\"Say hello from Docker in 5 words\"}],\"sessionId\":\"docker-local-test\"}"}'
```

**Figure 7.1b — Local Docker container status and Lambda RIE invocation output**

*(Drop your terminal screenshot showing `docker ps` and `"Hello world from Docker container."`)*

Screenshot demonstrates immutable terminal output confirming both containers are active and that the local AWS Lambda Runtime Interface Emulator returns an HTTP `200` JSON inference response (`"Hello world from Docker container."`).

---

## 7.3 Amazon Elastic Container Registry (ECR) Provisioning & Image Push

To store the built `linux/arm64` Lambda container image in AWS without exceeding Free-Tier storage limits, a private repository named `ai-creative-studio-ai-proxy` was created in `eu-west-2` and populated via authenticated `docker push`.

### Implementation Parameters
- **Repository Name:** `ai-creative-studio-ai-proxy`
- **Visibility:** `Private` (500 MB/month Free Tier)
- **Repository URI:** `552109716692.dkr.ecr.eu-west-2.amazonaws.com/ai-creative-studio-ai-proxy`
- **Tag Immutability:** `Mutable` (`latest` tag overwrites prior builds to conserve storage)
- **Encryption Type:** `AES-256` (\$0.00 AWS-managed encryption)
- **Pushed Image Size:** `187.35 MB` (`187,353,453` bytes, `--provenance=false`)

### Visual Verification

**Figure 7.2a — Amazon ECR private repository creation confirmation**

*(Drop your ECR Console screenshot with the green banner: "Successfully created private repository, ai-creative-studio-ai-proxy")*

Screenshot demonstrates the provisioned `ai-creative-studio-ai-proxy` private repository in `eu-west-2` configured with `Mutable` tag immutability and `AES-256` encryption.

**Figure 7.2b — Amazon ECR pushed container image (`latest`) overview**

*(Drop your ECR `Images (1)` tab screenshot showing `latest` | `Image` | `187.35 MB` | `sha256:f8a272f08e036e...`)*

Screenshot demonstrates the `latest` container image stored inside Amazon ECR with a total compressed size of `187.35 MB`, well within the 500 MB Free-Tier threshold.

### Immutable CLI Verification

```bash
aws ecr describe-images \
  --repository-name ai-creative-studio-ai-proxy \
  --query "imageDetails[*].[imageTags[0],imageSizeInBytes,imageDigest,imagePushedAt]" \
  --output table \
  --no-cli-pager
```

**Figure 7.2c — AWS CLI Amazon ECR image verification output**

*(Drop your terminal screenshot showing `DescribeImages` with `latest | 187353453 | sha256:f8a272f08...`)*

Screenshot demonstrates immutable terminal output confirming the `latest` image tag, byte size (`187353453`), cryptographic `sha256` digest, and push timestamp in `eu-west-2`.

---

## 7.4 Infrastructure as Code (Terraform) Implementation & Validation

To make the entire AWS architecture reproducible from code, four modular Terraform configuration files were authored under `terraform/`:

- **`providers.tf`:** Configures Terraform `>= 1.5.0`, the official `hashicorp/aws` provider (`v5.100.0`) targeting `eu-west-2`, and default project resource tags (`Project = "AI-Creative-Studio"`, `ManagedBy = "Terraform"`, `AutoDelete = "True"`).
- **`variables.tf`:** Parameterizes the AWS region, VPC CIDR (`10.0.0.0/24`), DynamoDB table name, SQS queue name, ECR repository name, and S3 bucket name.
- **`main.tf`:** Codifies all 16 core infrastructure resources across networking (VPC, 4 Subnets across 2 AZs, IGW, Route Tables, S3 & DynamoDB Gateway VPC Endpoints, Backend Security Group), data/messaging (DynamoDB table, SQS queue, ECR repository), and frontend delivery (S3 bucket and website configuration).
- **`outputs.tf`:** Exports `vpc_id`, `private_subnet_ids`, `dynamodb_table_name`, `sqs_queue_url`, `ecr_repository_url`, and `s3_website_endpoint`.

### Immutable CLI Verification

```bash
terraform init
terraform validate
terraform plan
```

**Figure 7.3a — Terraform provider initialization and syntax validation output**

*(Drop your terminal screenshot showing `Terraform has been successfully initialized!` and `Success! The configuration is valid.`)*

Screenshot demonstrates successful installation of the signed `hashicorp/aws v5.100.0` provider plugin and syntax validation across all `.tf` configuration files.

**Figure 7.3b — Terraform dry-run execution plan (`terraform plan`) output**

*(Drop your terminal screenshot showing `Plan: 16 to add, 0 to change, 0 to destroy.` and `Changes to Outputs:`)*

Screenshot demonstrates the read-only `terraform plan` summary confirming all 16 AWS infrastructure resources and 6 output values are ready for reproducible deployment without modifying live production resources.

---

## 7.5 Section 7 Verification & Summary Checklist

| Sub-Section | Component / Action | Implementation Summary | Status |
| :--- | :--- | :--- | :--- |
| **7.1** | Architecture & Free-Tier Strategy | Containerized serverless compute + declarative IaC with zero ECS/EKS or NAT charges (\$0.00/month). | **Completed** |
| **7.2** | Local Docker & RIE Testing | Built `nginx:alpine` frontend and `lambda/python:3.12` AI Proxy containers; verified HTTP `200` locally via `docker compose`. | **Completed** |
| **7.3** | Amazon ECR Private Registry | Created `ai-creative-studio-ai-proxy` in `eu-west-2` and pushed `187.35 MB` `linux/arm64` image (< 500 MB Free Tier). | **Completed** |
| **7.4** | Terraform IaC (`terraform/`) | Authored `providers.tf`, `variables.tf`, `main.tf`, and `outputs.tf`; verified via `terraform init`, `validate`, and `plan` (`16 to add`). | **Completed** |
