# Section 6: Secure AI Proxy, Event-Driven SQS Decoupling, DynamoDB Persistence & 4-in-1 Studio

## 6.1 Objective & Architectural Rationale

To transform the static S3 frontend and private VPC backend into a production-grade, end-to-end serverless AI platform while remaining **100% within the AWS Free Tier (\$0.00/month)**, Section 6 introduces four key architectural upgrades:

1. **Zero Secrets in the Browser:** All external AI credentials are removed from `FrontEnd/index.html` and stored encrypted in **AWS Systems Manager (SSM) Parameter Store (`SecureString`)**.
2. **Zero NAT Gateway Spend (\$0.00/month):** Instead of provisioning a paid NAT Gateway (\$32+/month) to give the private VPC Lambda internet access, a dedicated **AI Proxy Lambda (`ai-creative-studio-ai-proxy-fn`)** runs **outside the VPC** with free outbound internet access to call AI inference APIs (Hugging Face Inference with automatic keyless Pollinations fallback).
3. **Event-Driven Decoupling with Amazon SQS:** Rather than coupling the AI Proxy directly to DynamoDB or synchronous database writes, generation metadata is published asynchronously to an **Amazon SQS Standard Queue (`ai-creative-studio-jobs-queue`)**, which triggers the private VPC Lambda (`ai-creative-studio-backend-fn`) to persist records.
4. **Private Data Persistence & Least-Privilege IAM:** `ai-creative-studio-backend-fn` runs exclusively inside **Private Subnets A & B**, reaches **Amazon DynamoDB (`ai-creative-studio-history`)** privately via the **DynamoDB Gateway VPC Endpoint (`vpce-0e1731583522bc46a`)**, and operates under scoped inline IAM policies rather than `FullAccess` managed policies.

### Why a Second Lambda (`ai-creative-studio-ai-proxy-fn`) Is Used for the API Token
- **Why not keep the API token in the S3 frontend?** `FrontEnd/index.html` is served as a public static website. Any API key placed in browser JavaScript is immediately visible to anyone via View Source or browser DevTools. Moving the Hugging Face token to **SSM Parameter Store** and reading it inside a server-side Lambda ensures the token never leaves AWS.
- **Why not reuse the existing `ai-creative-studio-backend-fn` Lambda?** `ai-creative-studio-backend-fn` is intentionally attached to **Private Subnets A & B** with **no outbound internet access** (it can only reach DynamoDB privately via `vpce-0e1731583522bc46a`). Giving a VPC-attached Lambda outbound internet access to call Hugging Face, Pollinations, and SSM requires a **NAT Gateway** (~\$32+/month + data processing fees, outside the AWS Free Tier) or paid Interface VPC Endpoints.
- **The Dual-Lambda Solution (\$0.00/month):** By placing `ai-creative-studio-ai-proxy-fn` **outside the VPC**, AWS provides it with **free outbound internet access** to fetch `/ai-creative-studio/hf-token` from SSM and call external AI APIs, while `ai-creative-studio-backend-fn` stays strictly isolated inside the private subnets.

---

## 6.2 Updated Architecture

```text
Browser (S3 Static Website: ai-creative-studio-frontend, zero secrets)
   │
   └──► Amazon API Gateway REST API (ai-creative-studio-api / hz25eon6d3 / stage: dev)
          │
          ├── POST /api/generate/text  ──┐
          ├── POST /api/generate/image ──┴─► ai-creative-studio-ai-proxy-fn (Outside VPC, 29s timeout)
          │                                     ├── Reads /ai-creative-studio/hf-token (SSM SecureString)
          │                                     ├── Calls Hugging Face API (with Pollinations fallback)
          │                                     └── Sends log event ──► Amazon SQS (ai-creative-studio-jobs-queue)
          │                                                                    │
          │                                                                    ▼ (Lambda Trigger)
          ├── GET /api/health  ─────────────────────────────────────► ai-creative-studio-backend-fn
          └── GET /api/history ─────────────────────────────────────► (Private Subnets A & B, 10s timeout)
                                                                               │
                                                                               ▼ (VPC Gateway Endpoint)
                                                                      Amazon DynamoDB (ai-creative-studio-history)
```

> **[Insert Figure 6.0 — Updated Service Landscape & Architecture Diagram]**
> *Files:* `ai-creative-studio-service-landscape.png` / `ai-creative-studio-architecture-dark.png`

---

## 6.3 Implementation Summary (AWS Region: `eu-west-2`)

### Step 6.1 — Amazon DynamoDB History Table
Created a provisioned Free-Tier NoSQL table to persist per-session generation history with automatic 30-day expiration:
- **Table Name:** `ai-creative-studio-history`
- **Partition Key:** `sessionId` (`String`)
- **Sort Key:** `createdAt` (`String`, ISO-8601 UTC timestamp)
- **Capacity Mode:** Provisioned (`1 RCU`, `1 WCU` — within 25 RCU/WCU Always Free Tier)
- **TTL Attribute:** `expiresAt` (30 days)

### Step 6.2 — IAM Least-Privilege Hardening
Removed `AmazonDynamoDBFullAccess` from `ai-creative-studio-lambda-role` and replaced it with scoped inline policies:
- **`ai-creative-studio-history-ddb`:** Allows only `dynamodb:PutItem` and `dynamodb:Query` on `arn:aws:dynamodb:eu-west-2:552109716692:table/ai-creative-studio-history`.
- **`ai-creative-studio-sqs-read`:** Allows `sqs:ReceiveMessage`, `sqs:DeleteMessage`, and `sqs:GetQueueAttributes` on `ai-creative-studio-jobs-queue`.
- **`ai-creative-studio-proxy-access`** (on `ai-creative-studio-proxy-role`): Allows `ssm:GetParameter` on `/ai-creative-studio/hf-token` and `sqs:SendMessage` on `ai-creative-studio-jobs-queue`.

