# Tasks

- [x] Python Project Initialization & Dependency Setup
- [x] Database Connection & Session Management
- [x] SQLAlchemy Declarative Base & Models Configuration
  - [x] Guild / Server model
  - [x] Project model
  - [x] Channel model
  - [x] Task model
  - [x] Message Mapping model
  - [x] Thread Mapping model
  - [x] Sync State model
  - [x] Assignee Mapping model
  - [x] Activity Log model
  - [x] Notification model
  - [x] Reminder model
  - [x] History model
  - [x] Settings model
  - [x] Analytics model
- [x] Base Repository Interface & Concrete Implementations
- [x] Alembic Migration Setup
- [x] Repository Verification & Unit Test Framework Setup

- [x] Discord Bot Core Setup
  - [x] Set up bot configuration & discord.py client initialization
  - [x] Implement dynamic module commands extension loader
  - [x] Define command permissions dynamic decorators (Supabase settings backed)
  - [x] Implement Task Commands (`/task` CRUD stubs)
  - [x] Implement Project Commands (`/project`, `/channel_config` stubs)
  - [x] Implement Assignee Commands (`/link_assignee`, `/assignees` stubs)
  - [x] Implement Sync & Settings Commands (`/sync`, `/settings` stubs)
  - [x] Implement Help Command (`/help` dynamically customized by role)
  - [x] Create `main.py` entrypoint and bot CLI runner
  - [x] Verify bot starts and registers slash commands

- [x] Notion Integration Setup
  - [x] Set up async Notion API Client service (`backend/services/notion_service.py`)
  - [x] Design Notion property mappings matching all task attributes (Task, Description, Status, Priority, Assignee, Due Date, Drive Links, GitHub Links, etc.)
  - [x] Implement robust Notion API exception handling, retries, and rate limit backoff
  - [x] Add query database, retrieve page, create page, and update page methods
  - [x] Write integration/mock verification tests for the Notion service

- [x] Bidirectional Sync Engine Setup
  - [x] Implement incremental sync loop for fetching Notion updates (`backend/sync/sync_engine.py`)
  - [x] Implement conflict resolution rules (last-write-wins based on updated_at/last_edited_time)
  - [x] Implement Discord message/embed state updater
  - [x] Implement Discord-to-Notion push hooks
  - [x] Handle deleted items (Notion pages deleted or Discord threads archived/deleted)
  - [x] Log sync history, errors, and update `sync_states` table
  - [x] Write tests verifying sync flow, mapping updates, and conflict scenarios

- [x] Reminder Scheduler Setup
  - [x] Configure persistent scheduler using `APScheduler` and SQLAlchemy JobStore (`backend/scheduler/scheduler.py`)
  - [x] Implement scheduling routine for deadline intervals (3d, 1d, 6h, 1h, 15m, at deadline)
  - [x] Implement daily 9 AM IST morning overdue reminders routine
  - [x] Implement startup recovery logic reloading active reminders from Supabase on restart
  - [x] Write scheduler tests verifying job persistence and triggers

- [x] Notification System & Daily Reports
  - [x] Implement event-based notification dispatcher service (`backend/services/notification_service.py`)
  - [x] Configure real-time alerts for Task Created, Assigned, Status Changes, Priority Changes, and Deadlines
  - [x] Design formatting for Morning Daily Reports (9 AM IST: Due Today, Overdue, Completed Yesterday, High Priority, Blocked Tasks)
  - [x] Design formatting for Evening Reports (7 PM IST: Completed Today, Ongoing, Blocked, Completion %)
  - [x] Register report schedules in APScheduler
  - [x] Write verification tests for notifications and reports logic

- [x] Task Threads & Completion Workflow
  - [x] Implement Task Buttons persistent view logic (`backend/modules/tasks/buttons.py`)
  - [x] Implement Interactive Task Completion modal (`backend/modules/tasks/modals.py`)
  - [x] Integrate file/document attachments and link upload parser within task completion workflow
  - [x] Hook completion submission to update Supabase local state, commit to Notion, save change history, and dispatch notification alerts
  - [x] Write integration tests verifying buttons interactions and modals submission sequence
