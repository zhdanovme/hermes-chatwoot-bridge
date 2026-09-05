from __future__ import annotations

import json
from typing import Any

import httpx


def extract_response_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("output") or []:
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(str(content["text"]))
    text = "\n".join(parts).strip()
    if not text:
        raise RuntimeError("Hermes returned no assistant text")
    return text


class HermesClient:
    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        model: str,
        instructions: str,
        http: httpx.AsyncClient | None = None,
        timeout_seconds: float = 120,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.instructions = instructions
        self._http = http
        self.timeout_seconds = timeout_seconds

    async def respond(self, *, conversation: str, text: str, contact_context: dict[str, Any]) -> str:
        if not self.api_key:
            raise RuntimeError("HERMES_API_KEY is not configured")
        context = json.dumps(contact_context, ensure_ascii=False, separators=(",", ":"))
        payload = {
            "model": self.model,
            "input": f"[Chatwoot contact metadata]\n{context}\n\n[Incoming message]\n{text}",
            "instructions": self.instructions,
            "conversation": conversation,
            "store": True,
            "tools": [],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.api_url}/v1/responses"
        if self._http is not None:
            response = await self._http.post(url, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as http:
                response = await http.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return extract_response_text(response.json())
