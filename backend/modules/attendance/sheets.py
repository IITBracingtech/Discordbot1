"""
Google Sheets storage layer for the Attendance module in Discordbot1.

Handles Service Account / OAuth auth, worksheet caching, tenacity retries,
and all read/write operations for 5 subsystem tabs:
  - Mech
  - Elec
  - DV
  - Ops/Marke
  - Creatives
"""

import os
import discord
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, date, timedelta, timezone

import gspread
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.config.settings import settings

logger = structlog.get_logger(__name__)

# ── Subsystem definitions ───────────────────────────────────────────────────
SUBSYSTEM_TABS = ["Mech", "Elec", "DV", "Ops/Marke", "Creatives"]
LEAVES_HEADERS = ["user_id", "username", "date", "reason", "type", "total_leaves", "created_at"]

# ── Worksheet cache (module-level singletons) ────────────────────────────────
_gc: gspread.Client | None = None
_subsystem_worksheets: dict[str, gspread.Worksheet] = {}

# ── Retry decorator for transient Sheets API errors ──────────────────────────
_sheet_retry = retry(
    retry=retry_if_exception_type(gspread.exceptions.APIError),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)


# ── Role Detection Helper ────────────────────────────────────────────────────

def detect_subsystem(roles: Sequence[discord.Role] | list[str]) -> str | None:
    """
    Detect user's subsystem from their Discord roles.
    Matches:
      - Mech: 'mech', 'mechanical'
      - Elec: 'elec', 'electrical'
      - DV: 'dv', 'driverless'
      - Ops/Marke: 'ops', 'marke', 'operation', 'marketing'
      - Creatives: 'creative'
    Returns tab name string or None if unassigned.
    """
    role_names = [r.name.lower() if isinstance(r, discord.Role) else str(r).lower() for r in roles]

    for r in role_names:
        if "mech" in r or "mechanical" in r:
            return "Mech"
        if "elec" in r or "electrical" in r:
            return "Elec"
        if "dv" in r or "driverless" in r:
            return "DV"
        if any(k in r for k in ["ops", "marke", "operation", "marketing"]):
            return "Ops/Marke"
        if "creative" in r:
            return "Creatives"

    return None


def is_sheets_configured() -> bool:
    """Return True if both Google Sheet ID and Service Account / OAuth credentials are set."""
    has_sheet_id = bool(getattr(settings, "SPREADSHEET_ID", "") or getattr(settings, "GOOGLE_SHEET_ID", ""))
    has_creds = bool(
        getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")
        or getattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE", "")
        or (getattr(settings, "GOOGLE_CLIENT_ID", "") and getattr(settings, "GOOGLE_CLIENT_SECRET", ""))
    )
    return has_sheet_id and has_creds


