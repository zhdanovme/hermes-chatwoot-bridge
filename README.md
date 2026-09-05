# Hermes Chatwoot Bridge

Connect an existing Chatwoot inbox to Hermes Agent. The bridge receives an AgentBot
webhook, requests a reply from Hermes, and posts it to the same conversation.

`Chatwoot → bridge → Hermes → bridge → Chatwoot`

The root Compose file starts only the bridge. The complete local sandbox and web
widget demo are in [tests/](tests/README.md).

## Run the bridge

Prerequisites: a running Chatwoot instance, a Hermes server exposing
`/v1/responses`, and API credentials for both.

1. Copy `.env.example` to `.env` and set the service URLs and credentials.
   URLs must be reachable from the bridge container; `localhost` means the
   container itself.
2. Edit [config/employee.md](config/employee.md) with your employee instructions.
3. Disable built-in tools in your Hermes server configuration:

   ```yaml
   platform_toolsets:
     api_server: []
   ```

4. Start the bridge:

   ```bash
   docker compose up -d --build
   curl http://localhost:8080/healthz
   ```

The health endpoint reports `configured: true` when both API credentials are
present; it does not test downstream connectivity.

Port 8080 binds to loopback by default. Use your reverse proxy or a shared Docker
network to make the webhook reachable from Chatwoot.

## Connect an inbox

1. Create a webhook Agent Bot in Chatwoot with outgoing URL
   `<bridge-url>/webhooks/chatwoot`.
2. Assign the bot to your inbox and add the operators who should see its conversations.
3. Set `CHATWOOT_API_TOKEN` to a user token with access to the inbox.
4. If the bot has a webhook secret, put the same value in
   `CHATWOOT_WEBHOOK_SECRET`. Recreate the bridge after environment changes.

Send a message through the inbox and check that its reply appears in the same
conversation. Inspect delivery errors with `docker compose logs -f bridge`.

## Configuration

| Variable | Purpose |
| --- | --- |
| `CHATWOOT_URL`, `CHATWOOT_API_TOKEN` | Chatwoot endpoint and user credential |
| `HERMES_API_URL`, `HERMES_API_KEY` | Hermes endpoint and credential |
| `CHATWOOT_WEBHOOK_SECRET` | Timestamped HMAC validation; empty disables it |
| `HERMES_MODEL` | Hermes model selector; default: `hermes-agent` |
| `WEBHOOK_TOLERANCE_SECONDS` | Maximum signed webhook age; default: 300 |

Compose mounts the employee prompt read-only and persists the delivery ledger in
`bridge_data`. Restart the bridge after editing the prompt. Model provider
credentials belong on the Hermes server.

## Behavior and limits

- Only public incoming `message_created` events containing text trigger replies.
  Outgoing messages and private notes are ignored.
- Each conversation maps to `hermes:{account_id}:{conversation_id}`. Hermes
  persists its history. Messages are serialized per conversation within one bridge process.
- The bridge sends `tools: []`; the Hermes configuration above is also required
  to disable built-in tools. Separate histories alone are not a security boundary.
- The prompt directs replies to use its instructions, contact metadata, and the
  current history. This does not erase the model's pretrained knowledge.
- The SQLite ledger suppresses duplicate message IDs. Downstream HTTP/runtime
  failures return `500` for Chatwoot retries. Delivery is not guaranteed exactly
  once across crashes or ambiguous network failures.
- Human handoff is not automated: mentioning a colleague does not assign an operator.

## Development

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
```

All tests, demo code, and full-stack fixtures are in [tests/](tests/README.md).
Telegram account/MTProto, Wazzup, and email transport adapters are outside the
current scope.
