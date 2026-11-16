"""
AI Creative Studio — History Lambda  (ai-creative-studio-backend-fn)

Runs INSIDE the VPC (private subnets, 2 AZs). It has no internet access by design;
it reaches DynamoDB privately through the DynamoDB Gateway VPC Endpoint.

Invoked two ways:
  1. Directly (async) by the AI proxy Lambda:  {"action": "log", sessionId, tool, prompt, model}
  2. Through API Gateway HTTP API:
       GET /health                    -> backend status
       GET /history?sessionId=<id>    -> latest generations for this browser session
"""
import json
import os
import re
import time
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ.get("TABLE_NAME", "ai-creative-studio-history")
TTL_DAYS = int(os.environ.get("TTL_DAYS", "30"))
SESSION_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
TOOLS = {"text", "pdf", "image", "video"}

table = boto3.resource("dynamodb").Table(TABLE_NAME)


CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def resp(status, body):
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps(body, default=str)}


def log_item(event):
    session = str(event.get("sessionId", ""))
    tool = event.get("tool")
    if not SESSION_RE.match(session) or tool not in TOOLS:
        print("[warn] rejected log event:", json.dumps(event)[:300])
        return {"status": "rejected"}
    now = datetime.now(timezone.utc)
    table.put_item(Item={
        "sessionId": session,                                   # partition key
        "createdAt": now.isoformat(timespec="milliseconds"),    # sort key
        "tool": tool,
        "prompt": str(event.get("prompt", ""))[:500],
        "model": str(event.get("model", ""))[:120],
        "expiresAt": int(time.time()) + TTL_DAYS * 86400,       # DynamoDB TTL attribute
    })
    return {"status": "logged"}


def handle_http(event):
    method = event.get("httpMethod") or (event.get("requestContext", {}).get("http", {}).get("method")) or "GET"
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}
    # Works with both REST API (v1: "path") and HTTP API (v2: "rawPath") payloads
    path = (event.get("rawPath") or event.get("path") or "").rstrip("/")
    if path.endswith("/health") or path.endswith("/api"):
        return resp(200, {
            "status": "success",
            "service": "history",
            "network": "private-vpc",
            "table": TABLE_NAME,
            "message": "Hello from AI Creative Studio Backend (VPC Layer Active!)",
        })

    if path.endswith("/history"):
        session = (event.get("queryStringParameters") or {}).get("sessionId", "")
        if not SESSION_RE.match(session):
            return resp(400, {"error": "invalid sessionId"})
        out = table.query(
            KeyConditionExpression=Key("sessionId").eq(session),
            ScanIndexForward=False,   # newest first
            Limit=12,
        )
        items = [{k: i.get(k) for k in ("createdAt", "tool", "prompt", "model")} for i in out.get("Items", [])]
        return resp(200, {"items": items})

    return resp(404, {"error": "Not found"})


def lambda_handler(event, context):
    try:
        if "Records" in event:                # triggered by Amazon SQS queue
            for rec in event["Records"]:
                body = json.loads(rec.get("body") or "{}")
                log_item(body)
            return {"status": "processed", "count": len(event["Records"])}
        if "requestContext" in event:          # came through API Gateway
            return handle_http(event)
        if event.get("action") == "log":       # direct invoke from AI proxy
            return log_item(event)
        return {"status": "ok", "message": "AI Creative Studio history service (VPC) is alive"}
    except Exception as e:  # noqa: BLE001
        print(f"[error] {e}")
        if "requestContext" in event:
            return resp(500, {"error": "internal error"})
        raise
