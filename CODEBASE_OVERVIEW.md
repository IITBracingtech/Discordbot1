# CODEBASE OVERVIEW — IIT Bombay Racing Discord Bot

> **Audience:** Someone joining the project for the first time with no prior context.  
> **Goal:** Understand what this bot does, how it is structured, and how all the moving parts connect.

---

## 1. What Is This Project?

This is **Race Control** — a Discord bot built for the IIT Bombay Racing Team that serves two major purposes:

1. **Task Management Sync**: Keeps tasks in a Notion database two-way synced with Discord. When a team lead creates a task in Notion, the bot automatically posts it as an embed card in a Discord channel, creates a discussion thread, schedules deadline reminders, and notifies the assignee. When a team member updates the task from Discord (via buttons/modals), the change is pushed back to Notion.

2. **Attendance Tracking**: Team members tag the bot in a Discord message (e.g., `@Race Control I'm taking a leave tomorrow, feeling sick`) and the bot uses the **Groq LLM** to understand the message, extract the date and reason, detect the person's subsystem from their Discord roles, and log the entry to the correct Google Sheets worksheet.

---

## 2. Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Language | Python | 3.12 |
| Discord framework | discord.py | ≥ 2.4.0 |
| REST API framework | FastAPI + Uvicorn | ≥ 0.111.0 / 0.30.1 |
| Database ORM | SQLAlchemy (async) | ≥ 2.0.31 |
| Database driver | asyncpg (PostgreSQL) | ≥ 0.29.0 |
| Database host | Supabase (managed PostgreSQL) | — |
| Migrations | Alembic | ≥ 1.13.1 |
| Config & validation | Pydantic / pydantic-settings | ≥ 2.7.4 / 2.3.4 |
| Notion integration | notion-client | ≥ 2.2.1 |
| Background jobs | APScheduler (AsyncIOScheduler) | ≥ 3.10.4 |
| AI / LLM | Groq AI API (OpenAI-compatible REST) | — |
| Google Sheets | gspread + google-auth | ≥ 6.0.0 / 2.0.0 |
| HTTP client | httpx (async) | — |
| Retry logic | tenacity | ≥ 8.0.0 |
| Logging | structlog | ≥ 24.2.0 |
| PDF generation | reportlab | ≥ 5.0.0 |
| Environment variables | python-dotenv | ≥ 1.0.1 |
| Deployment | Render (Docker / Procfile) | — |

---

## 3. Directory Structure

