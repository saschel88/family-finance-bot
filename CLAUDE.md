# CLAUDE.md — family-finance-bot

This file is read by Claude Code on every request.
Follow these conventions strictly and without exceptions.

---

## Project

**Name:** family-finance-bot
**Description:** A Telegram bot for family expense tracking. The user sends a photo of a receipt, the bot recognizes line items via Claude Vision API, classifies them into categories, learns from user feedback, and maintains family spending statistics.

**Bot interface language:** Russian

---

## Stack

| Layer | Technology | Version |
|---|---|---|
| Python | CPython | 3.12+ |
| Telegram | python-telegram-bot | 21.x (async) |
| Claude API | anthropic SDK | ~0.40 |
| ORM | SQLAlchemy | ~2.0 |
| Migrations | Alembic | ~1.13 |
| Database | PostgreSQL | 16 |
| Config | Pydantic Settings | ~2.5 |
| Logging | structlog | ~24.0 |
| Formatter | Black + isort | latest |
| Type checking | mypy (strict) | ~1.10 |
| HTTP client | httpx | ~0.27 |
| Containers | Docker + Docker Compose | latest |

> All versions pinned in `pyproject.toml`. Use `uv` for dependency management — faster than pip, deterministic lockfile via `uv.lock`.

---

## Dependency Management

Use **uv** (not pip, not poetry):

```bash
uv init                  # init project
uv add anthropic         # add dependency
uv add --dev pytest      # add dev dependency
uv sync                  # install from lockfile
uv run pytest            # run in venv
```

`pyproject.toml` is the single source of truth for all dependencies.
`uv.lock` must be committed to the repository.
Never use bare `pip install` in Dockerfile — use `uv sync --frozen`.

---

## Architecture

Modular monolith. Single process with clean internal layer boundaries.

```
bot/
├── handlers/       — Telegram handlers (entry point, routing only)
├── services/       — business logic (vision, classifier, reporter, exchange, nct)
├── db/
│   ├── models.py   — SQLAlchemy models
│   ├── repository/ — CRUD, one file per entity
│   └── migrations/ — Alembic migrations
├── core/
│   ├── config.py   — Pydantic Settings
│   └── logging.py  — structlog setup
└── main.py         — application entry point
```

**Dependency rule:** handlers → services → repository → models. No reverse dependencies.

---

## Data Model

### Family
```
id: int (PK)
name: str
created_at: datetime
```

### FamilyMember
```
id: int (PK)
family_id: int (FK → Family)
chat_id: int (Telegram chat_id, unique)
name: str
role: str  — "owner" | "member"
joined_at: datetime
```

### FamilyInvite
```
id: int (PK)
family_id: int (FK → Family)
token: str (uuid4, unique)
created_by: int (FK → FamilyMember)
used_by: int | None (FK → FamilyMember)
expires_at: datetime  — +24h from creation
used_at: datetime | None
```

### Receipt
```
id: int (PK)
family_member_id: int (FK → FamilyMember)
shop_name: str | None
purchased_at: datetime  — date from the receipt
total_amount: Decimal
currency: str  — "KZT" by default
photo_file_id: str  — Telegram file_id
raw_claude_json: dict  — raw Claude response (JSONB)
created_at: datetime
updated_at: datetime
```

### ReceiptItem
```
id: int (PK)
receipt_id: int (FK → Receipt)
name: str
quantity: Decimal
unit_price: Decimal
total_price: Decimal
category_id: int | None (FK → Category)
confidence: float  — 0.0–1.0
is_manual: bool  — user manually corrected the category
original_currency: str | None
original_price: Decimal | None
exchange_rate_id: int | None (FK → ExchangeRate)
nct_code: str | None  — GTIN or NTIN/KZTIN from NCT catalog
updated_at: datetime
```

### Category
```
id: int (PK)
name: str
emoji: str
parent_id: int | None (FK → Category, for subcategories — later)
is_system: bool
```

### ProductRule
```
id: int (PK)
pattern: str
category_id: int (FK → Category)
match_type: str  — "exact" | "contains" | "regex"
confidence: float
usage_count: int
created_at: datetime
```

### ExchangeRate
```
id: int (PK)
from_currency: str
to_currency: str  — always "KZT"
rate: Decimal
rate_date: date
source: str  — "nbk" | "manual"
created_at: datetime
```

### Required Database Indexes
Always define these indexes explicitly in Alembic migrations:
```
FamilyMember: chat_id (unique), family_id
Receipt: family_member_id, purchased_at
ReceiptItem: receipt_id, category_id, nct_code
ProductRule: pattern, category_id
ExchangeRate: (from_currency, rate_date) unique
FamilyInvite: token (unique)
```

---

## Code Conventions

