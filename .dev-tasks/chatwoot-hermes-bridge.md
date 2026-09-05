# Chatwoot ↔ Hermes bridge

## Change contract

- Outcome: a local Compose stack exposes Chatwoot and a bridge that turns a Chatwoot AgentBot webhook into an autonomous Hermes reply.
- Invariants: incoming messages only trigger Hermes; outgoing bot messages do not loop; every Chatwoot conversation maps to one stable Hermes named conversation; failures are visible and do not produce a fabricated reply; webhook signatures can be enforced; API-server sessions expose zero tools and can answer only from their system prompt and isolated conversation history.
- Scope: Chatwoot AgentBot webhook, Hermes Responses API, Chatwoot outgoing message API, local Compose wiring, tests and setup documentation.
- Non-goals: Telegram MTProto, Wazzup, production deployment, CRM tools, and bulk outbound campaigns.

## 1. Minimal Reasonable Solution

1. Implement a small async FastAPI bridge with health, AgentBot webhook, Hermes client, and Chatwoot client.
2. Derive `hermes:{account_id}:{conversation_id}` as the stable Hermes `conversation` value.
3. Accept Chatwoot `message_created` payloads only when `message_type=incoming` and `private=false`; post the generated text to the source conversation as an outgoing Chatwoot message.
4. Add HMAC verification for Chatwoot's `X-Chatwoot-Timestamp`/`X-Chatwoot-Signature` headers, configurable for local development.
5. Add Docker Compose services for Postgres, Redis, Chatwoot, Hermes, and the bridge, with an `.env.example` and setup/run documentation.
6. Configure `platform_toolsets.api_server` as an explicit empty list and send an empty Responses API `tools` list, leaving non-API Hermes surfaces unaffected.

## 2. Matrix Decisions on Complications

| Complication | Options | Decision | Rationale and Cost |
| --- | --- | --- | --- |
| Hermes context continuity | Full history in Chat Completions; Responses `conversation`; private Hermes gateway session | Named Responses conversation | Hermes persists context server-side and bridge only stores deterministic mapping; requires Hermes API server. |
| Chatwoot integration surface | Account webhook; AgentBot outgoing webhook; API Inbox webhook | AgentBot outgoing webhook | Native Chatwoot bot lifecycle and per-inbox assignment; no broad account webhook filtering required. |
| Duplicate delivery | In-memory set; durable store; rely on Chatwoot | Request delivery/message ID with bounded SQLite ledger | Safe across bridge restarts without adding a database service; small local operational cost. |
| Hermes unavailable | Return error; post fallback text; queue | Return 500 and let Chatwoot retry; no fake reply | Preserves correctness and Chatwoot's AgentBot retry behavior. |
| Disable API tools | Empty request `tools`; empty API platform toolsets; both | Both | Request-level `tools` covers client-provided functions; platform toolsets are the authoritative gate for Hermes built-ins. |

## 3. Refactoring Options

| Option | Value | Cost and Risk | Decision |
| --- | --- | --- | --- |
| Add a generic provider adapter interface now | Easier Wazzup/MTProto later | More abstractions before the current path is proven | Defer |
| Add durable outbox/worker queue | Better production retry semantics | Requires another persistence/worker design | Defer; current bridge uses idempotency and HTTP retry boundaries |
| Add Chatwoot API client and Hermes client modules | Keeps transport logic testable and focused | A few small modules | Include |

## 4. Test Coverage Plan

| Behavior or Risk | Test or Check | Level |
| --- | --- | --- |
| Stable per-conversation Hermes key | Pure mapping tests | Unit |
| Ignore outgoing/private/non-message events | Webhook endpoint tests | Integration |
| Correct Hermes request and response extraction | Mock HTTP transport tests | Unit |
| Correct Chatwoot outgoing API request | Mock HTTP transport tests | Unit |
| HMAC acceptance/rejection and timestamp tolerance | Signature tests | Unit |
| Duplicate delivery does not call Hermes twice | Webhook tests | Integration |
| Container configuration and health endpoints | Compose config validation and smoke curl | Static/Runtime |
| API sessions expose no client or built-in tools | Request payload assertion, parsed Hermes config assertion, adversarial live request, and session DB inspection | Unit/Runtime |

Deviation log: none.