```
Discord Bot/
├── backend/                    # All application source code
│   ├── main.py                 # Entry point for running the bot directly (bot-only mode)
│   ├── config/
│   │   └── settings.py         # All env-var config via pydantic-settings (single Settings class)
│   ├── api/                    # FastAPI REST API (the process Render actually starts)
│   │   ├── main.py             # FastAPI app factory + lifespan hook that also starts the bot
│   │   ├── schemas.py          # Pydantic request/response schemas for API endpoints
│   │   └── routers/            # One file per API resource group
│   │       ├── tasks.py        # CRUD + status/progress/block endpoints for tasks
│   │       ├── projects.py     # Server, project, and channel registration endpoints
│   │       ├── assignees.py    # Discord ↔ Notion user mapping endpoints
│   │       ├── sync.py         # Trigger sync manually via HTTP
│   │       └── analytics.py    # Metrics and analytics query endpoints
│   ├── models/
│   │   └── core.py             # All SQLAlchemy ORM models (13 tables)
│   ├── database/
│   │   ├── base.py             # Declarative base for SQLAlchemy
│   │   └── session.py          # Async engine + session factory (asyncpg + Supabase URL)
│   ├── repositories/
│   │   └── base.py             # Generic async CRUD base class all repositories inherit
│   ├── services/               # External service clients (singletons)
│   │   ├── discord_client.py   # DiscordSyncBot class + global `bot` singleton
│   │   ├── notion_service.py   # Full Notion API client (read/write/schema alignment)
│   │   ├── groq_service.py     # Groq AI client + leave/late NLP parser
│   │   ├── notification_service.py  # DM + thread notification dispatching
│   │   └── analytics_service.py    # Metric aggregation over DB data
│   ├── modules/                # Discord cogs — each subfolder is a feature module
│   │   ├── attendance/         # Leave / late attendance logging via bot @mention
│   │   │   ├── commands.py     # Slash commands for attendance admin (view leaves, etc.)
│   │   │   ├── listener.py     # on_message listener: detects @mention → calls Groq → logs
│   │   │   └── sheets.py       # Google Sheets read/write layer (all 5 subsystem tabs)
│   │   ├── tasks/              # Task interaction layer (buttons, modals, slash commands)
│   │   │   ├── commands.py     # /add_task, /task_log slash commands
│   │   │   ├── listener.py     # Thread message listener (progress updates, status changes)
│   │   │   ├── buttons.py      # Persistent Discord button definitions for task cards
│   │   │   ├── modals.py       # Discord modal dialogs for task edits
│   │   │   ├── embeds.py       # All Discord embed builders (task card, reminders, etc.)
│   │   │   ├── interactions.py # Routes button click → correct modal/action
│   │   │   ├── parser.py       # Natural language parser for thread messages (progress, links)
│   │   │   └── repository.py   # Task DB queries (get, create, update, mappings, history)
│   │   ├── projects/           # Server/project/channel registration module
│   │   │   ├── commands.py     # /register_server, /add_project, /integrate_channel
│   │   │   ├── listener.py     # on_guild_join to auto-register server
│   │   │   └── repository.py   # DB queries for Server, Project, Channel, SyncState
│   │   └── settings/           # Assignee mapping and reminder settings
│   │       ├── commands.py     # /map_assignee, /view_assignees, /delete_assignee
│   │       └── repository.py   # DB queries for AssigneeMapping, Setting, Reminder
│   ├── sync/
│   │   └── sync_engine.py      # Core bidirectional Notion ↔ Discord sync orchestrator
│   ├── scheduler/
│   │   └── scheduler.py        # APScheduler: deadline reminders + daily overdue check (9 AM IST)
│   ├── utils/
│   │   ├── permissions.py      # Role-based access control decorators for slash commands
│   │   └── roster_exporter.py  # PDF/CSV roster export utility (reportlab)
│   └── shared/
│       └── __init__.py         # Placeholder for shared cross-module utilities
├── alembic/                    # Database migration management
│   ├── env.py                  # Alembic async migration environment setup
│   ├── versions/
│   │   └── 20fb8e49f18b_initial_schema.py  # Single migration creating all 13 tables
│   └── alembic.ini             # Alembic config pointing to DATABASE_URL
├── tests/                      # pytest test suite (11 test files)
│   ├── test_api.py             # FastAPI endpoint tests
│   ├── test_listener.py        # on_message / attendance listener tests
│   ├── test_parser.py          # Thread message NLP parser tests
│   ├── test_scheduler.py       # APScheduler reminder tests
│   ├── test_sync_engine.py     # Sync engine unit tests
│   ├── test_notion_service.py  # Notion API client tests
│   ├── test_notifications.py   # Notification service tests
│   ├── test_commands.py        # Slash command tests
│   ├── test_buttons_modals.py  # Button and modal tests
│   ├── test_repositories.py    # DB repository tests
│   └── test_roster_exporter.py # Roster export utility tests
├── .env                        # Local secrets (NOT committed to prod; Render has its own)
├── service_account.json        # Google Service Account credentials (NOT committed)
├── requirements.txt            # All Python dependencies with version pins
├── Dockerfile                  # Python 3.12-slim image; runs uvicorn on port 10000
├── Procfile                    # Render startup: `uvicorn backend.api.main:app`
├── docker-compose.yml          # Local Docker dev setup
├── pyproject.toml              # pytest and tool configs
└── alembic.ini                 # Alembic database URL config
```

---

## 4. Entry Points

There are **two ways** the application can start:

### Production / Render (primary)
```
Procfile → uvicorn backend.api.main:app
```
`backend/api/main.py` creates a **FastAPI** app. Its `lifespan` async context manager fires on startup and calls `asyncio.create_task(bot.start(token))` — this launches the Discord bot as a **background async task** inside the same process. Both the REST API and the Discord gateway connection run concurrently in a single uvicorn worker.

### Bot-only mode (development / direct run)
```
python -m backend.main
```
`backend/main.py` calls `asyncio.run(main())`, which directly calls `await bot.start(token)`. No FastAPI server is started.

In both cases, the **`DiscordSyncBot.setup_hook()`** is the first thing that runs after the token is accepted. It dynamically walks `backend/modules/` and loads every `commands.py` and `listener.py` as a discord.py Cog extension, so adding a new feature module requires only dropping a folder — no changes to the loader.