### Typing
- Strict typing everywhere. All functions must have argument and return type annotations.
- Use `from __future__ import annotations` in every file.
- Use `X | None` for optional fields, not `Optional[X]`.
- Use `TypedDict` or Pydantic models for dicts with known structure.
- mypy runs in CI. Code is not merged if mypy fails.
- mypy config: `strict = true` in `pyproject.toml`.

### Formatting
- Black with line length 88.
- isort for import sorting (black profile).
- No `# noqa` without an explanation comment on the same line.

### Naming
- Files and folders: `snake_case`
- Classes: `PascalCase`
- Functions and variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_single_underscore`

### Async
- All code is async/await. No synchronous blocking calls in async context.
- Use async SQLAlchemy sessions for all DB operations.
- Use `httpx.AsyncClient` for HTTP requests (NBK rates, NCT API).
- Never use `asyncio.sleep` inside a handler — use `asyncio.create_task` for background work.

### Logging
- Use structlog everywhere. No `print()` or bare `logging.info()`.
- Every significant step is logged with context: `chat_id`, `receipt_id`, `member_id`.
- Levels: DEBUG for diagnostics, INFO for business events, ERROR for exceptions.

### Error Handling
- No bare `except:` or `except Exception:` without logging.
- The user always receives a clear message in Russian.
- Internal errors are fully logged (with traceback).
- Claude API errors must be caught specifically (see Claude API Error Handling section).

### Configuration
- All secrets and parameters via `.env` + Pydantic Settings.
- No hardcoded tokens, connection strings, or URLs in code.
- `.env.example` must always be up to date.

---

## Database Connection

Configure connection pooling explicitly in `core/database.py`:

```python
engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,          # verify connection before use
    pool_recycle=3600,           # recycle connections every hour
)
```

Always use async context manager for sessions:
```python
async with async_session() as session:
    async with session.begin():
        ...
```

Never share a session across handlers or store it globally.

---

## Telegram Bot State Management

Use `python-telegram-bot` `ConversationHandler` for all multi-step flows.
Store conversation state in `bot_data` (application-level) or `user_data` (per-user) — never in global variables.

Multi-step flows that require ConversationHandler:
- `/start` onboarding (new user → create family or join via invite)
- `/invite` flow (generate link → confirm send)
- Category confirmation after receipt processing (inline buttons → update item)

State constants must be defined as module-level `IntEnum` in each handler file:

```python
class OnboardingState(IntEnum):
    WAITING_NAME = 0
    WAITING_CONFIRM = 1
```

For inline button callbacks, always use `CallbackQueryHandler` with a regex pattern to route correctly.

---

## Claude API Error Handling

All calls to Anthropic API must handle these errors explicitly:

```python
import anthropic

try:
    response = await client.messages.create(...)
except anthropic.RateLimitError:
    # wait and retry with exponential backoff
except anthropic.APITimeoutError:
    # retry up to 3 times, then fail gracefully
except anthropic.APIStatusError as e:
    # log e.status_code and e.message, notify user
```

Retry strategy for Vision and Classify calls:
- Max retries: 3
- Backoff: 2s, 4s, 8s
- On final failure: save receipt as `status=failed`, notify user in Russian

Always validate Claude JSON response with Pydantic before using:
```python
class ReceiptVisionResponse(BaseModel):
    shop_name: str | None
    purchased_at: datetime | None
    currency: str = "KZT"
    total_amount: Decimal
    items: list[ReceiptItemData]
```
If validation fails — log raw response and ask user to resend photo.

---

## NCT (National Catalog of Goods) Integration

**Platform:** https://nationalcatalog.kz (production), https://stg.nct.kz (staging)
**API docs:** https://nct.kz/rest/docs and https://nationalcatalog.kz/gwp/docs
**Catalog size:** 236 categories, ~3.5 million items
**Item codes:** GTIN (international barcode), NTIN/KZTIN (national code for Kazakhstan)

### Purpose in this project
NCT is used to enrich receipt items with standardized product data and improve classification accuracy. A GTIN/KZTIN match gives a reliable category mapping without relying on fuzzy text matching.

### Classification priority (classifier.py)
```
1. NCT lookup by GTIN (from receipt barcode if available) → category
2. NCT search by product name → category (if confidence > 0.85)
3. ProductRule exact match → category
4. ProductRule contains/regex match → category
5. Claude classify → category suggestion
6. confidence < 0.7 → ask user via inline buttons
```

### services/nct.py responsibilities
- `search_by_name(name: str) -> list[NctProduct]` — search NCT by product name
- `lookup_by_gtin(gtin: str) -> NctProduct | None` — lookup by barcode
- `map_nct_category_to_local(nct_category: str) -> int | None` — map NCT category to our Category table
- Cache results in memory (TTL 24h) to avoid redundant API calls
- On NCT API unavailability — fall through to next classification step silently

### Environment variables for NCT
```env
NCT_API_BASE_URL=https://nationalcatalog.kz/gwp
NCT_API_KEY=         # if required by API
NCT_CACHE_TTL=86400  # seconds, default 24h
```

### NCT category mapping
Store NCT→local category mapping in a `nct_category_map` table or as a JSON config file.
This mapping must be editable without code changes.

---

## Environment Variables

```env
# Telegram
TELEGRAM_BOT_TOKEN=

