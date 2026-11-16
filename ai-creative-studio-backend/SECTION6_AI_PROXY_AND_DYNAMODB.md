# Section 6: Secure AI Proxy, DynamoDB History & REST API Expansion

## 6.1 Project Objective
To complete the end-to-end serverless architecture while adhering strictly to AWS Free-Tier guidelines and the security principles established in Section 1:

1. **Zero Secrets in the Browser**: Store the Hugging Face API token encrypted in **AWS Systems Manager (SSM) Parameter Store (`SecureString`)** rather than in the public S3 `index.html`.
2. **Zero NAT Gateway Spend (\$0/month)**: Provision a dedicated **AI Proxy Lambda (`ai-creative-studio-ai-proxy-fn`)** outside the VPC so it has free outbound internet access to call open-source AI inference endpoints (Hugging Face + Pollinations fallback), while asynchronously invoking the private VPC Lambda (`ai-creative-studio-backend-fn`) to log generation history.
3. **Private Data Persistence**: Provision the **Amazon DynamoDB** table (`ai-creative-studio-history`) accessed exclusively from the private subnets via the existing **DynamoDB Gateway VPC Endpoint (`vpce-0e1731583522bc46a`)**.
4. **Least-Privilege IAM Hardening**: Replace broad `FullAccess` managed policies on `ai-creative-studio-lambda-role` with a scoped inline policy limited to `dynamodb:PutItem` and `dynamodb:Query` on the project table.
5. **Existing REST API Expansion**: Extend the existing Regional REST API **`ai-creative-studio-api` (`hz25eon6d3`)** and `/api` resource (`1qfw17`) from Section 4 rather than creating a duplicate API.

```
Browser ──► S3 Static Website (ai-creative-studio-frontend, zero secrets)
   │
   └──► API Gateway REST API (hz25eon6d3 / stage: dev)
          ├── POST /api/generate/text  ┐
          ├── POST /api/generate/image ┴─► AI Proxy Lambda (no VPC) ──► Hugging Face (token from SSM)
          │                                     │                    └─► Pollinations (free fallback)
          │                                     └─ async invoke ─┐
          ├── GET  /api/history ─────────────────────────────────┤
          └── GET  /api (/api/health) ───────────────────────────┴─► History Lambda (Private Subnets A + B)
                                                                            └─► DynamoDB (via vpce-0e1731583522bc46a)
```

---

## 6.2 Shared Environment Variables
Run these first in your terminal before executing the steps below:

```bash
export AWS_REGION=eu-west-2
export ACCOUNT_ID=552109716692
export API_ID=hz25eon6d3
export API_RESOURCE_ID=1qfw17
export TAGS_KV="Project=AI-Creative-Studio,Environment=Development,Owner=Huseyin Berik,ManagedBy=AWS-Console-CLI,AutoDelete=True"
cd "/Users/hberik/Cloud Projects/AWS cloud/ai-creative-studio-backend"
```

---

## 6.3 Store the Hugging Face Token in SSM Parameter Store
> **Security Note:** First revoke the previously exposed token at `https://huggingface.co/settings/tokens` and generate a new fine-grained token with *Make calls to Inference Providers* enabled. If you prefer to use only the keyless Pollinations API, you can skip this step and the proxy Lambda will automatically use Pollinations.

```bash
read -s "HF_TOKEN?Paste new Hugging Face token: " && echo
aws ssm put-parameter \
  --name /ai-creative-studio/hf-token \
  --type SecureString \
  --value "$HF_TOKEN" \
  --overwrite \
  --description "Hugging Face token for AI Creative Studio proxy" \
  --tags Key=Project,Value=AI-Creative-Studio Key=Environment,Value=Development Key=Owner,Value="Huseyin Berik" Key=ManagedBy,Value=AWS-Console-CLI Key=AutoDelete,Value=True
unset HF_TOKEN
```

### Immutable CLI Verification
```bash
aws ssm describe-parameters \
  --parameter-filters "Key=Name,Values=/ai-creative-studio/hf-token" \
  --query "Parameters[*].[Name,Type,Version,LastModifiedDate]" \
  --output table \
  --no-cli-pager
```

---

## 6.4 Provision Amazon DynamoDB History Table
To store generation metadata within the AWS Free Tier (25 GB storage + 25 provisioned WCU/RCU always free), create `ai-creative-studio-history` with a 30-day TTL:

```bash
aws dynamodb create-table \
  --table-name ai-creative-studio-history \
  --attribute-definitions AttributeName=sessionId,AttributeType=S AttributeName=createdAt,AttributeType=S \
  --key-schema AttributeName=sessionId,KeyType=HASH AttributeName=createdAt,KeyType=RANGE \
  --billing-mode PROVISIONED \
  --provisioned-throughput ReadCapacityUnits=1,WriteCapacityUnits=1 \
  --tags Key=Project,Value=AI-Creative-Studio Key=Environment,Value=Development Key=Owner,Value="Huseyin Berik" Key=ManagedBy,Value=AWS-Console-CLI Key=AutoDelete,Value=True \
  --no-cli-pager

aws dynamodb wait table-exists --table-name ai-creative-studio-history

aws dynamodb update-time-to-live \
  --table-name ai-creative-studio-history \
  --time-to-live-specification Enabled=true,AttributeName=expiresAt \
  --no-cli-pager
```

