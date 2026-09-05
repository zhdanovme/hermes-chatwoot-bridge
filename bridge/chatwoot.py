from __future__ import annotations

import httpx


class ChatwootClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        http: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self._http = http
        self.timeout_seconds = timeout_seconds

    async def create_message(self, *, account_id: int, conversation_id: int, content: str) -> dict:
        if not self.api_token:
            raise RuntimeError("CHATWOOT_API_TOKEN is not configured")
        payload = {"content": content, "message_type": "outgoing", "private": False}
        headers = {"api_access_token": self.api_token}
        url = f"{self.base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
        if self._http is not None:
            response = await self._http.post(url, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as http:
                response = await http.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