---

## 5. Architecture — How the Pieces Connect

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Render (Cloud Host)                           │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │              Single uvicorn Process                          │    │
│  │                                                              │    │
│  │   FastAPI REST API (backend/api/)          ─────────────►   │    │
│  │         /api/tasks, /api/sync, etc.        DB queries        │    │
│  │                                                              │    │
│  │   DiscordSyncBot (background task)                          │    │
│  │     ├── Cog: attendance/listener.py  ◄── @mention in chat   │    │
│  │     ├── Cog: tasks/listener.py       ◄── thread messages     │    │
│  │     ├── Cog: tasks/commands.py       ◄── /add_task           │    │
│  │     ├── Cog: projects/commands.py    ◄── /register_server    │    │
│  │     ├── Cog: settings/commands.py    ◄── /map_assignee       │    │
│  │     └── on_interaction handler       ◄── button clicks       │    │
│  │                                                              │    │
│  │   APScheduler (background jobs)                             │    │
│  │     ├── Deadline reminders (task-specific fire times)        │    │
│  │     └── Daily 9 AM IST overdue sweep                        │    │
│  │                                                              │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
         │               │                │              │
         ▼               ▼                ▼              ▼
   Discord Gateway   Supabase        Notion API      Google Sheets
   (WebSocket)       PostgreSQL      (REST)          (gspread)
                                          │
                                    ◄─────┘
                                SyncEngine polls
                                Notion every N min
                                (cursor-based, incremental)

  ┌─────────────────────────────────────────────────────────────────┐
  │  Groq AI API  (only used by attendance listener)                 │
  │  User @mentions bot → raw text → Groq LLM →                     │
  │  JSON: { is_attendance_request, entry_type, date, reason }       │
  └─────────────────────────────────────────────────────────────────┘
