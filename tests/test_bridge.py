import asyncio
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest
import yaml

from bridge.app import BridgeSettings, create_app
from bridge.chatwoot import ChatwootClient
from bridge.hermes import HermesClient, extract_response_text


def payload(*, message_type="incoming", private=False, event="message_created"):
    return {
        "event": event,
        "id": 99,
        "message_type": message_type,
        "private": private,
        "content": "Can you help me?",
        "account": {"id": 1, "name": "Local"},
        "conversation": {"id": 7, "status": "open"},
        "sender": {"id": 42, "name": "Ada", "email": "ada@example.test"},
        "inbox": {"id": 3, "name": "Support"},
    }


class FakeHermes:
    def __init__(self, text="Absolutely — what do you need?"):
        self.calls = []
        self.text = text

    async def respond(self, *, conversation, text, contact_context):
        self.calls.append((conversation, text, contact_context))
        return self.text


class FailingHermes(FakeHermes):
    async def respond(self, **kwargs):
        raise RuntimeError("provider unavailable")


class FakeChatwoot:
    def __init__(self):
        self.calls = []

    async def create_message(self, *, account_id, conversation_id, content):
        self.calls.append((account_id, conversation_id, content))
        return {"id": 123}


@pytest.mark.anyio
async def test_incoming_message_is_answered_in_same_chatwoot_conversation():
    hermes = FakeHermes()
    chatwoot = FakeChatwoot()
    app = create_app(
        BridgeSettings(chatwoot_webhook_secret="", hermes_api_url="http://hermes.test"),
        hermes_client=hermes,
        chatwoot_client=chatwoot,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhooks/chatwoot", json=payload())

    assert response.status_code == 200
    assert response.json() == {"status": "replied", "conversation": "hermes:1:7"}
    assert hermes.calls[0][0] == "hermes:1:7"
    assert hermes.calls[0][1] == "Can you help me?"
    assert chatwoot.calls == [(1, 7, "Absolutely — what do you need?")]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "overrides",
    [
        {"message_type": "outgoing"},
        {"private": True},
        {"event": "conversation_updated"},
    ],
)
async def test_non_incoming_events_are_ignored(overrides):
    hermes = FakeHermes()
    chatwoot = FakeChatwoot()
    app = create_app(BridgeSettings(), hermes_client=hermes, chatwoot_client=chatwoot)
    body = payload(**overrides)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhooks/chatwoot", json=body)

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert hermes.calls == []
    assert chatwoot.calls == []


@pytest.mark.anyio
async def test_duplicate_delivery_is_idempotent():
    hermes = FakeHermes()
    chatwoot = FakeChatwoot()
    app = create_app(BridgeSettings(), hermes_client=hermes, chatwoot_client=chatwoot)
    body = payload()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/webhooks/chatwoot", json=body, headers={"X-Chatwoot-Delivery": "delivery-1"})
        second = await client.post("/webhooks/chatwoot", json=body, headers={"X-Chatwoot-Delivery": "delivery-1"})

    assert first.json()["status"] == "replied"
    assert second.json() == {"status": "duplicate"}
    assert len(hermes.calls) == 1
    assert len(chatwoot.calls) == 1


@pytest.mark.anyio
async def test_downstream_failure_is_retryable_and_does_not_poison_event_ledger():
    hermes = FailingHermes()
    app = create_app(BridgeSettings(), hermes_client=hermes, chatwoot_client=FakeChatwoot())
    body = payload()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/webhooks/chatwoot", json=body)
        app.state.hermes = hermes
        second = await client.post("/webhooks/chatwoot", json=body)

    assert first.status_code == 500
    assert second.status_code == 500