def _get_client() -> gspread.Client:
    global _gc
    if _gc is not None:
        return _gc

    # 1. Service Account JSON string from environment
    if getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", None):
        import json
        info = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
        _gc = gspread.service_account_from_dict(info)
        logger.info("Authenticated via Service Account JSON env var")

    # 2. Service Account file path
    elif getattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE", None):
        sa_path = settings.GOOGLE_SERVICE_ACCOUNT_FILE
        if not os.path.isabs(sa_path):
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            sa_path = os.path.join(root_dir, sa_path)

        if os.path.exists(sa_path):
            _gc = gspread.service_account(filename=sa_path)
            logger.info("Authenticated via Service Account file", path=sa_path)
        else:
            logger.warning("GOOGLE_SERVICE_ACCOUNT_FILE path does not exist", path=sa_path)

    # 3. Google OAuth credentials
    elif getattr(settings, "GOOGLE_CLIENT_ID", None) and getattr(settings, "GOOGLE_CLIENT_SECRET", None):
        import json
        config_dir = os.path.expanduser("~/.config/gspread")
        os.makedirs(config_dir, exist_ok=True)
        creds_path = os.path.join(config_dir, "credentials.json")

        credentials = {
            "installed": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uris": ["http://localhost"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        with open(creds_path, "w") as f:
            json.dump(credentials, f)

        _gc = gspread.oauth(credentials_filename=creds_path)
        logger.info("Authenticated via OAuth (token cached to ~/.config/gspread/)")

    else:
        raise RuntimeError("No valid Google credentials configured in environment variables.")

    return _gc


# ── Worksheet initialisation ──────────────────────────────────────────────────

def _get_sheet_id() -> str:
    sheet_id = getattr(settings, "SPREADSHEET_ID", "") or getattr(settings, "GOOGLE_SHEET_ID", "")
    if not sheet_id:
        raise RuntimeError("Neither SPREADSHEET_ID nor GOOGLE_SHEET_ID is configured in environment.")
    return sheet_id


def _get_subsystem_sheets() -> dict[str, gspread.Worksheet]:
    """Return dict mapping subsystem tab name -> Worksheet, creating tabs if missing and ensuring updated headers."""
    global _subsystem_worksheets

    if len(_subsystem_worksheets) == len(SUBSYSTEM_TABS):
        return _subsystem_worksheets

    gc = _get_client()
    sheet_id = _get_sheet_id()

    sh = gc.open_by_key(sheet_id)
    existing = {ws.title for ws in sh.worksheets()}

    for tab in SUBSYSTEM_TABS:
        if tab not in _subsystem_worksheets:
            if tab not in existing:
                ws = sh.add_worksheet(title=tab, rows=2000, cols=7)
                ws.append_row(LEAVES_HEADERS, value_input_option="RAW")
                logger.info("Created subsystem worksheet", tab=tab)
            else:
                ws = sh.worksheet(tab)
                # Ensure row 1 header is updated to new schema
                try:
                    current_headers = ws.row_values(1)
                    if current_headers != LEAVES_HEADERS:
                        ws.update('A1:G1', [LEAVES_HEADERS])
                        logger.info("Updated worksheet header schema", tab=tab)
                except Exception as e:
                    logger.warning("Could not verify/update sheet headers", tab=tab, error=str(e))
            _subsystem_worksheets[tab] = ws

    logger.info("Subsystem worksheets ready", sheet_id=sheet_id, tabs=SUBSYSTEM_TABS)
    return _subsystem_worksheets


def init_sheets() -> None:
    """Ensure connection and all 5 subsystem tab headers exist. Call on bot startup."""
    _get_subsystem_sheets()


# ── Low-level retried I/O ─────────────────────────────────────────────────────

@_sheet_retry
def _read_all_subsystem_leaves() -> list[dict]:
    """Read all leave/late records across all 5 subsystem worksheets."""
    sheets = _get_subsystem_sheets()
    all_records = []
    for tab_name, ws in sheets.items():
        records = ws.get_all_records()
        for r in records:
            r["_subsystem"] = tab_name
        all_records.extend(records)
    return all_records


@_sheet_retry
def _append_subsystem_leave(tab_name: str, row: list) -> None:
    """Append an entry row to the designated subsystem worksheet."""
    sheets = _get_subsystem_sheets()
    ws = sheets.get(tab_name)
    if not ws:
        raise ValueError(f"Invalid subsystem tab: '{tab_name}'")
    ws.append_row(row, value_input_option="RAW")


# ── Public helpers — Leaves & Cumulative Counters ─────────────────────────────

def get_user_total_leaves(user_id: str) -> int:
    """Calculate cumulative total leaves logged by user_id across all subsystem tabs (excluding 'late' entries)."""
    all_records = _read_all_subsystem_leaves()
    return sum(
        1 for r in all_records
        if str(r.get("user_id", "")) == user_id and str(r.get("type", "leave")).lower() != "late"
    )


def leave_exists(user_id: str, leave_date: date, entry_type: str = "leave") -> bool:
    """Return True if the user already has a leave/late entry for this exact date in any subsystem tab."""
    target = leave_date.isoformat()
    all_records = _read_all_subsystem_leaves()
    entry_type_clean = entry_type.lower()
    return any(
        str(r.get("user_id", "")) == user_id
        and (str(r.get("date", "")) == target or str(r.get("leave_date", "")) == target)
        and str(r.get("type", "leave")).lower() == entry_type_clean
        for r in all_records
    )


def add_attendance_entry(user_id: str, username: str, entry_date: date, reason: str, subsystem: str, entry_type: str = "leave") -> int:
    """
    Log a leave or late entry to the user's subsystem worksheet.
    If entry_type is 'leave', increments cumulative total leaves.
    If entry_type is 'late', does NOT increment total leaves.
    Returns the current total leaves count for this user.
    """
    entry_type_clean = entry_type.lower()
    past_total = get_user_total_leaves(user_id)
    if entry_type_clean == "late":
        new_total = past_total
    else:
        new_total = past_total + 1

    _append_subsystem_leave(subsystem, [
        user_id,
        username,
        entry_date.isoformat(),
        reason,
        entry_type_clean,
        new_total,
        datetime.now(timezone.utc).isoformat(),
    ])
    logger.info(
        "Attendance entry recorded in subsystem tab",
        user_id=user_id,
        username=username,
        date=str(entry_date),
        subsystem=subsystem,
        type=entry_type_clean,
        total_leaves=new_total
    )
    return new_total


# Alias for backward compatibility
add_leave = add_attendance_entry


# ── Commented Out — Late & AlertsSent Operations ─────────────────────────────
"""
def late_exists(user_id: str, late_date: date) -> bool:
    pass

def add_late(user_id: str, username: str, late_date: date, reason: str) -> None:
    pass

def already_alerted(user_id: str, week_start: date) -> bool:
    pass

def mark_alerted(user_id: str, username: str, week_start: date) -> None:
    pass
"""


# ── Public helpers — Weekly logic ─────────────────────────────────────────────

def get_week_bounds(ref: date) -> tuple[date, date]:
    week_start = ref - timedelta(days=ref.weekday())   # Monday
    week_end   = week_start + timedelta(days=6)         # Sunday
    return week_start, week_end


def get_weekly_leave_counts(week_start: date, week_end: date) -> list[dict]:
    """Return [{user_id, username, day_count, subsystem}] for users with leaves in the given Mon–Sun week."""
    ws_str, we_str = week_start.isoformat(), week_end.isoformat()
    user_dates: defaultdict[str, set] = defaultdict(set)
    user_names: dict[str, str] = {}
    user_subsystems: dict[str, str] = {}

    for r in _read_all_subsystem_leaves():
        ldate = str(r.get("leave_date", ""))
        if ws_str <= ldate <= we_str:
            uid = str(r.get("user_id", ""))
            user_dates[uid].add(ldate)
            user_names[uid] = str(r.get("username", ""))
            user_subsystems[uid] = r.get("_subsystem", "")

    return [
        {"user_id": uid, "username": user_names[uid], "day_count": len(dates), "subsystem": user_subsystems[uid]}
        for uid, dates in user_dates.items()
    ]


# ── Public helpers — Queries ──────────────────────────────────────────────────

def get_user_leaves(user_id: str, week_start: date, week_end: date) -> list[dict]:
    ws_str, we_str = week_start.isoformat(), week_end.isoformat()
    rows = [
        {"leave_date": str(r.get("leave_date", "")), "reason": str(r.get("reason", "")), "subsystem": r.get("_subsystem", "")}
        for r in _read_all_subsystem_leaves()
        if str(r.get("user_id", "")) == user_id and ws_str <= str(r.get("leave_date", "")) <= we_str
    ]
    return sorted(rows, key=lambda x: x["leave_date"])


def get_flagged_users(week_start: date, week_end: date) -> list[tuple[dict, list[dict]]]:
    """Return all users with >1 distinct leave day this week across all subsystem sheets."""
    ws_str, we_str = week_start.isoformat(), week_end.isoformat()
    user_leaves: defaultdict[str, list[dict]] = defaultdict(list)
    user_names: dict[str, str] = {}
    user_subsystems: dict[str, str] = {}

    for r in _read_all_subsystem_leaves():
        ldate = str(r.get("leave_date", ""))
        if ws_str <= ldate <= we_str:
            uid = str(r.get("user_id", ""))
            user_leaves[uid].append({
                "leave_date": ldate,
                "reason": str(r.get("reason", "")),
                "subsystem": r.get("_subsystem", "")
            })
            user_names[uid] = str(r.get("username", ""))
            user_subsystems[uid] = r.get("_subsystem", "")

    result = []
    for uid, leaves in user_leaves.items():
        distinct_days = len({lv["leave_date"] for lv in leaves})
        if distinct_days > 1:
            result.append((
                {"user_id": uid, "username": user_names[uid], "day_count": distinct_days, "subsystem": user_subsystems[uid]},
                sorted(leaves, key=lambda x: x["leave_date"]),
            ))

    result.sort(key=lambda x: (-x[0]["day_count"], x[0]["username"]))
    return result


# ── Date parsing ──────────────────────────────────────────────────────────────

def parse_date_input(value: str | None) -> date:
    """Parse a user-supplied date string into a date object."""
    if value is None or value.strip().lower() in ("", "today"):
        return date.today()
    v = value.strip().lower()
    if v == "tomorrow":
        return date.today() + timedelta(days=1)
    if v == "yesterday":
        return date.today() - timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError("Could not parse date. Use YYYY-MM-DD, 'today', 'tomorrow', or 'yesterday'.")


# ── Scheduled daily check ─────────────────────────────────────────────────────

async def run_daily_check(bot: discord.Client) -> None:
    """Daily scheduled job: checks weekly leaves for all users across subsystem tabs."""
    import asyncio
    logger.info("Executing daily attendance check sweep...")
    week_start, week_end = get_week_bounds(date.today())
    counts = await asyncio.to_thread(get_weekly_leave_counts, week_start, week_end)

    flagged_users = [row for row in counts if row["day_count"] > 1]
    logger.info("Completed daily attendance check sweep", flagged_users_count=len(flagged_users))