### Immutable CLI Verification
```bash
aws dynamodb describe-table \
  --table-name ai-creative-studio-history \
  --query "Table.[TableName,TableStatus,KeySchema,ProvisionedThroughput.ReadCapacityUnits,ProvisionedThroughput.WriteCapacityUnits]" \
  --output table \
  --no-cli-pager
```

---

## 6.5 Upgrade & Harden the Private VPC History Lambda (`ai-creative-studio-backend-fn`)

### 6.5.1 Least-Privilege IAM Hardening
Scope `ai-creative-studio-lambda-role` to only `PutItem` and `Query` on `ai-creative-studio-history` and detach the broad `FullAccess` policies:

```bash
cat > /tmp/history-ddb-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "LeastPrivilegeHistoryTableAccess",
    "Effect": "Allow",
    "Action": ["dynamodb:PutItem", "dynamodb:Query"],
    "Resource": "arn:aws:dynamodb:${AWS_REGION}:${ACCOUNT_ID}:table/ai-creative-studio-history"
  }]
}
EOF

aws iam put-role-policy \
  --role-name ai-creative-studio-lambda-role \
  --policy-name ai-creative-studio-history-ddb \
  --policy-document file:///tmp/history-ddb-policy.json

aws iam detach-role-policy \
  --role-name ai-creative-studio-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
```

### 6.5.2 Deploy Updated History Handler & Increase Timeout
Update `ai-creative-studio-backend-fn` with `history/lambda_function.py` and raise the timeout from 3s to 10s so VPC cold starts and DynamoDB queries complete reliably:

```bash
(cd history && zip -j ../history.zip lambda_function.py)

aws lambda update-function-code \
  --function-name ai-creative-studio-backend-fn \
  --zip-file fileb://history.zip \
  --no-cli-pager

aws lambda wait function-updated --function-name ai-creative-studio-backend-fn

aws lambda update-function-configuration \
  --function-name ai-creative-studio-backend-fn \
  --timeout 10 \
  --environment "Variables={TABLE_NAME=ai-creative-studio-history,TTL_DAYS=30}" \
  --no-cli-pager
```

---

## 6.6 Provision the AI Proxy Lambda (`ai-creative-studio-ai-proxy-fn`)

### 6.6.1 Least-Privilege Execution Role
Create `ai-creative-studio-ai-proxy-role` with permissions solely to read `/ai-creative-studio/hf-token` from SSM and asynchronously invoke `ai-creative-studio-backend-fn`:

```bash
cat > /tmp/lambda-trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role \
  --role-name ai-creative-studio-ai-proxy-role \
  --assume-role-policy-document file:///tmp/lambda-trust.json \
  --tags Key=Project,Value=AI-Creative-Studio Key=Environment,Value=Development Key=Owner,Value="Huseyin Berik" Key=ManagedBy,Value=AWS-Console-CLI Key=AutoDelete,Value=True \
  --no-cli-pager

aws iam attach-role-policy \
  --role-name ai-creative-studio-ai-proxy-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

cat > /tmp/proxy-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadHfTokenFromSSM",
      "Effect": "Allow",
      "Action": "ssm:GetParameter",
      "Resource": "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/ai-creative-studio/hf-token"
    },
    {
      "Sid": "AsyncInvokeHistoryLambda",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:ai-creative-studio-backend-fn"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name ai-creative-studio-ai-proxy-role \
  --policy-name ai-creative-studio-proxy-access \
  --policy-document file:///tmp/proxy-policy.json

sleep 10
```

### 6.6.2 Create the AI Proxy Function (Outside VPC)
```bash
(cd ai_proxy && zip -j ../ai_proxy.zip lambda_function.py)

aws lambda create-function \
  --function-name ai-creative-studio-ai-proxy-fn \
  --runtime python3.12 \
  --architectures arm64 \
  --handler lambda_function.lambda_handler \
  --role arn:aws:iam::${ACCOUNT_ID}:role/ai-creative-studio-ai-proxy-role \
  --zip-file fileb://ai_proxy.zip \
  --timeout 29 \
  --memory-size 256 \
  --environment "Variables={HF_TOKEN_PARAM=/ai-creative-studio/hf-token,HISTORY_FUNCTION=ai-creative-studio-backend-fn}" \
  --tags "$TAGS_KV" \
  --no-cli-pager
```

---

## 6.7 Extend Existing REST API (`hz25eon6d3`) & Deploy to `dev` Stage
Add `/api/history`, `/api/health`, `/api/generate/text`, and `/api/generate/image` under your existing `/api` resource (`1qfw17`) in `ai-creative-studio-api` (`hz25eon6d3`):

