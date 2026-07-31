# 🏎️ RaceControl — Enterprise Discord ↔ Notion Synchronization Platform

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg?style=for-the-badge&logo=python)](https://www.python.org/)
[![Discord.py](https://img.shields.io/badge/discord.py-v2.4%2B-5865F2.svg?style=for-the-badge&logo=discord)](https://discordpy.readthedocs.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-v0.111%2B-009688.svg?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Notion API](https://img.shields.io/badge/Notion%20API-v2.2%2B-000000.svg?style=for-the-badge&logo=notion)](https://developers.notion.com/)
[![Supabase PostgreSQL](https://img.shields.io/badge/Supabase-PostgreSQL%2015%2B-3ECF8E.svg?style=for-the-badge&logo=supabase)](https://supabase.com/)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg?style=for-the-badge&logo=docker)](https://www.docker.com/)
[![Render Deployed](https://img.shields.io/badge/Render-24%2F7%20Free%20Tier-46E3B7.svg?style=for-the-badge&logo=render)](https://render.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

> **RaceControl** is a bi-directional task management engine designed for high-performance engineering teams, Formula Student racing organizations, and fast-paced tech startups. It syncs tasks between **Notion** databases and **Discord** channels with multi-assignee tagging, automated deadline reminders, natural language status updates, thread discussion sync, and analytics.

---

## 📌 Table of Contents

- [🏎️ RaceControl — Enterprise Discord ↔ Notion Synchronization Platform](#️-racecontrol--enterprise-discord--notion-synchronization-platform)
  - [📌 Table of Contents](#-table-of-contents)
  - [🚀 Executive Overview](#-executive-overview)
  - [✨ Features](#-features)
  - [🏗️ System Architecture](#️-system-architecture)
  - [🔄 System Workflow](#-system-workflow)
  - [💻 Tech Stack](#-tech-stack)
  - [📁 Folder Structure](#-folder-structure)
  - [📋 Prerequisites](#-prerequisites)
  - [🤖 Discord Bot Setup](#-discord-bot-setup)
  - [🛡️ Discord Permissions Matrix](#️-discord-permissions-matrix)
  - [📝 Notion Integration Setup](#-notion-integration-setup)
  - [📊 Notion Database Schema](#-notion-database-schema)
  - [👥 Assignee Mapping \& Mentions](#-assignee-mapping--mentions)
  - [⚡ Supabase Database Setup](#-supabase-database-setup)
  - [🔐 Environment Variables](#-environment-variables)
  - [💻 Local Development Guide](#-local-development-guide)
  - [☁️ Render 24/7 Free Deployment](#️-render-247-free-deployment)
  - [🐳 Docker Deployment](#-docker-deployment)
  - [🔑 GitHub Secrets Configuration](#-github-secrets-configuration)
  - [🔄 CI/CD Pipeline](#-cicd-pipeline)
  - [🤖 Bot Workflow](#-bot-workflow)
  - [🔔 Notification Workflow](#-notification-workflow)
  - [⏰ Deadline Reminder System](#-deadline-reminder-system)
  - [🧠 Smart Message Parsing Engine](#-smart-message-parsing-engine)
  - [📁 File Upload \& Link Attachment Handling](#-file-upload--link-attachment-handling)
  - [🌐 REST API Documentation](#-rest-api-documentation)
  - [🗄️ Database Schema \& ER Diagram](#️-database-schema--er-diagram)
  - [📜 Logging System](#-logging-system)
  - [🚨 Error Handling \& Diagnostics](#-error-handling--diagnostics)
  - [🔧 Troubleshooting Checklist](#-troubleshooting-checklist)
  - [❓ Frequently Asked Questions (FAQ)](#-frequently-asked-questions-faq)
  - [🔒 Security Policy](#-security-policy)
  - [🗺️ Future Roadmap](#️-future-roadmap)
  - [🤝 Contributing Guidelines](#-contributing-guidelines)
  - [📄 License](#-license)
  - [👏 Credits](#-credits)

---

## 🚀 Executive Overview

In engineering and formula student teams, project managers write tasks in Notion while sub-system engineers work daily in Discord. Context switching leads to stale Notion boards, forgotten deadlines, and missed handoffs.

**RaceControl** solves this completely:
1. Team leads create tasks in Notion.
2. **RaceControl** automatically creates visual Task Cards in dedicated Discord project channels (`#powertrain`, `#aerodynamics`, `#chassis`) with multi-assignee tags.
3. Members interact via Discord buttons (`▶️ Start`, `📝 Update Progress`, `✅ Submit`) or type updates directly into dedicated Discord task discussion threads.
4. **RaceControl** parses natural language messages, extracts Google Drive / GitHub links, updates Notion in real-time, and schedules deadline reminders.

> [!NOTE]
> Engineers **never need to open Notion** to view or update tasks. Everything happens directly inside Discord.

---

## ✨ Features

### 🔄 Automatic Bidirectional Task Synchronization
- Polls Notion databases every 30 seconds for newly created, edited, or deleted pages.
- Instantly creates, updates, or purges matching task embed cards in Discord text channels.
- When tasks are deleted or archived in Notion, **RaceControl** automatically purges the corresponding Discord messages, discussion threads, and PostgreSQL records.

### 🏷️ Multi-Member Assignee Tagging
- Assign tasks to single or multiple team members in Notion.
- **RaceControl** maps Notion assignees (`Srikar`, `Narayana Malla`) to Discord user IDs (`<@123456789>`, `<@987654321>`).
- Discord embed cards mention every tagged assignee directly in the embed header.
- Modals and button interactions preserve all multi-assignee mentions without overwriting Notion tags.

### ⏰ Intelligent Deadline Reminders & Tiered Escalation
- Calculates precise deadline triggers based on target due dates (3 Days, 1 Day, 6 Hours, 1 Hour, 15 Minutes, and Deadline).
- Automatically converts UTC timestamps into `Asia/Kolkata` (IST) format for deadline displays.
- Displays human-readable date-only deadlines (`⏰ Due Today`, `⏰ Due Tomorrow`, `⏰ Due 31 Jul 2026`).
- **Tiered Overdue Escalation Sweep** runs daily at 9:00 AM IST:
  - **Day 1 Overdue**: Pings Assignee in task thread.
  - **Day 2 Overdue**: Pings Assignee + CCs Sub-Team Lead / Task Creator.
  - **Day 3+ Overdue**: Pings Assignee + CCs Sub-Team Lead + Escalates to Manager (`@role_manager_id`).

### 💬 Auto-Created Discussion Threads
- Automatically creates a dedicated Discord discussion thread for every task card (`💬 task-title`).
- Posts a pinned welcome embed explaining thread commands and workflow.
- Any message, status update, link, or attachment posted inside the thread automatically syncs back to Notion.
- Automatically archives threads upon task completion and purges them after 24 hours.

### 🧠 Smart Natural Language Message Parser
- Automatically parses thread replies for status changes and completion notes:
  - Keywords: `started`, `working on`, `in progress` $\rightarrow$ Status set to `In Progress`.
  - Keywords: `completed`, `done`, `finished` $\rightarrow$ Status set to `Done`.
  - Keywords: `blocked`, `stuck`, `waiting on` $\rightarrow$ Status set to `Blocked` with reason recorded.
- Automatically extracts URLs: Google Drive, GitHub PRs/issues, Figma, Dropbox, OneDrive.

### 📊 Real-Time Analytics & Operations Reports
- **Daily Morning Briefing (9:00 AM IST)**: Overview of tasks due today and pending items sent to project channels.
- **Daily Evening Debrief (7:00 PM IST)**: Summary of completed tasks and active blockers.
- **Weekly Analytics Report (Sunday 9:00 AM IST)**: Team completion efficiency metrics.
- **Monthly Analytics Report (1st of Month 9:00 AM IST)**: Sub-team performance breakdowns.

---

## 🏗️ System Architecture

The following diagram illustrates the flow of data through **RaceControl**:

```mermaid
flowchart TD
    subgraph ExternalServices ["External Services"]
        N[Notion Workspace / DB]
        D[Discord Guild / Channels]
    end
    subgraph CoreSystem ["RaceControl Core Platform"]
        SE[Sync Engine - 30s Polling]
        DB[(Supabase / PostgreSQL 15)]
        PE[Natural Language Parser]
        SCH[APScheduler Engine]
        API[FastAPI REST Server]
        DIS[Discord.py Bot Gateway]
    end

    %% Sync Flow
    N -->|Poll Pages & Properties| SE
    SE -->|Upsert Task Models| DB
    SE -->|Dispatch Card Embeds & Threads| DIS
    DIS -->|Render Embed Cards| D

    %% User Interaction Flow
    D -->|Button Clicks / Thread Messages| DIS
    DIS -->|Extract Text & Links| PE
    PE -->|Update Task State| DB
    PE -->|Push Page Properties| N

    %% Scheduler & Escalation Flow
    SCH -->|Trigger Reminders & 9 AM Sweep| DB
    SCH -->|Dispatch Notifications| DIS
    API -->|Health & Management Endpoints| CoreSystem
```

---

## 🔄 System Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Lead as Team Manager
    participant N as Notion DB
    participant SE as Sync Engine
    participant DB as Supabase DB
    participant D as Discord Channel
    actor Dev as Engineer

    Lead->>N: Create/Update Task Page
    SE->>N: Poll Database (Every 30s)
    N-->>SE: Return Page Properties & Multi-Assignees
    SE->>DB: Upsert Task & Assignee Mappings
    SE->>D: Post Task Card Embed & Create Thread
    D-->>Dev: Ping Tagged Assignees (<@User1> <@User2>)
    Dev->>D: Click "Start Task" or Type Update in Thread
    D->>SE: Interaction Event Received
    SE->>DB: Update Task Status to "In Progress"
    SE->>N: Push Status Update to Notion
    SE->>D: Update Embed Status Badge to 🟡 In Progress
```

---

## 💻 Tech Stack

| Component | Technology | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Language** | Python | `3.12+` | Core asynchronous runtime |
| **Bot Framework** | `discord.py` | `2.4.0+` | Gateway connection, interactions, slash commands |
| **Web Server** | FastAPI / Uvicorn | `0.111.0+` | Healthcheck endpoints & REST API |
| **Database** | Supabase (PostgreSQL) | `15.0+` | Relational storage for task mappings & state |
| **ORM** | SQLAlchemy (AsyncIO) | `2.0.31+` | Asynchronous database operations |
| **Migrations** | Alembic | `1.13.1+` | Database schema migrations |
| **Scheduler** | APScheduler | `3.10.4+` | Cron sweeps & deadline reminder triggers |
| **Notion SDK** | `notion-client` | `2.2.1+` | Async Notion REST API integration |
| **Logging** | `structlog` | `24.2.0+` | Structured JSON & console log formatting |
| **Testing** | `pytest` / `pytest-asyncio` | `9.1.1+` | Asynchronous unit and integration test suite |
| **Containerization** | Docker | `3.12-slim` | Production container runtime |
| **Hosting** | Render Web Service | Free Tier | 24/7 hosting with keep-alive self-ping |

---

## 📁 Folder Structure

```text
RaceControl/
├── backend/
│   ├── api/
│   │   ├── main.py                  # FastAPI server application & bot lifespan
│   │   └── routers/                 # REST API endpoints (tasks, projects, sync)
│   ├── config/
│   │   └── settings.py              # Pydantic environment configuration
│   ├── database/
│   │   ├── base.py                  # Declarative base model
│   │   └── session.py               # Async SQLAlchemy engine & session factory
│   ├── models/
│   │   └── core.py                  # SQLAlchemy ORM models (Task, Channel, etc.)
│   ├── modules/
│   │   ├── projects/                # Project & channel mapping modules
│   │   ├── settings/                # Assignee & role settings repositories
│   │   └── tasks/                   # Tasks cog, embeds, modals, & interactions
│   │       ├── commands.py          # Slash commands (/link_assignee, etc.)
│   │       ├── embeds.py            # Discord Embed card generators
│   │       ├── interactions.py      # Button click handlers
│   │       ├── listener.py          # Message thread listener
│   │       ├── modals.py            # Progress & completion popups
│   │       ├── parser.py            # Natural language message parser
│   │       └── repository.py        # Task database repository
│   ├── scheduler/
│   │   └── scheduler.py             # APScheduler deadline & keep-alive engine
│   ├── services/
│   │   ├── analytics_service.py     # Analytical report generation
│   │   ├── discord_client.py        # Custom Discord Bot client setup
│   │   ├── notification_service.py  # Daily briefings & debriefs
│   │   └── notion_service.py        # Async Notion API integration wrapper
│   ├── sync/
│   │   └── sync_engine.py           # Bidirectional sync engine logic
│   └── utils/
│       └── permissions.py           # Operations role permission checks
├── tests/                           # 127+ Automated unit & integration tests
├── Dockerfile                       # Multi-stage production Docker container definition
├── Procfile                         # Web service process launcher for Render / Koyeb
├── requirements.txt                 # Clean PyPI frozen production dependencies
├── pyproject.toml                   # Pytest & tool configurations
└── README.md                        # Exhaustive project documentation
```

---

## 📋 Prerequisites

Before installing **RaceControl**, ensure you have accounts and access for the following services:

1. **Python `3.12` or higher** installed on your host machine.
2. **Discord Account** with administrator access to your target server.
3. **Discord Developer Portal Access** to register a Bot Application.
4. **Notion Workspace** (Admin access to create Integrations and share databases).
5. **Supabase Account** (or any PostgreSQL 15+ database).
6. **GitHub Account** (For source control and deployment).
7. **Render Account** (For free 24/7 cloud hosting).

---

## 🤖 Discord Bot Setup

Follow these step-by-step instructions to create and configure your Discord Bot from scratch.

### Step 1: Create a Discord Application
1. Navigate to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** in the top right corner.
3. Name your application `RaceControl` and accept the Developer Terms.

![Developer Portal Application Setup](assets/images/setup-1.png)

### Step 2: Create Bot & Enable Privileged Intents
1. In the left navigation sidebar, click **Bot**.
2. Click **Reset Token** to generate a new bot token. Copy this token immediately and store it securely (This is your `DISCORD_BOT_TOKEN`).
3. Scroll down to the **Privileged Gateway Intents** section.
4. Enable the following three intents (CRITICAL):
   - ✅ **Presence Intent**
   - ✅ **Server Members Intent**
   - ✅ **Message Content Intent**
5. Click **Save Changes**.

> [!WARNING]
> If **Message Content Intent** is disabled, the bot will not be able to parse text updates or link uploads in discussion threads!

![Privileged Gateway Intents](assets/images/setup-2.png)

### Step 3: Configure OAuth2 & Bot Permissions
1. In the left navigation sidebar, click **OAuth2** $\rightarrow$ **URL Generator**.
2. Under **Scopes**, check:
   - ✅ `bot`
   - ✅ `applications.commands`
3. Under **Bot Permissions**, check:
   - ✅ `Send Messages`
   - ✅ `Create Public Threads`
   - ✅ `Send Messages in Threads`
   - ✅ `Embed Links`
   - ✅ `Attach Files`
   - ✅ `Read Message History`
   - ✅ `Manage Messages`
   - ✅ `Manage Threads`
   - ✅ `Use Slash Commands`
4. Copy the generated **OAuth2 URL** at the bottom of the page.

![OAuth2 URL Generator](assets/images/setup-3.png)

### Step 4: Invite Bot to Your Server
1. Paste the generated OAuth2 URL into your browser address bar.
2. Select your target Discord server from the dropdown menu.
3. Click **Authorize** and complete the CAPTCHA.

### Step 5: Enable Developer Mode & Copy IDs
1. Open your Discord App settings $\rightarrow$ **Advanced**.
2. Toggle **Developer Mode** to `ON`.
3. Right-click your Discord server name in the left sidebar $\rightarrow$ click **Copy Server ID** (This is your `GUILD_ID`).
4. Right-click any target text channel (e.g. `#powertrain`) $\rightarrow$ click **Copy Channel ID** (This is your `CHANNEL_ID`).

![Copy Discord IDs](assets/images/setup-4.png)

---

## 🛡️ Discord Permissions Matrix

| Permission Name | Required Scope | Why It Is Needed | Consequence If Missing |
| :--- | :--- | :--- | :--- |
| **Send Messages** | Text Channels | Posting task embed cards into project channels | Bot cannot post initial task cards |
| **Create Public Threads** | Text Channels | Creating dedicated discussion threads for tasks | Task threads fail to launch |
| **Send Messages in Threads**| Task Threads | Posting progress updates and reminders inside threads | Assignees receive no thread reminders |
| **Embed Links** | Embeds | Formatting task cards, progress bars, and footers | Embed cards revert to plain raw text |
| **Attach Files** | Threads | Uploading attached files and progress media to Notion | Attachment sync fails silently |
| **Read Message History** | Text/Threads | Reading thread replies to parse natural language updates | Auto-status updates do not function |
| **Manage Messages** | Text Channels | Cleaning up obsolete embeds when tasks are deleted | Deleted Notion tasks leave ghost embeds |
| **Manage Threads** | Text Channels | Archiving and deleting completed discussion threads | Channels clutter with archived threads |
| **Use Slash Commands** | Application | Executing `/link_assignee` and `/project_setup` commands | Slash commands return error responses |

---

## 📝 Notion Integration Setup

### Step 1: Create an Internal Integration
1. Go to [Notion Integrations](https://www.notion.com/my-integrations).
2. Click **+ New integration**.
3. Set **Associated workspace** to your team workspace.
4. Name the integration `RaceControl Sync`.
5. Under **Capabilities**, ensure the following are enabled:
   - ✅ Read content
   - ✅ Update content
   - ✅ Insert content
   - ✅ Read user information (without email addresses)
6. Click **Save** $\rightarrow$ Copy the **Internal Integration Secret** (This is your `NOTION_API_KEY`).

![Notion Integration Setup](assets/images/setup-5.png)

### Step 2: Connect Integration to Database
1. Open your Notion Task Database page (e.g. `Tasks` or `Test2`).
2. Click the `...` menu icon in the top right corner of Notion.
3. Scroll down and click **+ Add connections**.
4. Search for `RaceControl Sync` and click **Confirm**.

![Connect Integration to Database](assets/images/setup-6.png)

### Step 3: Extract Notion Database ID
1. Open your Notion database as a full page.
2. Examine the browser URL:
   `https://www.notion.so/myworkspace/3ad580cfdec880fe932a000b811f5bcf?v=...`
3. The 32-character hexadecimal string between the slash `/` and the `?v=` is your **Notion Database ID**:
   `3ad580cf-dec8-80fe-932a-000b811f5bcf`

---

## 📊 Notion Database Schema

Ensure your Notion Database includes the following property columns with exact names and property types:

| Property Name | Notion Type | Description / Purpose | Supported Values |
| :--- | :--- | :--- | :--- |
| **Task Name** | Title | The main title of the task | Plain text string |
| **Description** | Rich Text | Comprehensive task instructions | Multi-line text format |
| **Status** | Status / Select | Current state of task execution | `Not Started`, `In Progress`, `Blocked`, `Done` |
| **Assigned to** | Multi-select / Person | Assigned team members | Notion User names or multi-select tags |
| **Assigned By** | Select | Member who created or assigned task | Lead name or user display name |
| **Due Date** | Date | Deadline for task completion | ISO Date (`YYYY-MM-DD`) |
| **Progress Summary**| Rich Text | Latest progress update note | Log text updated by Discord interactions |
| **Completion Summary**| Rich Text | Final completion summary | Text submitted upon task completion |
| **Blocked Reason** | Rich Text | Detail explaining why task is stuck | Text entered when task is marked blocked |
| **Drive Links** | Url / Rich Text | Attached Google Drive folder or files | Google Drive URLs |
| **GitHub Links** | Url / Rich Text | Related GitHub pull request or issue | GitHub repository URLs |
| **Created Time** | Created Time | Automatic creation timestamp | ISO Timestamp |
| **Updated By** | Rich Text | Name of member who last edited card | Discord display name |

---

## 👥 Assignee Mapping & Mentions

**RaceControl** maps Notion user names to Discord user IDs so team members get tagged directly on Discord embed cards (`<@Srikar> <@Narayana Malla>`).

### Executing the `/link_assignee` Slash Command
Run this command in Discord to register a member mapping:

```text
/link_assignee notion_name:Srikar discord_user:@Srikar
```

```mermaid
flowchart LR
    N_User["Notion Assignee Tag: 'Srikar'"] -->|Query AssigneeMapping DB| MapTable["assignee_mappings Table"]
    MapTable -->|Resolve Discord User ID| D_User["Discord User ID: '123456789012345678'"]
    D_User -->|Render Embed Mention| Card["Discord Embed: <@123456789012345678>"]
```

---

## ⚡ Supabase Database Setup

### Step 1: Create Supabase Project
1. Log into your [Supabase Dashboard](https://database.new).
2. Click **New Project**.
3. Select your Organization, name your project `racecontrol-db`, and set a secure **Database Password**.
4. Choose the region closest to your server (e.g. `ap-south-1` for Mumbai / India).
5. Click **Create new project**.

![Supabase Project Creation](assets/images/setup-7.png)

### Step 2: Retrieve API Keys & Connection String
1. In your Supabase dashboard sidebar, navigate to **Project Settings** $\rightarrow$ **API**.
2. Copy the **Project URL** (This is your `SUPABASE_URL`).
3. Copy the **service_role secret key** (This is your `SUPABASE_SERVICE_ROLE_KEY`).
4. Navigate to **Project Settings** $\rightarrow$ **Database**.
5. Under **Connection String**, select **URI** and copy the PostgreSQL connection URL:
   `postgresql://postgres:[YOUR-PASSWORD]@db.xxxxxx.supabase.co:5432/postgres`

---

## 🔐 Environment Variables

Create a `.env` file in the project root directory containing the following environment keys:

```ini
# Environment Scoping
ENV=production
LOG_LEVEL=INFO
TIMEZONE=Asia/Kolkata

# Discord Application Credentials
DISCORD_BOT_TOKEN=MTUzMDI5MjE3NDA5NTEyNjY1OA.Xxxxx.YYYYYYy-zzzzzzz
GUILD_ID=1530289513635512411

# Notion API Credentials
NOTION_API_KEY=secret_abc123xyz45678901234567890
NOTION_DATABASE_ID=3ad580cf-dec8-80fe-932a-000b811f5bcf

# Supabase / PostgreSQL Credentials
SUPABASE_URL=https://xxxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
DATABASE_URL=postgresql+asyncpg://postgres:YourPassword@db.xxxxxx.supabase.co:5432/postgres

# Operations Role Escalation (Discord Role ID for Manager)
ROLE_MANAGER_ID=1530289513635512412

# Sync Configuration
POLL_INTERVAL=30
RENDER_EXTERNAL_URL=https://racingteam-bot-1.onrender.com
```

| Variable Name | Required | Default | Purpose / Explanation |
| :--- | :---: | :--- | :--- |
| `ENV` | Yes | `development` | Scopes logging format and slash command auto-sync |
| `LOG_LEVEL` | No | `INFO` | Structlog verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `TIMEZONE` | No | `Asia/Kolkata` | Timezone for deadline displays and reports |
| `DISCORD_BOT_TOKEN` | **Yes** | — | Authentication token from Discord Developer Portal |
| `GUILD_ID` | **Yes** | — | Target Discord Server ID for command registration |
| `NOTION_API_KEY` | **Yes** | — | Integration Secret key from Notion Developers |
| `NOTION_DATABASE_ID` | **Yes** | — | 32-character ID of connected Notion Database |
| `DATABASE_URL` | **Yes** | — | Async SQLAlchemy PostgreSQL connection string |
| `POLL_INTERVAL` | No | `30` | Interval in seconds between Notion sync sweeps |
| `RENDER_EXTERNAL_URL` | No | — | Public URL of web service used for 10m keep-alive ping |

---

## 💻 Local Development Guide

### Step 1: Clone Repository & Create Virtual Environment
```bash
# Clone the repository
git clone https://github.com/narayanamalla/RacingTeam-Bot-1.git
cd RacingTeam-Bot-1

# Create virtual environment with Python 3.12+
python3 -m venv .venv

# Activate virtual environment
# On macOS / Linux:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Configure Local Environment
Copy `.env.example` to `.env` and fill in your credential keys:
```bash
cp .env.example .env
```

### Step 4: Run Database Migrations
```bash
alembic upgrade head
```

### Step 5: Execute Automated Test Suite
```bash
pytest
```

### Step 6: Start Bot Runner & API Server
```bash
# Option A: Start Discord Bot Runner directly
python -m backend.main

# Option B: Start FastAPI Web Server with Bot background task
uvicorn backend.api.main:app --reload --port 8000
```

---

## ☁️ Render 24/7 Free Deployment

Deploy **RaceControl** on Render Web Services for **100% free 24/7 uptime**.

### Step 1: Connect GitHub Repository
1. Log into your [Render Dashboard](https://dashboard.render.com).
2. Click **New +** $\rightarrow$ **Web Service**.
3. Connect your GitHub account and select repository `narayanamalla/RacingTeam-Bot-1`.

![Render New Web Service](assets/images/setup-8.png)

### Step 2: Configure Service Settings
- **Name**: `RacingTeam-Bot-1`
- **Region**: Singapore / Frankfurt
- **Branch**: `main`
- **Runtime**: `Docker`
- **Instance Type**: `Free` ($0/month)

![Render Deployment Configuration](assets/images/setup-9.png)

### Step 3: Add Environment Variables
Scroll down to **Environment Variables** and add all values from your `.env` file (`DISCORD_BOT_TOKEN`, `NOTION_API_KEY`, `DATABASE_URL`, `RENDER_EXTERNAL_URL`, etc.).

### Step 4: Deploy & Verify
Click **Create Web Service**. Render will build the Docker container and launch Uvicorn on `$PORT`.

> [!TIP]
> **RaceControl** includes an automated 10-minute self-ping background job (`keep_alive_ping`) that pings `https://racingteam-bot-1.onrender.com/health`. This prevents Render's free instance from sleeping!

---

## 🐳 Docker Deployment

### Building & Running with Docker
```bash
# Build Docker image
docker build -t racecontrol-bot .

# Run Docker container
docker run -d \
  --name racecontrol-instance \
  -p 10000:10000 \
  --env-file .env \
  racecontrol-bot
```

### Running with Docker Compose
Use the following `docker-compose.yml`:

```yaml
version: '3.8'

services:
  racecontrol:
    build: .
    container_name: racecontrol_bot
    restart: always
    ports:
      - "10000:10000"
    env_file:
      - .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:10000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

Launch with:
```bash
docker-compose up -d --build
```

---

## 🔑 GitHub Secrets Configuration

When setting up GitHub Actions CI/CD pipelines, populate the following repository secrets under **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions**:

- `DISCORD_BOT_TOKEN`
- `NOTION_API_KEY`
- `NOTION_DATABASE_ID`
- `DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `RENDER_DEPLOY_HOOK_URL`

---

## 🔄 CI/CD Pipeline

The `.github/workflows/ci-cd.yml` workflow automatically runs on every push to `main`:

```mermaid
flowchart LR
    Push["Git Push to main"] --> Checkout["Checkout Repository"]
    Checkout --> SetupPy["Setup Python 3.12"]
    SetupPy --> InstDeps["Install PyPI Dependencies"]
    InstDeps --> RunLinter["Run Flake8 / Black Check"]
    RunLinter --> RunPytest["Run 127 Pytest Suite"]
    RunPytest -->|Tests Pass| TriggerDeploy["Trigger Render Deploy Hook"]
```

---

## 🤖 Bot Workflow

```mermaid
flowchart TD
    A["Manager creates page in Notion"] -->|Notion API| B["Sync Engine (30s interval)"]
    B -->|Check DB| C{"Task exists in Supabase?"}
    C -- No --> D["Post Task Card Embed & Create Thread"]
    C -- Yes --> E["Update Existing Embed Card"]
    D --> F["Tag Assignees (<@Srikar> <@Narayana>)"]
    F --> G["Schedule Deadline Reminders"]
    G --> H["Member Clicks 'Start Task'"]
    H --> I["Update Discord Card to 🟡 In Progress"]
    I --> J["Push 'In Progress' to Notion"]
```

---

## 🔔 Notification Workflow

```mermaid
stateDiagram-v2
    [*] --> Created: Notion Page Added
    Created --> Assigned: Task Card Posted & Members Tagged
    Assigned --> InProgress: Member Clicks Start
    InProgress --> Reminder3Day: 3 Days Before Due Date
    InProgress --> Reminder1Day: 1 Day Before Due Date
    InProgress --> Deadline: Deadline Trigger
    Deadline --> OverdueDay1: Past Due Date (Day 1)
    OverdueDay1 --> OverdueDay2: Day 2 Escalation (Ping Lead)
    OverdueDay2 --> OverdueDay3: Day 3+ Escalation (Ping Manager)
    InProgress --> Completed: Member Clicks Submit
    Completed --> [*]: Thread Archived & Scheduled for 24h Purge
```

---

## ⏰ Deadline Reminder System

| Interval | Trigger Time | Target Audience | Action Taken |
| :--- | :--- | :--- | :--- |
| **3 Days** | `due_date - 3 days` | Tagged Assignees | Thread reminder embed posted |
| **1 Day** | `due_date - 1 day` | Tagged Assignees | Urgent thread reminder posted |
| **6 Hours** | `due_date - 6 hours` | Tagged Assignees | High priority alert posted |
| **1 Hour** | `due_date - 1 hour` | Tagged Assignees | Final countdown alert posted |
| **15 Mins** | `due_date - 15 mins` | Tagged Assignees | Immediate deadline warning |
| **Deadline**| `due_date` | Tagged Assignees | Deadline reached alert |
| **Overdue D1**| `due_date + 1 day` | Tagged Assignees | Overdue warning posted |
| **Overdue D2**| `due_date + 2 days` | Assignee + Task Creator | Escalation to sub-team lead |
| **Overdue D3+**| `due_date + 3 days` | Assignee + Creator + Manager | Formal escalation to Manager Role |

---

## 🧠 Smart Message Parsing Engine

The natural language parser (`backend/modules/tasks/parser.py`) converts thread chat replies into task properties automatically:

```text
User in Thread: "I have started working on the powertrain CAD model. Drive link: https://drive.google.com/drive/folders/1abc..."
↓
Parsed Properties:
- Status: "In Progress"
- Drive Links: ["https://drive.google.com/drive/folders/1abc..."]
- Progress Summary: "I have started working on the powertrain CAD model."
```

### Recognized Keyword Rules:
- **Start**: `started`, `starting`, `wip`, `in progress`, `working on`
- **Completion**: `completed`, `done`, `finished`, `resolved`, `ready for review`
- **Blocked**: `blocked`, `stuck`, `waiting for`, `issue with`, `cannot proceed`

---

## 📁 File Upload & Link Attachment Handling

**RaceControl** extracts and syncs media links posted inside Discord channels or task threads directly to Notion database columns:

| Link / File Type | Extracted Pattern | Notion Target Property | Display Format |
| :--- | :--- | :--- | :--- |
| **Google Drive** | `drive.google.com` | `Drive Links` | `[Drive 1](url)` link button |
| **GitHub PR / Issue**| `github.com/.../pull/...` | `GitHub Links` | `[GitHub 1](url)` link button |
| **Figma Files** | `figma.com/file/...` | `Attachments` | Clickable Figma Link |
| **Discord Attachments**| Image / PDF / CAD / ZIP | `Attachments` | Uploaded File URL |

---

## 🌐 REST API Documentation

FastAPI provides an interactive OpenAPI documentation endpoint at `http://localhost:10000/docs`.

### Key Endpoints:

#### 1. Health Check
- **`GET /health`**
- **Response `200 OK`**:
```json
{
  "status": "healthy",
  "bot_connected": true,
  "bot_latency": 0.042,
  "environment": "production"
}
```

#### 2. Trigger Notion Sync Sweep
- **`POST /api/sync/trigger`**
- **Response `200 OK`**:
```json
{
  "status": "success",
  "synced_channels": 3,
  "tasks_updated": 5
}
```

#### 3. Assignee Mappings
- **`GET /api/assignees`**: List registered user mappings.
- **`POST /api/assignees`**: Create new mapping.

---

## 🗄️ Database Schema & ER Diagram

```mermaid
erdiagram
    PROJECTS ||--o{ CHANNELS : contains
    CHANNELS ||--o{ TASKS : hosts
    TASKS ||--o{ MESSAGE_MAPPINGS : embeds
    TASKS ||--o{ THREAD_MAPPINGS : threads
    TASKS ||--o{ REMINDERS : triggers
    TASKS }o--|| ASSIGNEE_MAPPINGS : assigned_to

    PROJECTS {
        uuid id PK
        string server_id
        string name
        datetime created_at
    }

    CHANNELS {
        uuid id PK
        uuid project_id FK
        string discord_channel_id
        string notion_database_id
        datetime created_at
    }

    TASKS {
        uuid id PK
        string channel_id
        string notion_page_id
        string title
        string description
        string status
        datetime due_date
        uuid assignee_id FK
        text progress_summary
        text completion_summary
        text blocked_reason
        datetime created_at
    }

    ASSIGNEE_MAPPINGS {
        uuid id PK
        string server_id
        string discord_user_id
        string notion_user_id
        string display_name
    }

    REMINDERS {
        uuid id PK
        uuid task_id FK
        datetime trigger_time
        string reminder_type
        string status
    }
```

---

## 📜 Logging System

**RaceControl** utilizes `structlog` for structured logging:

```json
{"event": "Task created successfully", "task_id": "3ad580cf", "title": "Design Front Wing", "level": "info", "timestamp": "2026-07-30T14:20:00Z"}
{"event": "Notion API rate limit hit, backoff 2s", "level": "warning", "timestamp": "2026-07-30T14:21:05Z"}
```

---

## 🚨 Error Handling & Diagnostics

| Common Symptom | Root Cause | Solution |
| :--- | :--- | :--- |
| `discord.errors.LoginFailure` | `DISCORD_BOT_TOKEN` is invalid or expired | Reset token in Developer Portal and update `.env` |
| `APIResponseError: 404` | Notion Database not shared with Integration | Open Notion DB $\rightarrow$ `...` $\rightarrow$ Add `RaceControl Sync` connection |
| `sqlalchemy.exc.OperationalError` | Supabase DB connection string incorrect | Verify password and host in `DATABASE_URL` |
| `MissingGreenlet` | SQLAlchemy async relationship accessed lazily | Execute explicit `select()` queries for relationships |
| `No open ports detected` | Service running `backend.main` instead of `uvicorn` | Ensure `Dockerfile` CMD launches `uvicorn backend.api.main:app` |

---

## 🔧 Troubleshooting Checklist

- [ ] Discord Bot Token copied correctly without trailing spaces.
- [ ] All 3 Privileged Gateway Intents enabled in Developer Portal.
- [ ] Notion Integration Secret added to database connection menu.
- [ ] Notion Database ID set to exact 32-character string.
- [ ] Supabase connection string uses `postgresql+asyncpg://`.
- [ ] Render environment variables populated matching `.env`.

---

## ❓ Frequently Asked Questions (FAQ)

<details>
<summary><b>1. Is RaceControl free to host 24/7?</b></summary>
Yes! RaceControl includes an automated keep-alive self-ping feature that pings Render every 10 minutes, keeping your web service awake 24/7 on Render's free tier.
</details>

<details>
<summary><b>2. How fast do Notion task updates sync to Discord?</b></summary>
Synchronization sweeps run automatically every 30 seconds.
</details>

<details>
<summary><b>3. Can I tag multiple members in a single task?</b></summary>
Yes! Multi-assignee support allows you to tag multiple people in Notion, and all members will be mentioned on Discord.
</details>

<details>
<summary><b>4. What happens if I delete a task in Notion?</b></summary>
RaceControl automatically detects deleted/trashed Notion pages, purges the corresponding embed card from Discord, deletes the discussion thread, and cleans up database records.
</details>

<details>
<summary><b>5. Does RaceControl support multiple sub-team channels?</b></summary>
Yes! You can map different Notion databases to different Discord channels (e.g. `#powertrain`, `#aerodynamics`, `#electronics`).
</details>

<details>
<summary><b>6. Do engineers need a Notion account to use this?</b></summary>
No. Engineers can perform all task operations directly inside Discord via buttons and thread replies.
</details>

<details>
<summary><b>7. How are overdue tasks handled?</b></summary>
Overdue tasks undergo a 3-tier escalation sweep daily at 9:00 AM IST, notifying assignees, leads, and managers.
</details>

<details>
<summary><b>8. Can I attach Google Drive links directly in Discord?</b></summary>
Yes! Simply post any Google Drive URL in the task thread and RaceControl will update Notion's Drive Links field.
</details>

<details>
<summary><b>9. What database does RaceControl use?</b></summary>
RaceControl uses PostgreSQL 15+ (hosted via Supabase or local Docker).
</details>

<details>
<summary><b>10. How do slash commands get registered?</b></summary>
Slash commands are synced automatically to your target Discord server (`GUILD_ID`) on startup.
</details>

<details>
<summary><b>11. Can I run RaceControl using Docker Compose?</b></summary>
Yes, a ready-to-use `docker-compose.yml` configuration is provided in the documentation.
</details>

<details>
<summary><b>12. What happens if Notion API hits a rate limit?</b></summary>
RaceControl features exponential backoff retry logic to handle Notion rate limits gracefully.
</details>

<details>
<summary><b>13. Is the deadline display customizable?</b></summary>
Deadlines are cleanly formatted in IST (`Asia/Kolkata`) with date-only displays (`Due Today`, `Due Tomorrow`, `Due 31 Jul 2026`).
</details>

<details>
<summary><b>14. Can I customize the daily briefing times?</b></summary>
Yes, briefing cron times can be configured in `backend/scheduler/scheduler.py`.
</details>

<details>
<summary><b>15. What happens if the bot loses internet connection?</b></summary>
Upon reconnecting, APScheduler automatically reloads all active reminders from PostgreSQL.
</details>

<details>
<summary><b>16. How does assignee mapping work?</b></summary>
Use the `/link_assignee` slash command in Discord to pair Notion display names with Discord user IDs.
</details>

<details>
<summary><b>17. Can I host this on AWS or DigitalOcean?</b></summary>
Yes! Any cloud platform supporting Docker or Python 3.12 can run RaceControl.
</details>

<details>
<summary><b>18. Are task threads deleted after completion?</b></summary>
Completed task threads are archived immediately and purged automatically after 24 hours.
</details>

<details>
<summary><b>19. How do I run the automated test suite?</b></summary>
Execute `pytest` in your terminal to run all 127+ automated unit and integration tests.
</details>

<details>
<summary><b>20. Does RaceControl support dark mode embeds?</b></summary>
Discord embeds dynamically update color codes based on status (Grey for Not Started, Gold for In Progress, Red for Blocked, Green for Done).
</details>

<details>
<summary><b>21. Is my Notion Integration Secret safe?</b></summary>
Yes. All credentials are isolated in environment variables and never logged or exposed.
</details>

<details>
<summary><b>22. Can I use SQLite for local testing?</b></summary>
Yes, `aiosqlite` is included for lightweight local unit testing.
</details>

<details>
<summary><b>23. What permissions does the Discord Bot require?</b></summary>
The bot requires standard message, thread management, embed, and slash command permissions as detailed in the permission matrix.
</details>

<details>
<summary><b>24. How do I assign a Manager role for escalations?</b></summary>
Set `ROLE_MANAGER_ID` in your `.env` file to your team's Discord Manager role ID.
</details>

<details>
<summary><b>25. How do button interactions stay persistent across bot restarts?</b></summary>
Button interactions use structured `custom_id` strings (`op_start:<task_id>`) handled globally by `on_interaction`.
</details>

<details>
<summary><b>26. Can I add custom status values to Notion?</b></summary>
Yes, maps are configured in `backend/modules/tasks/embeds.py`.
</details>

<details>
<summary><b>27. Does RaceControl support GitHub repository links?</b></summary>
Yes! GitHub PR and issue links posted in task threads automatically populate the `GitHub Links` Notion property.
</details>

<details>
<summary><b>28. How do I inspect live deployment logs on Render?</b></summary>
Log into Render Dashboard $\rightarrow$ select `RacingTeam-Bot-1` $\rightarrow$ click **Logs**.
</details>

<details>
<summary><b>29. What is the memory footprint of RaceControl?</b></summary>
RaceControl consumes under 150MB of RAM, making it optimal for free container instances.
</details>

<details>
<summary><b>30. How do I contribute new features to the project?</b></summary>
Fork the repository, create a feature branch, ensure `pytest` passes, and submit a Pull Request!
</details>

---

## 🔒 Security Policy

- **Environment Isolation**: Secrets are stored strictly in `.env` variables and never committed to source control.
- **Least Privilege Access**: Discord Bot permissions are scoped exclusively to required channel operations.
- **Async SQL Injection Prevention**: All database queries use SQLAlchemy parameter binding.

---

## 🗺️ Future Roadmap

- [ ] **Web Dashboard**: React-based dashboard for team leads to visualize live task analytics.
- [ ] **Recruitment Module**: Automated candidate tracking and interview scheduling.
- [ ] **Inventory & Component Tracker**: Formula Student parts inventory management.
- [ ] **Sponsor CRM Sync**: Notion-to-Discord sponsor outreach pipeline.

---

## 🤝 Contributing Guidelines

1. **Fork the Repository** on GitHub.
2. **Create a Feature Branch**: `git checkout -b feature/amazing-feature`
3. **Commit your changes**: `git commit -m "Add amazing feature"`
4. **Run Tests**: Ensure all tests pass with `pytest`.
5. **Push Branch**: `git push origin feature/amazing-feature`
6. **Open a Pull Request**.

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.

---

## 👏 Credits

Developed with ❤️ by **IIT Bombay Racing**.
Special thanks to the open-source communities behind `discord.py`, `FastAPI`, `Notion SDK`, and `Supabase`.
