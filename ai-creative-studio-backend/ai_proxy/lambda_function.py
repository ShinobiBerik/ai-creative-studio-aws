"""
AI Creative Studio — AI Proxy Lambda  (ai-creative-studio-ai-proxy-fn)

Runs OUTSIDE the VPC so it can reach the internet without a NAT Gateway.
- Reads the Hugging Face token from SSM Parameter Store (SecureString), so it never reaches the browser
- Calls Hugging Face for text + image, falls back to the free keyless Pollinations API
- Async-invokes the private VPC history Lambda to log each generation to DynamoDB

Routes (API Gateway HTTP API, payload v2.0):
  POST /generate/text   {messages:[...], max_tokens, sessionId, tool, logPrompt, log}
  POST /generate/image  {prompt, width, height, seed, sessionId, tool, logPrompt, log}
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import boto3

SSM_PARAM = os.environ.get("HF_TOKEN_PARAM", "/ai-creative-studio/hf-token")
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")
HISTORY_FN = os.environ.get("HISTORY_FUNCTION", "ai-creative-studio-backend-fn")
TEXT_MODEL = os.environ.get("HF_TEXT_MODEL", "Qwen/Qwen2.5-Coder-32B-Instruct")
IMAGE_MODEL = os.environ.get("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")

HF_CHAT_URL = "https://router.huggingface.co/v1/chat/completions"
HF_IMAGE_URL = f"https://router.huggingface.co/hf-inference/models/{IMAGE_MODEL}"
POLL_TEXT_URL = "https://text.pollinations.ai/openai"
POLL_IMAGE_URL = "https://image.pollinations.ai/prompt/"
UA = "ai-creative-studio/1.0 (+aws-lambda)"

MAX_TOTAL_CHARS = 16000          # whole conversation (PDF analysis sends ~12k)
MAX_PROMPT_CHARS = 1500          # image prompts
ALLOWED_SIZES = {(1024, 1024), (1280, 720), (720, 1280)}
SESSION_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
TOOLS = {"text", "pdf", "image", "video"}

_ssm = boto3.client("ssm")
_sqs = boto3.client("sqs")
_lambda = boto3.client("lambda")
_token_cache = None


# ---------------------------------------------------------------- helpers
def hf_token():
    """Fetch the token once per container (cold start) and cache it."""
    global _token_cache
    if _token_cache is None:
        try:
            _token_cache = _ssm.get_parameter(Name=SSM_PARAM, WithDecryption=True)["Parameter"]["Value"]
        except Exception as e:  # noqa: BLE001
            print(f"[warn] HF token unavailable, using free fallback only: {e}")
            _token_cache = ""
    return _token_cache


def http(url, data=None, headers=None, timeout=20):
    """Tiny urllib wrapper -> (status, content_type, bytes). Never raises on HTTP errors."""
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def budget(context, reserve=2.5):
    """Seconds left before Lambda/API Gateway time out, minus a safety margin."""
    return max(3.0, context.get_remaining_time_in_millis() / 1000 - reserve)


CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def resp(status, body):
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps(body)}


def log_generation(body, tool, model):
    """Fire-and-forget invoke of the VPC history Lambda."""
    if body.get("log") is False:
        return
    session = str(body.get("sessionId", ""))
    if not SESSION_RE.match(session):
        return
    payload = {
        "action": "log",
        "sessionId": session,
        "tool": tool,
        "prompt": str(body.get("logPrompt", ""))[:500],
        "model": model,
    }
    try:
        if SQS_QUEUE_URL:
            _sqs.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(payload))
        else:
            _lambda.invoke(FunctionName=HISTORY_FN, InvocationType="Event", Payload=json.dumps(payload).encode())
    except Exception as e:  # noqa: BLE001
        print(f"[warn] history log failed: {e}")


# ---------------------------------------------------------------- text
def generate_text(body, context):
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")
    clean = []
    for m in messages[:10]:
        role = m.get("role") if isinstance(m, dict) else None
        if role not in ("system", "user", "assistant"):
            raise ValueError("invalid message role")
        clean.append({"role": role, "content": str(m.get("content", ""))})
    if sum(len(m["content"]) for m in clean) > MAX_TOTAL_CHARS:
        raise ValueError(f"input too long (max {MAX_TOTAL_CHARS} characters)")
    max_tokens = max(50, min(int(body.get("max_tokens", 1000)), 2000))

    token = hf_token()
    if token:
        payload = json.dumps({"model": TEXT_MODEL, "messages": clean, "max_tokens": max_tokens, "temperature": 0.7}).encode()
        status, _, raw = http(HF_CHAT_URL, payload,
                              {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                              timeout=min(20, budget(context, 8)))
        if status == 200:
            try:
                text = json.loads(raw)["choices"][0]["message"]["content"]
                if text:
                    return {"text": text, "model": f"Hugging Face · {TEXT_MODEL}"}
            except (KeyError, IndexError, ValueError):
                pass
        print(f"[warn] HF text failed ({status}): {raw[:200]!r}")

    payload = json.dumps({"model": "openai", "messages": clean, "private": True}).encode()
    status, ctype, raw = http(POLL_TEXT_URL, payload, {"Content-Type": "application/json"}, timeout=budget(context))
    if status != 200:
        raise RuntimeError(f"All text providers failed (last HTTP {status})")
    if "json" in ctype:
        text = json.loads(raw)["choices"][0]["message"]["content"]
    else:
        text = raw.decode("utf-8", "replace")
    return {"text": text, "model": "Pollinations · open model (fallback)"}


# ---------------------------------------------------------------- image
def generate_image(body, context):
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("prompt is required")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt too long (max {MAX_PROMPT_CHARS} characters)")
    w, h = int(body.get("width", 1024)), int(body.get("height", 1024))
    if (w, h) not in ALLOWED_SIZES:
        w, h = 1024, 1024
    seed = int(body.get("seed") or 0) % 1_000_000_000

    token = hf_token()
    if token:
        payload = json.dumps({"inputs": prompt, "parameters": {"width": w, "height": h}}).encode()
        status, ctype, raw = http(HF_IMAGE_URL, payload,
                                  {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "image/jpeg"},
                                  timeout=min(18, budget(context, 10)))
        if status == 200 and ctype.startswith("image/"):
            return {"image": base64.b64encode(raw).decode(), "mime": ctype.split(";")[0], "model": f"Hugging Face · {IMAGE_MODEL}"}
        print(f"[warn] HF image failed ({status}): {raw[:200]!r}")

    url = (f"{POLL_IMAGE_URL}{urllib.parse.quote(prompt)}"
           f"?width={w}&height={h}&seed={seed}&nologo=true&model=flux")
    status, ctype, raw = http(url, timeout=budget(context))
    if status != 200 or not ctype.startswith("image/"):
        raise RuntimeError(f"All image providers failed (last HTTP {status})")
    return {"image": base64.b64encode(raw).decode(), "mime": ctype.split(";")[0], "model": "Pollinations · FLUX (fallback)"}


# ---------------------------------------------------------------- handler
def lambda_handler(event, context):
    method = event.get("httpMethod") or (event.get("requestContext", {}).get("http", {}).get("method")) or "POST"
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}
    # Works with both REST API (v1: "path") and HTTP API (v2: "rawPath") payloads
    path = (event.get("rawPath") or event.get("path") or "").rstrip("/")
    try:
        raw = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode()
        body = json.loads(raw)
        tool = body.get("tool") if body.get("tool") in TOOLS else None

        if path.endswith("/generate/text"):
            result = generate_text(body, context)
            log_generation(body, tool or "text", result["model"])
        elif path.endswith("/generate/image"):
            result = generate_image(body, context)
            log_generation(body, tool or "image", result["model"])
        else:
            return resp(404, {"error": "Not found"})
        return resp(200, result)

    except (ValueError, json.JSONDecodeError) as e:
        return resp(400, {"error": str(e)})
    except Exception as e:  # noqa: BLE001
        print(f"[error] {e}")
        return resp(502, {"error": str(e)})