```bash
HIST_URI="arn:aws:apigateway:${AWS_REGION}:lambda:path/2015-03-31/functions/arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:ai-creative-studio-backend-fn/invocations"
PROXY_URI="arn:aws:apigateway:${AWS_REGION}:lambda:path/2015-03-31/functions/arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:ai-creative-studio-ai-proxy-fn/invocations"

# Create child resources under /api (1qfw17)
HISTORY_RES=$(aws apigateway create-resource --rest-api-id $API_ID --parent-id $API_RESOURCE_ID --path-part history --query id --output text)
HEALTH_RES=$(aws apigateway create-resource --rest-api-id $API_ID --parent-id $API_RESOURCE_ID --path-part health --query id --output text)
GEN_RES=$(aws apigateway create-resource --rest-api-id $API_ID --parent-id $API_RESOURCE_ID --path-part generate --query id --output text)
TEXT_RES=$(aws apigateway create-resource --rest-api-id $API_ID --parent-id $GEN_RES --path-part text --query id --output text)
IMAGE_RES=$(aws apigateway create-resource --rest-api-id $API_ID --parent-id $GEN_RES --path-part image --query id --output text)

# Wire ANY methods with Lambda Proxy Integration (handles GET, POST, and OPTIONS preflight automatically)
for RES in $HISTORY_RES $HEALTH_RES; do
  aws apigateway put-method --rest-api-id $API_ID --resource-id $RES --http-method ANY --authorization-type NONE --no-cli-pager
  aws apigateway put-integration --rest-api-id $API_ID --resource-id $RES --http-method ANY --type AWS_PROXY --integration-http-method POST --uri $HIST_URI --no-cli-pager
done

for RES in $TEXT_RES $IMAGE_RES; do
  aws apigateway put-method --rest-api-id $API_ID --resource-id $RES --http-method ANY --authorization-type NONE --no-cli-pager
  aws apigateway put-integration --rest-api-id $API_ID --resource-id $RES --http-method ANY --type AWS_PROXY --integration-http-method POST --uri $PROXY_URI --no-cli-pager
done

# Grant API Gateway permission to invoke both Lambdas
aws lambda add-permission \
  --function-name ai-creative-studio-ai-proxy-fn \
  --statement-id apigw-rest-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${AWS_REGION}:${ACCOUNT_ID}:${API_ID}/*/*/*" \
  --no-cli-pager

aws lambda add-permission \
  --function-name ai-creative-studio-backend-fn \
  --statement-id apigw-rest-subroutes \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${AWS_REGION}:${ACCOUNT_ID}:${API_ID}/*/*/*" \
  --no-cli-pager

# Redeploy the existing dev stage
aws apigateway create-deployment \
  --rest-api-id $API_ID \
  --stage-name dev \
  --description "Section 6: AI Proxy and DynamoDB History routes" \
  --no-cli-pager
```

---

## 6.8 Deploy Updated Frontend to S3 & Verify End-to-End
`FrontEnd/index.html` is already pre-configured with `API_BASE = "https://hz25eon6d3.execute-api.eu-west-2.amazonaws.com/dev/api"`. Upload it to your S3 bucket:

```bash
aws s3 cp "/Users/hberik/Cloud Projects/AWS cloud/FrontEnd/index.html" s3://ai-creative-studio-frontend/index.html --content-type "text/html"
```

### End-to-End CLI Verification
```bash
API="https://hz25eon6d3.execute-api.eu-west-2.amazonaws.com/dev/api"

# 1. Verify Private VPC History Lambda health
curl -s "$API/health"

# 2. Verify AI Proxy Lambda text generation (token stays in SSM)
curl -s -X POST "$API/generate/text" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Say hello from AWS in 5 words"}],"max_tokens":50,"sessionId":"cli-verify-0001","tool":"text","logPrompt":"CLI verification test"}'

# 3. Verify private DynamoDB history persistence via Gateway VPC Endpoint
sleep 2
curl -s "$API/history?sessionId=cli-verify-0001"
```

---

## 6.9 Section 6 Verification & Summary Checklist

| Sub-Section | Component / Action | Implementation Summary | Status |
| :--- | :--- | :--- | :--- |
| **6.3** | **SSM Secret Storage** | Stored Hugging Face token in `/ai-creative-studio/hf-token` (`SecureString`) so zero credentials exist in S3. | Ready |
| **6.4** | **DynamoDB Table** | Provisioned `ai-creative-studio-history` (1 RCU / 1 WCU Always Free + 30-day TTL). | Ready |
| **6.5** | **VPC History Lambda** | Scoped IAM role to least-privilege (`PutItem`, `Query`) and deployed DynamoDB history handler inside private subnets. | Ready |
| **6.6** | **AI Proxy Lambda** | Provisioned `ai-creative-studio-ai-proxy-fn` outside VPC for \$0 NAT-free outbound AI calls + async VPC logging. | Ready |
| **6.7** | **REST API Expansion** | Added `/api/generate/text`, `/api/generate/image`, `/api/history`, and `/api/health` to `hz25eon6d3` (`dev` stage). | Ready |
| **6.8** | **S3 Frontend Upgrade** | Deployed 4-in-1 AI Creative Studio (Text, PDF Generator + Analyzer, Image, Video) wired to `hz25eon6d3`. | Ready |