```

**Data flow for a new Notion task:**
1. Team lead creates a task page in Notion (fills Title, Assignee, Due Date, Status, Description).
2. The `SyncEngine.sync_all_channels()` job runs on a schedule; it queries the Notion database using a cursor so only recently changed pages are fetched.
3. If the page is newer than 60 seconds and has a valid title + due date, `_create_task()` is called.
4. Task is persisted to PostgreSQL. A Discord embed card is posted to the mapped channel with action buttons (Update Progress, Mark Blocked, Mark Done). 
5. The assignee is @mentioned in the card and a DM notification is sent.
6. Deadline reminder jobs are scheduled in APScheduler (3 days, 1 day, 6 hours, 1 hour, 15 min before due date).

**Data flow for an attendance leave request:**
1. Member types: `@Race Control taking leave tmr, have a test`
2. `AttendanceListenerCog.on_message()` fires; the bot mention is stripped.
3. The message is sent to `GroqService.parse_attendance_intent()` which calls Groq's API with a strict JSON system prompt. Response: `{ "is_attendance_request": true, "entry_type": "leave", "date": "2026-09-24", "reason": "have a test" }`.
4. The bot **immediately replies** to Discord before touching Sheets (fast UX).
5. A background `asyncio.create_task` then checks for duplicate entries and appends the row to the correct subsystem tab in Google Sheets.

---

## 6. Data Models

All 13 SQLAlchemy models live in [`backend/models/core.py`](backend/models/core.py). The schema is created by the single Alembic migration in `alembic/versions/`.

### Core Tables

| Table | Primary Key | Description |
|---|---|---|
| `servers` | Discord Guild ID (string) | One row per Discord server registered |
| `projects` | UUID | A named project grouping inside a server |
| `channels` | Discord Channel ID (string) | Maps a Discord text channel to a Notion database |
| `tasks` | UUID | A synced task; mirrors a Notion page |
| `message_mappings` | UUID | Links a task to its Discord embed message ID (1-to-1) |
| `thread_mappings` | UUID | Links a task to its Discord discussion thread ID (1-to-1) |
| `sync_states` | UUID | Stores Notion pagination cursor per channel; tracks IDLE/SYNCING/FAILED |
| `assignee_mappings` | UUID | Bidirectional Discord user ID ↔ Notion user name/ID mapping |
| `activity_logs` | UUID | Append-only log of every action on a task |
| `notifications` | UUID | Record of every Discord notification sent |
| `reminders` | UUID | Each deadline reminder job (SCHEDULED/SENT/CANCELLED) |
| `history` | UUID | Property-level changelog (old value → new value) for tasks |
| `settings` | UUID | Key-value store of per-server settings |
| `analytics` | UUID | Numeric metric snapshots per server |

### Key Relationships
- `Server` → many `Project` → many `Channel` → many `Task`
- `Task` → one `MessageMapping`, one `ThreadMapping`
- `Task` → many `Reminder`, `ActivityLog`, `History`, `Notification`
- `AssigneeMapping` → many `Task` (via foreign key on `tasks.assignee_id`)

### Google Sheets Schema (Attendance)
Five worksheet tabs: **Mech, Elec, DV, Ops/Marke, Creatives**

Each tab has these columns (in order):

| Column | Description |
|---|---|
| `user_id` | Discord user snowflake ID |
| `username` | Discord display name |
| `date` | Entry date in ISO format (YYYY-MM-DD) |
| `reason` | Leave/late reason string |
| `type` | `"leave"` or `"late"` |
| `total_leaves` | Running cumulative leave count (not incremented for `late` entries) |
| `created_at` | UTC ISO timestamp of when the row was written |

---

## 7. Core Logic — Module by Module

### 7.1 Attendance Module (`backend/modules/attendance/`)

**What it does:** Listens for bot @mentions in any Discord channel. Uses Groq LLM to parse the plain-English message and determine if it's a leave request or a lateness notification. Routes the entry to the correct Google Sheets subsystem tab based on the user's Discord roles.

**Key files:**
- [`listener.py`](backend/modules/attendance/listener.py) — `on_message` Cog; orchestrates the full flow
- [`sheets.py`](backend/modules/attendance/sheets.py) — All Sheets auth, worksheet caching, read/write functions
- [`commands.py`](backend/modules/attendance/commands.py) — Admin slash commands for viewing leave summaries

**Notable behaviours:**
- `detect_subsystem()` matches role names with simple substring checks (`"mech"` → Mech tab, `"elec"` → Elec tab, etc.)
- Duplicate prevention: `leave_exists()` reads all rows across all 5 tabs and checks date + user_id + type before appending
- `type = "late"` entries are written to the sheet but do NOT increment `total_leaves`
- Discord reply is sent **before** the Sheets write; the Sheets update runs as a fire-and-forget `asyncio.create_task` for instant UX

### 7.2 Sync Engine (`backend/sync/sync_engine.py`)

**What it does:** The bidirectional bridge between Notion and Discord. It is stateless — all state (cursor, last sync time) is stored in the `sync_states` DB table.

**Notion → Discord (pull loop):**
- Queries each registered Notion database using a pagination cursor so only deltas are fetched
- Compares Notion page `last_edited_time` against the local `task.last_activity` timestamp
- On new page: waits 60 seconds grace period (so a Notion user can finish filling in all fields), then creates the task in DB and posts the embed card to Discord
- On existing page, newer in Notion: runs `_detect_changes()` which returns a `ChangeSet` dataclass (deadline changed? assignee changed? status changed? reopened?). Only targeted notifications are sent — e.g., a deadline change only posts a deadline embed, not a generic "something changed" message.
- On page archived/deleted in Notion: deletes the Discord message, thread, and DB row

**Discord → Notion (push, immediate):**
- `push_task_to_notion()` is called after every button/modal action by the user
- Constructs a Notion property payload from the local task DB record and calls the Notion API

### 7.3 Notion Service (`backend/services/notion_service.py`)

**What it does:** Full async Notion API client wrapping the `notion-client` library. Handles schema alignment (Notion property keys and types differ per database), retry on 429 rate-limits, and both `database_id` / `data_source_id` API variants (Notion API compatibility issue).

**Key methods:**
- `query_database()` — paginated fetch with cursor support
- `create_page()` / `update_page_properties()` — write to Notion
- `parse_notion_properties()` — extracts a standard dict from raw Notion page JSON, handling all property types (title, rich_text, status, select, multi_select, people, date, etc.)
- `build_task_properties()` — inverse: builds Notion property payload from the standard task dict
- `_align_properties_to_schema()` — fetches the live database schema and remaps property keys + coerces value types to match (prevents API errors when schema column names vary by team)

### 7.4 Groq AI Service (`backend/services/groq_service.py`)

**What it does:** Async HTTP client for the Groq AI REST API (OpenAI-compatible). Primarily used for attendance intent parsing; also answers general questions when the bot is @mentioned with a non-attendance message.

**Key method:**
- `parse_attendance_intent(user_text)` — sends a strict system prompt instructing the model to return a raw JSON object with `is_attendance_request`, `entry_type` (`"leave"` or `"late"`), `date`, and `reason`. Handles model outputs that accidentally wrap the JSON in markdown code blocks.

### 7.5 Scheduler (`backend/scheduler/scheduler.py`)

**What it does:** Wraps APScheduler's `AsyncIOScheduler` to manage two types of jobs:
1. **Deadline reminders** — for each task with a due date, schedules reminder jobs at 3 days, 1 day, 6 hours, 1 hour, and 15 minutes before the deadline. Each job fires `send_task_reminder()` which posts an embed into the task's Discord thread and @mentions the assignee.
2. **Daily 9 AM IST sweep** — `check_overdue_tasks_9am()` finds all tasks past their due date that are still open and escalates them.

On bot startup (`on_ready`), all `SCHEDULED` reminders from the DB are reloaded into APScheduler — this ensures reminders survive bot restarts.

### 7.6 Task Interaction Layer (`backend/modules/tasks/`)

**What it does:** Everything the user interacts with in Discord around a task card.

- **`embeds.py`** — All `discord.Embed` builders (task card with status/priority/assignee/deadline, reminder embeds, status-change embeds)
- **`buttons.py`** — `TaskActionButtons` is a persistent `discord.ui.View` with buttons: Update Progress, Mark Blocked, Mark Done, View Notion, Assign. Each button's `custom_id` encodes `op_{action}:{task_id}` so it works across bot restarts.
- **`interactions.py`** — `handle_task_interaction()` routes the `custom_id` to the right modal
- **`modals.py`** — `discord.ui.Modal` subclasses for each action (progress text, block reason, completion notes). On submit, they update the DB and call `push_task_to_notion()`.
- **`listener.py`** — Watches for plain messages posted inside task discussion threads; uses `parser.py` to extract progress updates, link pastes, or status keywords from natural language
- **`parser.py`** — NLP rule-based parser that detects intent from thread messages (e.g., "done ✅" → status Done, pasted GitHub URL → add to github_links)

### 7.7 Projects & Settings Modules (`backend/modules/projects/`, `backend/modules/settings/`)

**Projects** handles server/project/channel registration via slash commands. A Discord server must be registered (`/register_server`) before channels can be mapped to Notion databases (`/integrate_channel`).

**Settings** handles the Discord-to-Notion assignee mapping table (`/map_assignee @discord_user notion_name`). This mapping is used by the sync engine to resolve Notion assignee names into Discord @mentions and vice versa.

### 7.8 REST API (`backend/api/`)

**What it does:** Provides HTTP endpoints primarily for a potential web dashboard or external automation to read/write task data and trigger sync.

**Routers:**
- `tasks.py` — CRUD for tasks; status/progress/block/complete update endpoints
- `projects.py` — Register server, project, channel; list all
- `assignees.py` — Create/list/delete assignee mappings
- `sync.py` — `POST /api/sync/{channel_id}` triggers a manual sync for one channel
- `analytics.py` — Query aggregated metrics

The bot runs in the same process as the FastAPI server (started in the `lifespan` hook) so both share the same DB session factory and `bot` object.

---

## 8. External Dependencies & Environment Variables

### Required Services

| Service | Purpose | How authenticated |
|---|---|---|
| **Discord** | Bot gateway + message sending | `DISCORD_BOT_TOKEN` in .env / Render |
| **Supabase PostgreSQL** | Persistent storage for all tasks, mappings, reminders | `DATABASE_URL` (asyncpg connection string) |
| **Notion** | Source of truth for task data | `NOTION_BOT_TOKEN` |
| **Groq AI** | LLM for attendance message parsing | `GROQ_API_KEY` |
| **Google Sheets** | Attendance log storage (5 subsystem tabs) | `service_account.json` (Service Account key file) OR `GOOGLE_SERVICE_ACCOUNT_JSON` (JSON string for Render) |

### Full `.env` Variables

| Variable | Description |
|---|---|
| `ENV` | `development` / `production` (affects log format and command sync behaviour) |
| `DATABASE_URL` | asyncpg PostgreSQL URL (Supabase) |
| `DISCORD_BOT_TOKEN` / `DISCORD_TOKEN` | Bot token (aliased) |
| `DISCORD_GUILD_ID` / `GUILD_ID` | Target guild ID for slash command sync in dev |
| `NOTION_BOT_TOKEN` | Notion internal integration token |
| `GROQ_API_KEY` | Groq API key |
| `GROQ_MODEL` | Model name (default: `openai/gpt-oss-120b`) |
| `GROQ_BASE_URL` | API endpoint (default: `https://api.groq.com/openai/v1`) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Path to `service_account.json` (local) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON string of service account (Render env var) |
| `SPREADSHEET_ID` / `GOOGLE_SHEET_ID` | Google Sheets spreadsheet ID |
| `ATTENDANCE_ADMIN_CHANNEL_ID` | Discord channel ID for attendance admin notifications |
| `ALERT_ROLE_ID` | Discord role ID to ping for leave alerts (optional) |
| `ATTENDANCE_DAILY_CHECK_HOUR` | Hour (24h IST) for daily overdue check cron (default: 9) |
| `TIMEZONE` | Timezone for scheduler (default: `Asia/Kolkata`) |
| `LOG_LEVEL` | Logging level (default: `INFO`) |