@pytest.mark.anyio
async def test_same_conversation_messages_are_serialized():
    class SlowHermes(FakeHermes):
        def __init__(self):
            super().__init__(text="ok")
            self.in_flight = 0
            self.max_in_flight = 0

        async def respond(self, **kwargs):
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            await asyncio.sleep(0.01)
            self.in_flight -= 1
            return await super().respond(**kwargs)

    hermes = SlowHermes()
    app = create_app(BridgeSettings(), hermes_client=hermes, chatwoot_client=FakeChatwoot())
    first_body = payload()
    second_body = payload()
    second_body["id"] = 100

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            client.post("/webhooks/chatwoot", json=first_body),
            client.post("/webhooks/chatwoot", json=second_body),
        )

    assert [response.status_code for response in responses] == [200, 200]
    assert hermes.max_in_flight == 1


@pytest.mark.anyio
async def test_demo_page_bootstraps_chatwoot_web_widget():
    from tests.demo import create_demo_app

    app = create_demo_app(
        public_url="http://localhost:3000", website_token="demo-token",
        hermes_client=FakeHermes(),
        chatwoot_client=FakeChatwoot(),
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/demo")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "demo-token" in response.text
    assert "http://localhost:3000/packs/js/sdk.js" in response.text


@pytest.mark.anyio
async def test_bridge_does_not_expose_test_demo():
    app = create_app(BridgeSettings(), hermes_client=FakeHermes(), chatwoot_client=FakeChatwoot())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/demo")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_signed_webhook_requires_valid_timestamped_signature():
    secret = "bridge-secret"
    app = create_app(
        BridgeSettings(chatwoot_webhook_secret=secret, webhook_tolerance_seconds=60),
        hermes_client=FakeHermes(),
        chatwoot_client=FakeChatwoot(),
    )
    raw = json.dumps(payload(), separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.post(
            "/webhooks/chatwoot",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Chatwoot-Timestamp": timestamp,
                "X-Chatwoot-Signature": f"sha256={signature}",
            },
        )
        bad = await client.post(
            "/webhooks/chatwoot",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Chatwoot-Timestamp": timestamp,
                "X-Chatwoot-Signature": "sha256=bad",
            },
        )

    assert ok.status_code == 200
    assert bad.status_code == 401


def test_extract_response_text_from_responses_api():
    body = {
        "output": [
            {"type": "function_call", "name": "lookup", "status": "completed"},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Final answer"}]},
        ]
    }
    assert extract_response_text(body) == "Final answer"


@pytest.mark.anyio
async def test_hermes_client_uses_named_conversation():
    captured = {}

    def handler(request: httpx.Request):
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Hi Ada"}],
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HermesClient(
            api_url="http://hermes:8642",
            api_key="secret",
            model="hermes-agent",
            instructions="Act as support.",
            http=http,
        )
        result = await client.respond(
            conversation="hermes:1:7",
            text="Hello",
            contact_context={"name": "Ada", "email": "ada@example.test"},
        )

    sent = json.loads(captured["request"].content)
    assert captured["request"].url == httpx.URL("http://hermes:8642/v1/responses")
    assert captured["request"].headers["Authorization"] == "Bearer secret"
    assert sent["conversation"] == "hermes:1:7"
    assert sent["instructions"] == "Act as support."
    assert sent["tools"] == []
    assert "Ada" in sent["input"]
    assert result == "Hi Ada"


def test_hermes_api_platform_has_no_builtin_toolsets():
    config = yaml.safe_load((Path(__file__).parents[1] / "tests" / "config" / "hermes.yaml").read_text())

    assert config["platform_toolsets"]["api_server"] == []


@pytest.mark.anyio
async def test_chatwoot_client_creates_public_outgoing_message():
    captured = {}

    def handler(request: httpx.Request):
        captured["request"] = request
        return httpx.Response(200, json={"id": 123})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ChatwootClient(base_url="http://chatwoot:3000", api_token="token", http=http)
        result = await client.create_message(account_id=1, conversation_id=7, content="Hi Ada")

    sent = json.loads(captured["request"].content)
    assert captured["request"].url == httpx.URL("http://chatwoot:3000/api/v1/accounts/1/conversations/7/messages")
    assert captured["request"].headers["api_access_token"] == "token"
    assert sent == {"content": "Hi Ada", "message_type": "outgoing", "private": False}
    assert result == {"id": 123}
