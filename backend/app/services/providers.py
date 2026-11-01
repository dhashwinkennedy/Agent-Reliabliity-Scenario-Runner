"""Persisted, OpenAI-compatible LLM providers.  No provider secret leaves this module."""
import ipaddress
import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import ProviderConfiguration


class ProviderError(Exception):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def _url(base_url):
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderError("INVALID_PROVIDER_URL", "base_url must be an absolute HTTP(S) URL without credentials, query, or fragment")
    try:
        addresses = {x[4][0] for x in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ProviderError("PROVIDER_DNS_FAILED", "provider hostname cannot be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved) and not settings.allow_local_llm_providers:
            raise ProviderError("PROVIDER_URL_BLOCKED", "private, loopback, link-local, and reserved provider endpoints are blocked; set ALLOW_LOCAL_LLM_PROVIDERS=true only for trusted local development")
    return base_url.rstrip("/")


def _fernet():
    if not settings.app_encryption_key:
        raise ProviderError("ENCRYPTION_KEY_UNAVAILABLE", "APP_ENCRYPTION_KEY is required before an API key can be stored", 503)
    try:
        return Fernet(settings.app_encryption_key.encode())
    except Exception as exc:
        raise ProviderError("ENCRYPTION_KEY_INVALID", "APP_ENCRYPTION_KEY is invalid", 503) from exc


def encrypt_api_key(value): return _fernet().encrypt(value.encode()).decode()
def decrypt_api_key(value):
    if not value: return None
    try: return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc: raise ProviderError("CREDENTIAL_DECRYPT_FAILED", "stored provider credential cannot be decrypted", 503) from exc

def metadata(item):
    return {"id": item.id, "name": item.display_name, "provider_type": item.provider_type,
            "base_url": item.base_url, "default_model": item.model, "is_active": item.active,
            "api_key_configured": bool(item.encrypted_api_key), "timeout_seconds": item.timeout_seconds,
            "generation_parameters": item.generation_parameters or {}, "created_at": item.created_at, "updated_at": item.updated_at}

def get_provider(db, provider_id, require_active=True):
    item = db.get(ProviderConfiguration, provider_id)
    if not item: raise ProviderError("PROVIDER_NOT_FOUND", "Provider not found", 404)
    if require_active and not item.active: raise ProviderError("PROVIDER_INACTIVE", "Provider is inactive", 409)
    return item

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

def _request(item, suffix, method="GET", payload=None):
    base = _url(item.base_url)
    headers = {"Accept": "application/json"}
    secret = decrypt_api_key(item.encrypted_api_key)
    if secret: headers["Authorization"] = f"Bearer {secret}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"; data = json.dumps(payload).encode()
    request = Request(f"{base}{suffix}", data=data, headers=headers, method=method)
    max_retries = 2
    raw = None
    for attempt in range(max_retries):
        try:
            with build_opener(NoRedirect()).open(request, timeout=item.timeout_seconds) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024: raise ProviderError("PROVIDER_RESPONSE_TOO_LARGE", "Provider response exceeded 1 MiB")
                if not 200 <= response.status < 300: raise ProviderError("PROVIDER_HTTP_ERROR", f"Provider returned HTTP {response.status}", 502)
                break
        except HTTPError as exc:
            if attempt < max_retries - 1 and exc.code in {502, 503, 504, 530, 429}:
                time.sleep(2)
                continue
            code = "PROVIDER_AUTH_FAILED" if exc.code in {401,403} else "PROVIDER_RATE_LIMITED" if exc.code == 429 else "PROVIDER_HTTP_ERROR"
            raise ProviderError(code, f"Provider returned HTTP {exc.code}", 502) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise ProviderError("PROVIDER_UNREACHABLE", "Provider could not be reached within the configured timeout", 502) from exc
    try: return json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "Provider returned invalid JSON", 502) from exc

def discover_models(item):
    body = _request(item, "/models")
    values = body.get("data") if isinstance(body, dict) else None
    if not isinstance(values, list): raise ProviderError("MODEL_DISCOVERY_UNSUPPORTED", "Provider did not return an OpenAI-compatible models response", 502)
    return [x["id"] for x in values if isinstance(x, dict) and isinstance(x.get("id"), str)]

def generate(db: Session, provider_id: str, messages: list[dict], model: str | None = None, generation_settings: dict | None = None):
    item = get_provider(db, provider_id)
    payload = {"model": model or item.model, "messages": messages, **(item.generation_parameters or {}), **(generation_settings or {})}
    try:
        body = _request(item, "/chat/completions", "POST", payload)
    except ProviderError as exc:
        if "response_format" in payload and "HTTP 400" in str(exc.message):
            fallback_payload = dict(payload)
            fallback_payload.pop("response_format", None)
            body = _request(item, "/chat/completions", "POST", fallback_payload)
        else:
            raise
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict) or not isinstance(choices[0].get("message"), dict):
        raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "Provider did not return an OpenAI-compatible chat completion", 502)
    return body

def connection_test(item):
    checks, errors = [], []
    start_time = time.monotonic()
    try:
        _url(item.base_url)
        checks.append({"name": "base_url", "ok": True})
    except ProviderError as exc:
        latency_ms = int((time.monotonic() - start_time) * 1000)
        return {
            "ok": False,
            "reachable": False,
            "latency_ms": latency_ms,
            "checks": [{"name": "base_url", "ok": False}],
            "errors": [{"code": exc.code, "message": exc.message}],
        }
    models = None
    reachable = True
    try:
        models = discover_models(item)
        checks.append({"name": "model_discovery", "ok": True, "models": models})
        if item.model not in models:
            errors.append({"code": "MODEL_NOT_LISTED", "message": "Configured model was not returned by discovery"})
    except ProviderError as exc:
        if exc.code == "PROVIDER_UNREACHABLE":
            reachable = False
        checks.append({"name": "model_discovery", "ok": False})
        errors.append({"code": exc.code, "message": exc.message})
    try:
        generate_for_item(item)
        checks.append({"name": "completion", "ok": True, "model": item.model})
    except ProviderError as exc:
        if exc.code == "PROVIDER_UNREACHABLE":
            reachable = False
        checks.append({"name": "completion", "ok": False})
        errors.append({"code": exc.code, "message": exc.message})
    latency_ms = int((time.monotonic() - start_time) * 1000)
    is_ok = any(x["name"] == "completion" and x["ok"] for x in checks)
    return {
        "ok": is_ok,
        "reachable": reachable,
        "latency_ms": latency_ms,
        "checks": checks,
        "errors": errors,
    }

def generate_for_item(item):
    payload = {"model":item.model, "messages":[{"role":"user","content":"Reply with OK."}], "max_tokens":4}
    body = _request(item, "/chat/completions", "POST", payload)
    if not isinstance(body, dict) or not isinstance(body.get("choices"), list) or not body["choices"]:
        raise ProviderError("PROVIDER_MALFORMED_RESPONSE", "Provider did not return an OpenAI-compatible chat completion", 502)
    return body