---

## 9. Known Complexity & Gotchas

### Dynamic Cog Loading
`DiscordSyncBot._load_module_cogs()` auto-discovers modules by walking the `backend/modules/` directory. Any new module folder with a `commands.py` or `listener.py` is automatically loaded as a Cog — no import needed anywhere. This is clean but means a syntax error in any module file crashes the entire bot load.

### Dual API Compatibility in Notion Service
Notion's Python client has two API variants for databases: `client.databases` (official) and `client.data_sources` (newer internal). Many methods in `notion_service.py` try one variant and fall back to the other with a `try/except` block. This is a workaround for inconsistent Notion API responses and should be cleaned up once the API stabilises.

### Schema Alignment on Every Write
`_align_properties_to_schema()` fetches the live Notion database schema before every write to coerce property names and types. This adds one extra Notion API call per update but prevents hard-to-debug `validation_error` failures when different Notion databases have slightly different column naming conventions.

### Google Sheets Auth Priority
`_get_client()` in `sheets.py` tries three authentication methods in order:
1. `GOOGLE_SERVICE_ACCOUNT_JSON` env var (a JSON string — used on Render)
2. `GOOGLE_SERVICE_ACCOUNT_FILE` file path (local `service_account.json`)
3. OAuth `credentials.json` + cached `token.json` (legacy, expires every 7 days unless the app is published)

