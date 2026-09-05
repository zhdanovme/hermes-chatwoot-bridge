# Hermes ↔ Chatwoot bridge

Локальный bridge превращает Hermes Agent в Chatwoot AgentBot: входящее сообщение
из Chatwoot уходит в Hermes, а ответ Hermes создаётся в той же conversation.
Контекст хранится на стороне Hermes в именованной `conversation`, поэтому разные
диалоги изолированы друг от друга.

## Запуск

```bash
cp .env.example .env
docker compose up -d
docker compose logs -f bridge hermes
```

Открыть Chatwoot: http://localhost:3000.

Compose автоматически копирует `config/hermes.yaml` в volume Hermes через
одноразовый сервис `hermes-config`. Его состояние `Exited (0)` после запуска —
нормальное: основной сервис `hermes` стартует только после успешной инициализации.

Перед первым диалогом нужно один раз:

1. Создать локального администратора Chatwoot.
2. Создать Website inbox в Chatwoot (Settings → Inboxes → Add inbox → Website) и
   скопировать его `Website token` в `CHATWOOT_WEBSITE_TOKEN`.
3. В Chatwoot создать Agent Bot с `outgoing_url`:
   `http://bridge:8080/webhooks/chatwoot` и типом `Webhook`.
4. Привязать Agent Bot к нужному inbox.
5. Добавить нужных операторов в этот inbox, иначе они не увидят его conversations
   в интерфейсе Chatwoot.
6. Создать API access token пользователя Chatwoot и записать его в `CHATWOOT_API_TOKEN`.
7. Если у Agent Bot задан secret, записать его в `CHATWOOT_WEBHOOK_SECRET`.
8. Настроить провайдера Hermes: передать `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` в `.env`
   или выполнить `docker compose exec hermes hermes setup --portal`.

После изменения `.env`:

```bash
docker compose up -d --build
curl http://localhost:8080/healthz
```

Ожидаемый health-ответ:

```json
{"status":"ok","configured":true}
```

Для теста через встроенный веб-чат откройте http://localhost:8080/demo. Страница
подгрузит Chatwoot Web Widget, а сообщения попадут в тот же inbox и пройдут через
Agent Bot → Hermes → ответ в conversation.

> `SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true` включён в Chatwoot только для этой
> локальной Compose-сборки, чтобы AgentBot мог вызвать `http://bridge:8080` во
> внутренней Docker-сети. Не переносите эту настройку в публичный production без
> отдельной оценки SSRF-риска и сетевых ограничений.

## Контракт bridge

Bridge принимает Chatwoot AgentBot webhook `message_created`. Обрабатываются только
публичные входящие сообщения (`message_type=incoming`, `private=false`). Исходящие
сообщения Hermes и private notes игнорируются, чтобы не создавать цикл.

Для каждой Chatwoot conversation используется отдельная Hermes conversation:

```text
hermes:{chatwoot_account_id}:{chatwoot_conversation_id}
```

Доставка идемпотентна по Chatwoot message id. Hermes ошибки возвращаются как `500`,
чтобы Chatwoot мог повторить webhook; bridge не отправляет выдуманный fallback-ответ.

API-сессии Hermes работают без инструментов. Bridge явно отправляет `tools: []`, а
`config/hermes.yaml` задаёт `platform_toolsets.api_server: []`, поэтому ответы могут
опираться только на `config/employee.md`, метаданные контакта и историю текущей
conversation. Файлы, terminal, web, skills, memory и другие встроенные инструменты
на API-поверхности недоступны. Эта настройка не отключает инструменты в прямом CLI
Hermes.

## Проверка без внешнего канала

После создания inbox и Agent Bot можно отправить тестовый webhook напрямую:

```bash
curl -X POST http://localhost:8080/webhooks/chatwoot \
  -H 'Content-Type: application/json' \
  -d '{"event":"message_created","id":1,"message_type":"incoming","private":false,"content":"Привет","account":{"id":1},"conversation":{"id":1},"sender":{"id":1,"name":"Тест"},"inbox":{"id":1,"name":"Local"}}'
```

Для этого smoke-теста подпись отключена только если `CHATWOOT_WEBHOOK_SECRET` пуст.

## Что сознательно не входит сейчас

Telegram user-account/MTProto и Wazzup оставлены на следующий этап. Их следует
подключать отдельными transport-адаптерами, не смешивая их с текущей Chatwoot ↔ Hermes
сессией и не подключая один почтовый ящик одновременно к Chatwoot и Hermes IMAP.
# hermes-chatwoot-bridge
