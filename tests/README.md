# Local integration sandbox

All automated tests, the web demo, and the full local stack live here.
Run sandbox commands from this directory.

## Start

```bash
cp .env.example .env
# Set OPENAI_API_KEY and CHATWOOT_SECRET_KEY_BASE in .env.
docker compose up -d --build
```

This starts Chatwoot, PostgreSQL, Redis, Sidekiq, Hermes, and the bridge.
Configure the Hermes model/provider in [config/hermes.yaml](config/hermes.yaml).
The one-shot `hermes-config` container copies that file to the Hermes volume;
its `Exited (0)` status is expected.

## Test the web chat

1. Open [Chatwoot](http://localhost:3000) and create an administrator.
2. Create a Website inbox and save its Website token as
   `CHATWOOT_WEBSITE_TOKEN` in `.env`.
3. Create a webhook Agent Bot with outgoing URL
   `http://bridge:8080/webhooks/chatwoot` and assign it to the inbox.
4. Add your administrator/operators to that inbox so they can see conversations.
5. Save a Chatwoot user API token as `CHATWOOT_API_TOKEN`.
   Set `CHATWOOT_WEBHOOK_SECRET` too if the bot has a secret.
6. Run `docker compose up -d` to apply environment changes.
7. Send a message through the [web demo](http://localhost:8080/demo) and inspect
   the reply in Chatwoot.

[demo.py](demo.py) supplies the demo route through a test-only mount.
The regular bridge image does not expose this route.

## Configuration and existing data

The bridge uses `../config/employee.md`; rebuild the test bridge after editing it.
After changing Hermes configuration, run:

```bash
docker compose up -d --force-recreate hermes-config hermes
```

The project name `hermes-chatwoot` preserves the original stack's volume names.
To reuse an existing root `.env`:

```bash
docker compose --env-file ../.env up -d --build
```

Run either the root bridge or this sandbox on port 8080, not both simultaneously.

This local fixture enables signup and private-network webhooks, uses test
PostgreSQL credentials, and tracks `latest` service images.
`SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true` allows Chatwoot to reach the bridge
inside Docker; review network restrictions for public deployment.

`docker compose down` retains the data volumes. Adding `--volumes` deletes
stored conversations and other test data.

## Automated checks

From the repository root:

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
docker compose --env-file tests/.env.example -f tests/docker-compose.yml config --quiet
```