For production on Render, method 1 is used. For local dev, method 2 is used.

### 60-Second Grace Buffer on New Tasks
When the sync engine sees a brand-new Notion page, it waits until the page is at least 60 seconds old before creating the Discord card. This prevents half-filled task cards from being posted while a team lead is still typing into Notion fields.

### Hardcoded Server ID in `resolve_task_assignee_mention`
In `sync_engine.py` at `resolve_task_assignee_mention()`, there is a fallback hardcoded server ID `"1530289513635512411"`. This is a known TODO — it should be dynamically resolved from the DB, but was left as a quick fix and has not been updated.

### Attendance Uses `leave_date` Key in Old Records
Some older Google Sheets records use `leave_date` as the column name instead of `date`. The `leave_exists()` and `get_weekly_leave_counts()` functions check both `r.get("date")` and `r.get("leave_date")` to handle backwards compatibility.

### Late Entries Don't Increment Leave Count
`add_attendance_entry()` checks `entry_type == "late"` and skips the increment of `total_leaves`. The running total is computed live each time by scanning all prior rows, not by reading the last value in the column — so the count is always accurate even if rows were manually edited.

### Bot + API in One Process
On Render, `uvicorn` starts FastAPI and the Discord bot runs as a background `asyncio.create_task`. This means a bot crash (e.g., gateway disconnect) does not crash the REST API, but a fatal Python exception in the main event loop could affect both. The architecture trades deployment simplicity (one Render service, one dyno) for some resilience risk.

### Worksheet Cache
`_subsystem_worksheets` in `sheets.py` is a module-level dict cached for the bot's lifetime. If someone renames a worksheet tab in Google Sheets while the bot is running, the cache becomes stale and writes will fail silently until the bot restarts.
