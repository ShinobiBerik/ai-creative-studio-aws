# Step 3 — Build the Backend Compute Layer

### 3.1 Architecture Overview
The backend compute layer maps out a security-first serverless execution profile inside our custom isolated network space. By nesting our AWS Lambda functions directly inside private subnets across two distinct Availability Zones, we eliminate exposure to the public internet while leveraging VPC Gateway Endpoints to interface securely with S3 and DynamoDB data streams.

---

### 3.2 Configuration Artifacts

#### IAM Execution Role Profile
* **Role Name:** `ai-creative-studio-lambda-role`
* **Trusted Entity Service Principal:** `lambda.amazonaws.com`
* **Attached Guardrail Policies:** `AWSLambdaVPCAccessExecutionRole` (AWS Managed)

#### Core Lambda Function Profile
* **Function Name:** `ai-creative-studio-backend-fn`
* **Runtime Framework Layer:** `Python 3.12`
* **Hardware Architecture:** `arm64` (Apple Silicon Optimization Matrix)
* **Assigned Network Targets:**
  * **VPC ID:** `vpc-02e8393e8d34b76a3`
  * **Private Subnet A:** `subnet-048b9fe5aec35316d` (eu-west-2a)
  * **Private Subnet B:** `subnet-092022acb94897f8d` (eu-west-2b)
  * **Attached Firewall Rule Group:** `sg-046061eabe6c4f087` (`ai-creative-studio-backend-sg`)

---

### 3.3 Metadata Resource Tagging Structures
Every asset provisioned during this deployment phase has been systematically tagged using our standard compliance taxonomy parameters:

| Tag Key | Assigned Value | Verification Status |
| :--- | :--- | :--- |
| **Project** | `AI-Creative-Studio` | Verified via CLI Manifest |
| **Environment** | `Development` | Verified via CLI Manifest |
| **Owner** | `Huseyin Berik` | Verified via CLI Manifest |
| **ManagedBy** | `AWS-Console-CLI` | Verified via CLI Manifest |
| **AutoDelete** | `True` | Verified via CLI Manifest |

---

### 3.4 Operational Verification Audits

#### Audit Milestone 1: CLI Resource Matrix Lookup
```bash
aws lambda get-function --function-name ai-creative-studio-backend-fn --output json
```
* **Result Status:** `Active` / `LastUpdateStatus: Successful`
* **Verification Asset:** See `Figure_3.2b_CLI_Lambda_Verification.png`

#### Audit Milestone 2: Private Network Invocations
```bash
aws lambda invoke --function-name ai-creative-studio-backend-fn --payload '{}' response.json
cat response.json
```
* **Result Status:** Returned `StatusCode: 200` containing standard serverless network routing body greetings.
* **Verification Asset:** See `Figure_3.5_CLI_Invoc_Verification.png` & `Figure_3.6_Console_Test_Success.png`