# Anthropic
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-5

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/family_finance
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10

# NBK Exchange Rates
NBK_API_URL=https://nationalbank.kz/rss/get_rates.cfm

# NCT National Catalog
NCT_API_BASE_URL=https://nationalcatalog.kz/gwp
NCT_API_KEY=
NCT_CACHE_TTL=86400

# App
LOG_LEVEL=INFO
ENVIRONMENT=development  # development | production
```

---

## Bot Commands

```
/start                       — register, create Family or join via invite link
/invite                      — create a one-time invite link (owner only)
/report                      — current month expenses (own)
/report family               — current month expenses (whole family)
/report week                 — current week expenses
/learn <product> <category>  — force-add a classification rule
/rate <currency> <rate>      — set exchange rate manually (e.g. /rate USD 450)
/categories                  — list all categories
```

Photo of a receipt — main flow, no command needed.

---

## Receipt Processing Flow

```
1. User sends a photo
2. handlers/receipt.py — receives it, sends "обрабатываю..." message
3. services/vision.py — Claude Vision → ReceiptVisionResponse (validated Pydantic)
4. services/classifier.py — for each item:
   a. NCT lookup by GTIN (if barcode present) → category
   b. NCT search by name (confidence > 0.85) → category
   c. ProductRule exact match → category
   d. ProductRule contains/regex → category
   e. Claude classify → category suggestion
   f. confidence < 0.7 → ask user (inline buttons)
5. repository/receipt.py — save receipt and items in single transaction
6. Telegram reply — summary with items and categories
7. If uncertain items exist — inline buttons for confirmation
8. User confirms → update ReceiptItem, add ProductRule
```

---

## Graceful Shutdown

Register signal handlers in `main.py` to allow in-flight receipt processing to complete:

```python
import signal, asyncio

async def shutdown(app):
    await app.updater.stop()
    await app.stop()
    await engine.dispose()

loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(shutdown(app)))
loop.add_signal_handler(signal.SIGINT,  lambda: asyncio.create_task(shutdown(app)))
```

Docker stop sends SIGTERM — bot must handle it within 30 seconds (`stop_grace_period: 30s` in docker-compose).

---

## Default Categories (is_system=True)

Categories are aligned with OKTRU consumer goods levels. Each category stores an `oktru_code` field for NCT mapping — populated via config file `nct_category_map.json`, updatable without redeploy.

| # | User label | emoji | OKTRU basis | oktru_code |
|---|---|---|---|---|
| 1 | Продукты | 🛒 | Продукты питания и напитки | 01 |
| 2 | Кафе и рестораны | 🍕 | Услуги общественного питания | 56 |
| 3 | Аптека | 💊 | Фармацевтические товары | 21 |
| 4 | Красота и гигиена | 🧴 | Косметика и средства гигиены | 20 |
| 5 | Одежда и обувь | 👕 | Одежда, обувь и аксессуары | 14 |
| 6 | Дети | 👶 | Товары для детей | 88 |
| 7 | Дом и хозяйство | 🏠 | Товары для дома и хозяйства | 46 |
| 8 | Техника | 📱 | Бытовая техника и электроника | 26 |
| 9 | Авто | ⛽ | Автотовары и топливо | 45 |
| 10 | Образование | 🎓 | Образовательные товары и услуги | 85 |
| 11 | Развлечения | 🎭 | Досуг и развлечения | 93 |
| 12 | Путешествия | ✈️ | Транспортные услуги и туризм | 79 |
| 13 | Прочее | 💰 | — | null |

> `oktru_code` values are approximate top-level OKTRU codes. Exact codes will be refined once NCT API access is established. The mapping lives in `bot/core/nct_category_map.json` and can be updated without code changes.

---

## Claude Vision Prompt (vision.py)

Always use this system prompt when calling Claude Vision:

```
You are a receipt recognition system.
Extract all line items from the receipt and return ONLY valid JSON without markdown.

Response format:
{
  "shop_name": "store name or null",
  "purchased_at": "ISO datetime or null",
  "currency": "KZT",
  "total_amount": 0.00,
  "items": [
    {
      "name": "item name",
      "quantity": 1.0,
      "unit_price": 0.00,
      "total_price": 0.00,
      "barcode": "barcode string or null"
    }
  ]
}

