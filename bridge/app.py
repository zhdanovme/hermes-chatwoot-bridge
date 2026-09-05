from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

from bridge.chatwoot import ChatwootClient
from bridge.hermes import HermesClient
from bridge.idempotency import IdempotencyLedger


@dataclass(slots=True)
class BridgeSettings:
    chatwoot_url: str = "http://chatwoot:3000"
    chatwoot_api_token: str = ""
    chatwoot_webhook_secret: str = ""
    hermes_api_url: str = "http://hermes:8642"
    hermes_api_key: str = ""
    hermes_model: str = "hermes-agent"
    hermes_instructions_file: str = "config/employee.md"
    hermes_instructions: str = field(init=False)
    idempotency_db: str = ":memory:"
    webhook_tolerance_seconds: int = 300

    def __post_init__(self) -> None:
        try:
            self.hermes_instructions = Path(self.hermes_instructions_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"Cannot read instructions file: {self.hermes_instructions_file}") from exc
        if not self.hermes_instructions:
            raise ValueError(f"Empty instructions file: {self.hermes_instructions_file}")

    @classmethod
    def from_env(cls) -> BridgeSettings:
        return cls(
            chatwoot_url=os.getenv("CHATWOOT_URL", "http://chatwoot:3000"),
            chatwoot_api_token=os.getenv("CHATWOOT_API_TOKEN", ""),
            chatwoot_webhook_secret=os.getenv("CHATWOOT_WEBHOOK_SECRET", ""),
            hermes_api_url=os.getenv("HERMES_API_URL", "http://hermes:8642"),
            hermes_api_key=os.getenv("HERMES_API_KEY", ""),
            hermes_model=os.getenv("HERMES_MODEL", "hermes-agent"),
            hermes_instructions_file=os.getenv("HERMES_INSTRUCTIONS_FILE", "config/employee.md"),
            idempotency_db=os.getenv("IDEMPOTENCY_DB", ":memory:"),
            webhook_tolerance_seconds=int(os.getenv("WEBHOOK_TOLERANCE_SECONDS", "300")),
        )


def _verify_signature(raw: bytes, request: Request, settings: BridgeSettings) -> None:
    if not settings.chatwoot_webhook_secret:
        return
    timestamp = request.headers.get("X-Chatwoot-Timestamp", "")
    supplied = request.headers.get("X-Chatwoot-Signature", "")
    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid webhook timestamp") from exc
    if abs(int(time.time()) - timestamp_int) > settings.webhook_tolerance_seconds:
        raise HTTPException(status_code=401, detail="Expired webhook timestamp")
    expected = hmac.new(
        settings.chatwoot_webhook_secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256
    ).hexdigest()
    normalized = supplied.removeprefix("sha256=")
    if not hmac.compare_digest(expected, normalized):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"Missing {name}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Missing {name}") from exc


def _contact_context(payload: dict[str, Any]) -> dict[str, Any]:
    sender = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
    inbox = payload.get("inbox") if isinstance(payload.get("inbox"), dict) else {}
    return {
        "contact_id": sender.get("id"),
        "name": sender.get("name"),
        "email": sender.get("email"),
        "phone_number": sender.get("phone_number"),
        "inbox_id": inbox.get("id"),
        "inbox_name": inbox.get("name"),
    }


def _should_process(payload: dict[str, Any]) -> bool:
    return (
        payload.get("event") == "message_created"
        and payload.get("message_type") == "incoming"
        and payload.get("private") is not True
        and bool(str(payload.get("content") or "").strip())
    )


def create_app(
    settings: BridgeSettings | None = None,
    *,
    hermes_client: HermesClient | None = None,
    chatwoot_client: ChatwootClient | None = None,
    ledger: IdempotencyLedger | None = None,
) -> FastAPI:
    config = settings or BridgeSettings.from_env()
    hermes = hermes_client or HermesClient(
        api_url=config.hermes_api_url,
        api_key=config.hermes_api_key,
        model=config.hermes_model,
        instructions=config.hermes_instructions,
    )
    chatwoot = chatwoot_client or ChatwootClient(
        base_url=config.chatwoot_url,
        api_token=config.chatwoot_api_token,
    )
    events = ledger or IdempotencyLedger(config.idempotency_db)
    session_locks: dict[str, asyncio.Lock] = {}
    app = FastAPI(title="Hermes Chatwoot Bridge", version="0.1.0")

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "configured": bool(config.chatwoot_api_token and config.hermes_api_key),
        }

    @app.post("/webhooks/chatwoot")
    async def chatwoot_webhook(request: Request) -> dict[str, str]:
        raw = await request.body()
        _verify_signature(raw, request, config)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Webhook payload must be an object")
        if not _should_process(payload):
            return {"status": "ignored"}

        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        conversation = payload.get("conversation") if isinstance(payload.get("conversation"), dict) else {}
        account_id = _integer(account.get("id") or payload.get("account_id"), "account id")
        conversation_id = _integer(conversation.get("id") or payload.get("conversation_id"), "conversation id")
        message_id = payload.get("id") or request.headers.get("X-Chatwoot-Delivery", "")
        if not message_id:
            message_id = hashlib.sha256(raw).hexdigest()
        event_key = f"chatwoot:{account_id}:message:{message_id}"
        if not events.claim(event_key):
            return {"status": "duplicate"}

        session = f"hermes:{account_id}:{conversation_id}"
        lock = session_locks.setdefault(session, asyncio.Lock())
        async with lock:
            try:
                answer = await hermes.respond(
                    conversation=session,
                    text=str(payload["content"]).strip(),
                    contact_context=_contact_context(payload),
                )
                await chatwoot.create_message(account_id=account_id, conversation_id=conversation_id, content=answer)
            except (httpx.HTTPError, RuntimeError) as exc:
                events.release(event_key)
                # Chatwoot retries AgentBot webhooks on 500/429. Returning 500 here
                # keeps a transient Hermes/provider outage retryable and visible.
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"status": "replied", "conversation": session}

    return app


app = create_app()