### Step 6.3 — AWS Systems Manager (SSM) Parameter Store
- **Parameter Name:** `/ai-creative-studio/hf-token`
- **Tier / Type:** `Standard` / `SecureString` (encrypted at rest using AWS-managed KMS key — \$0.00)
- **Purpose:** Stores a fine-grained Hugging Face Inference token so zero credentials appear in source code or S3.

> **[Insert Figure 6.1 — SSM Parameter Store (`/ai-creative-studio/hf-token`)]**

### Step 6.4 — Amazon SQS Queue & Lambda Trigger
- **Queue Name:** `ai-creative-studio-jobs-queue` (Standard Queue)
- **Queue URL:** `https://sqs.eu-west-2.amazonaws.com/552109716692/ai-creative-studio-jobs-queue`
- **Event Source Mapping:** Configured as an active Lambda trigger on `ai-creative-studio-backend-fn`, decoupling AI inference latency from private VPC database writes.

> **[Insert Figure 6.2 — Amazon SQS Queue & Active Lambda Trigger]**

### Step 6.5 — Dual-Lambda Compute Layer
1. **`ai-creative-studio-ai-proxy-fn` (Outside VPC)**
   - **Runtime / Arch:** Python 3.12 (`arm64`), 256 MB RAM, `29 sec` timeout (matching API Gateway's 29s integration limit).
   - **Behavior:** Caches the SSM token across warm invocations, handles `POST /api/generate/text` and `POST /api/generate/image`, automatically falls back to keyless Pollinations if Hugging Face credits/endpoints are unavailable, and enqueues `{action: "log", sessionId, tool, prompt, model}` to SQS.
2. **`ai-creative-studio-backend-fn` (Private Subnets A & B)**
   - **Runtime / Env:** Python 3.12, `10 sec` timeout, `TABLE_NAME=ai-creative-studio-history`, `TTL_DAYS=30`.
   - **Behavior:** Processes SQS `Records` batches to write items into DynamoDB via the Gateway VPC Endpoint, and serves `GET /api/health` and `GET /api/history?sessionId=<id>` through API Gateway.

### Step 6.6 — API Gateway REST API Expansion
Extended the existing Regional REST API **`ai-creative-studio-api` (`hz25eon6d3`, stage `dev`)** with Lambda Proxy Integrations and CORS enabled:
- `GET /api/health` → `ai-creative-studio-backend-fn`
- `GET /api/history` → `ai-creative-studio-backend-fn`
- `POST /api/generate/text` → `ai-creative-studio-ai-proxy-fn`
- `POST /api/generate/image` → `ai-creative-studio-ai-proxy-fn`

### Step 6.7 — 4-in-1 Frontend Upgrade (`s3://ai-creative-studio-frontend/index.html`)
Upgraded the static SPA hosted on S3 with four creative workspaces and zero embedded secrets:
- **Text Studio:** Live prompt generation routed through `/api/generate/text`.
- **PDF Studio:** Client-side PDF Generator (`jsPDF`) and PDF Analyzer (`pdf.js`).
- **Image Studio:** Diffusion image generation routed through `/api/generate/image`.
- **Video Studio:** Storyboard WebM video generator (`MediaRecorder` + `Canvas`).
- **Recent Generations:** Queries `GET /api/history` on load so session history persists across browser refreshes.

---

## 6.4 End-to-End Verification & Results

1. **API Health & VPC Connectivity:** `GET https://hz25eon6d3.execute-api.eu-west-2.amazonaws.com/dev/api/health` returned HTTP `200` (`"Hello from AI Creative Studio Backend (VPC Layer Active!)"`).
2. **AI Proxy Console Test:** Invoking `ai-creative-studio-ai-proxy-fn` returned `statusCode: 200` (`"AWS says hello, welcome aboard."` via `"Pollinations · open model (fallback)"`) and queued a test log event.
3. **Live Website End-to-End Test (Text & Image):**
   - Generated text (`"Explain to me what is a frontend?"`) and an image (`"create me a supercar in the future"`) on the live S3 website (`AWS API (hz25eon6d3) Online`).
   - Verified in **DynamoDB → Explore items (`ai-creative-studio-history`)** that 3 items (`console-test-0001`, `text`, and `image`) were persisted asynchronously via SQS → Private VPC Lambda → DynamoDB with valid `expiresAt` TTL timestamps.

> **[Insert Figure 6.3 — Live 4-in-1 AI Creative Studio Image Generation Output]**
> **[Insert Figure 6.4 — DynamoDB `ai-creative-studio-history` Persisted Items]**

---

## 6.5 Free-Tier Cost Summary

| AWS Service | Configuration | Monthly Cost |
| :--- | :--- | :---: |
| **Amazon S3** | Static website hosting (`index.html`) | **\$0.00** |
| **Amazon API Gateway** | Regional REST API (`hz25eon6d3`, `dev` stage) | **\$0.00** |
| **AWS Lambda (x2)** | `ai-proxy-fn` (No VPC) + `backend-fn` (Private VPC) | **\$0.00** |
| **AWS Systems Manager** | Standard `SecureString` parameter | **\$0.00** |
| **Amazon SQS** | Standard queue (`ai-creative-studio-jobs-queue`) | **\$0.00** |
| **Amazon DynamoDB** | Provisioned `1 RCU / 1 WCU` + Gateway VPC Endpoint | **\$0.00** |
| **Total Section 6 Spend** | **No NAT Gateway, No KMS Custom Keys** | **\$0.00** |