Rules:
- All amounts as numbers (not strings)
- If currency is not determined — KZT
- If date is unreadable — null
- Item name — as printed on the receipt, no abbreviations
- If a barcode is visible near the item — include it in barcode field
- Return ONLY JSON, no explanations
```

---

## CI/CD Pipeline (GitHub Actions)

Pipeline runs on every push to `main` and on pull requests.

### Steps in order:
```
1. lint       — black --check + isort --check
2. typecheck  — mypy --strict
3. test       — pytest --cov --cov-fail-under=80
4. build      — docker build (verify image builds)
5. push       — push image to registry (main branch only)
6. deploy     — SSH to VPS, docker compose pull && up -d (main branch only)
```

Steps 5 and 6 run only on push to `main`, not on PRs.
If any step fails, subsequent steps are skipped.

### Required GitHub Secrets:
```
TELEGRAM_BOT_TOKEN
ANTHROPIC_API_KEY
DATABASE_URL
VPS_HOST
VPS_USER
VPS_SSH_KEY
DOCKER_REGISTRY_TOKEN
```

---

## Testing

### Coverage Requirements
- Mandatory 80% coverage for all `services/` and `repository/` modules.
- Coverage is enforced in CI — build fails if below threshold.
- Run with: `pytest --cov=bot --cov-report=term-missing --cov-fail-under=80`

### Tools
- `pytest` + `pytest-asyncio` for all async tests.
- `pytest-postgresql` for database tests (real PostgreSQL, not SQLite).
- `respx` for mocking `httpx` calls (NBK API, NCT API).
- `pytest-mock` for general mocking.

### What must be tested

`services/vision.py`
- Happy path: valid receipt image response
- Malformed JSON from Claude → raises specific exception
- Missing required fields → Pydantic ValidationError handled
- Claude API timeout → retry logic triggered

`services/classifier.py`
- NCT lookup hit → correct category assigned
- NCT lookup miss → falls through to ProductRule
- ProductRule exact match
- ProductRule contains match
- ProductRule regex match
- confidence < 0.7 → returns None (triggers user confirmation)
- All classification steps miss → Claude fallback

`services/reporter.py`
- Monthly aggregation by category
- Weekly aggregation
- own scope vs family scope
- Date boundary conditions (first/last day of month)

`services/exchange.py`
- KZT → KZT passthrough (no conversion)
- NBK rate fetch success
- NBK API unavailable → uses manual rate
- Manual rate override via /rate command

`services/nct.py`
- GTIN lookup hit and miss
- Name search with confidence threshold
- NCT API unavailable → silent fallthrough
- Cache hit (no HTTP call made)

`repository/`
- All CRUD operations per entity
- FK constraint violations handled
- Invite expiry: expired invite rejected
- Invite single-use: used invite rejected

`handlers/`
- Happy path per handler
- Error path per handler
- ConversationHandler state transitions for onboarding
- Inline button callback routing

### Test structure
```
tests/
├── conftest.py              — shared fixtures (db, bot mock, test family, test member)
├── services/
│   ├── test_vision.py
│   ├── test_classifier.py
│   ├── test_reporter.py
│   ├── test_exchange.py
│   └── test_nct.py
├── repository/
│   ├── test_receipt_repo.py
│   ├── test_member_repo.py
│   ├── test_rule_repo.py
│   └── test_invite_repo.py
└── handlers/
    ├── test_receipt_handler.py
    └── test_command_handlers.py
```

---

## Docker

### docker-compose.yml (dev)
- Services: `bot`, `postgres`
- Volumes for PostgreSQL data persistence
- `.env` file mounted automatically
- Hot reload via `watchfiles`
- `stop_grace_period: 30s` on bot service

### docker-compose.prod.yml
- No hot reload
- Restart policy: `unless-stopped`
- Logs in JSON format
- `stop_grace_period: 30s`
- Resource limits: `mem_limit: 512m`

---

## Makefile

```makefile
make dev        — start locally (docker compose up)
make test       — run tests with coverage (pytest --cov)
make lint       — black --check + isort --check + mypy
make format     — black + isort (auto-fix)
make migrate    — alembic upgrade head
make revision   — alembic revision --autogenerate
make logs       — docker compose logs -f bot
make shell      — open shell inside bot container
```

---

## What NOT to do

- Do not write business logic in handlers
- Do not make direct DB queries from handlers
- Do not store state in global variables — use ConversationHandler user_data/bot_data
- Do not use synchronous PostgreSQL drivers (psycopg2) — asyncpg only
- Do not use bare `pip install` — use `uv`
- Do not commit the `.env` file
- Do not ignore mypy errors
- Do not skip tests for new services or repositories
- Do not hardcode `latest` for dependency versions in pyproject.toml
- Do not call NCT or NBK APIs without timeout and fallback handling
