import asyncio
from datetime import datetime, timezone
from typing import Any
import httpx
from notion_client import AsyncClient, APIResponseError
from backend.config.settings import settings
import structlog

logger = structlog.get_logger(__name__)


class NotionService:
    """Service class for managing asynchronous read/write integrations with Notion API."""

    def __init__(self, token: str | None = None) -> None:
        raw_token = token or settings.NOTION_BOT_TOKEN
        self.token = raw_token.strip() if raw_token else ""
        self.client = AsyncClient(auth=self.token)
        self.user_cache: dict[str, str] = {}

    async def get_user_name(self, user_id: str) -> str:
        """Fetch display name of Notion user, with in-memory caching."""
        if user_id in self.user_cache:
            return self.user_cache[user_id]
        try:
            user = await self._execute_with_retry(self.client.users.retrieve, user_id=user_id)
            name = user.get("name") or "CT Manager"
            self.user_cache[user_id] = name
            return name
        except Exception:
            return "CT Manager"

    async def _execute_with_retry(self, api_call: Any, *args: Any, **kwargs: Any) -> Any:
        """Executes Notion API calls wrapped with exponential backoff for rate limits (429)."""
        retries = 3
        delay = 1.0
        for attempt in range(retries):
            try:
                return await api_call(*args, **kwargs)
            except APIResponseError as e:
                # 429 is Notion's rate limit code
                if e.status == 429 and attempt < retries - 1:
                    logger.warning("Notion API rate-limited. Retrying with backoff...", attempt=attempt+1, delay=delay)
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    logger.error("Notion API call failed with response error", status=e.status, code=e.code, message=str(e))
                    raise
            except httpx.HTTPError as e:
                if attempt < retries - 1:
                    logger.warning("Notion network connection error. Retrying...", attempt=attempt+1, delay=delay)
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    logger.error("Notion API connection failed", error=str(e))
                    raise

    async def query_database(self, database_id: str, cursor: str | None = None, page_size: int = 100) -> dict[str, Any]:
        """Queries Notion database for tasks, using filter cursor for incremental changes."""
        body: dict[str, Any] = {
            "page_size": page_size
        }
        if cursor:
            body["start_cursor"] = cursor

        try:
            return await self._execute_with_retry(
                self.client.data_sources.query,
                data_source_id=database_id,
                **body
            )
        except Exception:
            return await self._execute_with_retry(
                self.client.data_sources.query,
                data_source_id=database_id,
                **body
            )

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """Retrieves a single task page from Notion."""
        return await self._execute_with_retry(self.client.pages.retrieve, page_id=page_id)

    async def _align_properties_to_schema(self, database_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        """Aligns input property keys and value structures to the actual Notion database schema."""
        try:
            try:
                schema = await self._execute_with_retry(
                    self.client.data_sources.retrieve,
                    data_source_id=database_id
                )
            except Exception:
                schema = await self._execute_with_retry(
                    self.client.data_sources.retrieve,
                    data_source_id=database_id
                )
            schema_props = schema.get("properties", {}) if schema else {}
        except Exception as e:
            logger.warning("Failed to retrieve database schema, proceeding without property alignment", error=str(e))
            return properties

        aligned_properties: dict[str, Any] = {}
        for key, val in properties.items():
            target_key = None
            clean_key = key.strip().lower()

            # 1. Exact match or stripped match
            for k in schema_props:
                if k.strip().lower() == clean_key:
                    target_key = k
                    break

            # 2. Key alias matching
            if not target_key:
                aliases = {
                    "Task": ["Task name", "Task Name", "Name", "Title"],
                    "Task name": ["Task", "Task Name", "Name", "Title"],
                    "Task Name": ["Task", "Task name", "Name", "Title"],
                    "Assignee": ["Assigned to", "Assigned To", "Assignees"],
                    "Assigned to": ["Assignee", "Assigned To"],
                    "Created By": ["Assigned By", "Assigned by", "Assigner"],
                    "Assigned By": ["Created By", "Assigned by", "Assigner"],
                    "Due Date": ["Due date", "Date", "date"],
                    "Due date": ["Due Date", "Date", "date"],
                    "Date": ["Due Date", "Due date", "date"],
                    "Progress Summary": ["Progress", "Progress summary"],
                    "Progress": ["Progress Summary", "Progress summary"],
                }
                for candidate in aliases.get(key, []):
                    clean_cand = candidate.strip().lower()
                    for k in schema_props:
                        if k.strip().lower() == clean_cand:
                            target_key = k
                            break
                    if target_key:
                        break

            # 3. Fallback: auto-detect Title property if looking for Task/Title
            if not target_key and clean_key in ("task", "task name", "title", "name"):
                for k, v in schema_props.items():
                    if isinstance(v, dict) and v.get("type") == "title":
                        target_key = k
                        break

            if not target_key:
                logger.debug("Property does not exist in Notion schema, filtering out", key=key)
                continue

            prop_schema = schema_props[target_key]
            prop_type = prop_schema.get("type")

            # Value coercion according to Notion schema column type
            if prop_type == "select":
                select_name = None
                if isinstance(val, dict):
                    if "select" in val and isinstance(val["select"], dict):
                        select_name = val["select"].get("name")
                    elif "people" in val and isinstance(val["people"], list) and val["people"]:
                        select_name = val["people"][0].get("id") or val["people"][0].get("name")
                    elif "status" in val and isinstance(val["status"], dict):
                        select_name = val["status"].get("name")
                elif isinstance(val, str):
                    select_name = val

                if select_name:
                    aligned_properties[target_key] = {"select": {"name": str(select_name)}}
                else:
                    aligned_properties[target_key] = {"select": None}

            elif prop_type == "multi_select":
                items = []
                if isinstance(val, dict):
                    if "multi_select" in val and isinstance(val["multi_select"], list):
                        items = [opt.get("name") for opt in val["multi_select"] if isinstance(opt, dict) and opt.get("name")]
                    elif "select" in val and isinstance(val["select"], dict) and val["select"].get("name"):
                        items = [val["select"]["name"]]
                    elif "people" in val and isinstance(val["people"], list):
                        items = [p.get("id") or p.get("name") for p in val["people"] if isinstance(p, dict)]
                elif isinstance(val, list):
                    items = [str(x) for x in val]
                elif isinstance(val, str) and val:
                    items = [val]

                aligned_properties[target_key] = {"multi_select": [{"name": str(i)} for i in items if i]}

            elif prop_type == "status":
                status_name = None
                if isinstance(val, dict) and "status" in val:
                    status_name = val["status"].get("name")
                elif isinstance(val, str):
                    status_name = val

                if status_name:
                    aligned_properties[target_key] = {"status": {"name": str(status_name)}}

            elif prop_type == "people":
                people_list = []
                if isinstance(val, dict) and "people" in val and isinstance(val["people"], list):
                    for p in val["people"]:
                        pid = p.get("id") if isinstance(p, dict) else str(p)
                        if pid and len(pid) == 36 and "-" in pid: # Must be valid UUID for Notion people property
                            people_list.append({"object": "user", "id": pid})
                aligned_properties[target_key] = {"people": people_list}

            else:
                aligned_properties[target_key] = val

        return aligned_properties

    async def add_select_option_to_database(self, database_id: str, property_name: str, option_name: str) -> bool:
        """Adds a new option name to a Select or Multi-Select dropdown property in a Notion database."""
        try:
            db_info = None
            try:
                db_info = await self._execute_with_retry(self.client.databases.retrieve, database_id=database_id)
            except Exception:
                try:
                    db_info = await self._execute_with_retry(self.client.data_sources.retrieve, data_source_id=database_id)
                except Exception:
                    db_info = None

            if not db_info:
                return False

            props = db_info.get("properties", {})
            target_prop_key = None

            # Look for exact or alias property match in schema
            candidates = [property_name]
            if property_name.lower() in ("assigned to", "assignee"):
                candidates = ["Assigned to", "Assigned To", "Assignee", "Assignees"]
            elif property_name.lower() in ("assigned by", "assigner", "created by"):
                candidates = ["Assigned By", "Assigned by", "Assigner", "Created By"]

            for k in candidates:
                if k in props:
                    target_prop_key = k
                    break

            if not target_prop_key:
                # Case-insensitive fallback
                for prop_k in props:
                    if prop_k.lower() == property_name.lower():
                        target_prop_key = prop_k
                        break

            if not target_prop_key:
                logger.warning("Target dropdown property not found in Notion schema", database_id=database_id, property_name=property_name)
                return False

            prop_info = props[target_prop_key]
            prop_type = prop_info.get("type")

            if prop_type == "select":
                current_options = prop_info.get("select", {}).get("options", [])
                existing_names = [opt.get("name") for opt in current_options]
                if option_name not in existing_names:
                    new_options = current_options + [{"name": option_name}]
                    try:
                        await self._execute_with_retry(
                            self.client.databases.update,
                            database_id=database_id,
                            properties={target_prop_key: {"select": {"options": new_options}}}
                        )
                    except Exception:
                        await self._execute_with_retry(
                            self.client.data_sources.update,
                            data_source_id=database_id,
                            properties={target_prop_key: {"select": {"options": new_options}}}
                        )
                    logger.info("Added option to Notion select dropdown", database_id=database_id, option_name=option_name)
                    return True
            elif prop_type == "multi_select":
                current_options = prop_info.get("multi_select", {}).get("options", [])
                existing_names = [opt.get("name") for opt in current_options]
                if option_name not in existing_names:
                    new_options = current_options + [{"name": option_name}]
                    try:
                        await self._execute_with_retry(
                            self.client.databases.update,
                            database_id=database_id,
                            properties={target_prop_key: {"multi_select": {"options": new_options}}}
                        )
                    except Exception:
                        await self._execute_with_retry(
                            self.client.data_sources.update,
                            data_source_id=database_id,
                            properties={target_prop_key: {"multi_select": {"options": new_options}}}
                        )
                    logger.info("Added option to Notion multi_select dropdown", database_id=database_id, option_name=option_name)
                    return True
        except Exception as e:
            logger.warning("Failed to add option to Notion database dropdown", database_id=database_id, option_name=option_name, error=str(e))
        return False

    async def remove_select_options_from_database(
        self, database_id: str, property_name: str, options_to_remove: list[str]
    ) -> bool:
        """Removes specified option names from a Notion select or multi_select dropdown property."""
        try:
            try:
                schema = await self.client.data_sources.retrieve(data_source_id=database_id)
            except Exception:
                schema = await self._execute_with_retry(self.client.databases.retrieve, database_id=database_id)

            props = schema.get("properties", {}) if schema else {}
            target_prop_key = None
            clean_name = property_name.strip().lower()

            for prop_k in props:
                if prop_k.strip().lower() == clean_name:
                    target_prop_key = prop_k
                    break

            if not target_prop_key:
                logger.warning("Target dropdown property not found in Notion schema for removal", database_id=database_id, property_name=property_name)
                return False

            remove_set = set(x.strip().lower() for x in options_to_remove)
            prop_info = props[target_prop_key]
            prop_type = prop_info.get("type")

            if prop_type in ("select", "multi_select"):
                current_options = prop_info.get(prop_type, {}).get("options", [])
                new_options = [
                    opt for opt in current_options
                    if opt.get("name", "").strip().lower() not in remove_set
                ]
                if len(new_options) != len(current_options):
                    payload = {target_prop_key: {prop_type: {"options": new_options}}}
                    try:
                        await self.client.data_sources.update(data_source_id=database_id, properties=payload)
                    except Exception:
                        await self._execute_with_retry(self.client.databases.update, database_id=database_id, properties=payload)
                    logger.info("Removed options from Notion dropdown", database_id=database_id, count=len(current_options) - len(new_options))
                    return True
        except Exception as e:
            logger.warning("Failed to remove option from Notion dropdown", database_id=database_id, error=str(e))
        return False

    async def create_page(self, database_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        """Creates a new page in a mapped Notion database."""
        aligned_props = await self._align_properties_to_schema(database_id, properties)
        try:
            return await self.client.pages.create(
                parent={"data_source_id": database_id},
                properties=aligned_props
            )
        except Exception:
            return await self._execute_with_retry(
                self.client.pages.create,
                parent={"database_id": database_id},
                properties=aligned_props
            )

    async def update_page_properties(self, page_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        """Updates properties of an existing Notion task page."""
        try:
            page = await self._execute_with_retry(self.client.pages.retrieve, page_id=page_id)
            parent = page.get("parent", {}) if page else {}
            parent_id = parent.get("data_source_id") or parent.get("database_id")
            if parent_id:
                properties = await self._align_properties_to_schema(parent_id, properties)
        except Exception as e:
            logger.warning("Failed to align properties for update_page_properties", error=str(e))

        return await self._execute_with_retry(
            self.client.pages.update,
            page_id=page_id,
            properties=properties
        )

    async def add_page_comment(self, page_id: str, comment_text: str) -> None:
        """Posts a comment directly to the Notion page's Comments section."""
        try:
            await self._execute_with_retry(
                self.client.comments.create,
                parent={"page_id": page_id},
                rich_text=[{"text": {"content": comment_text}}]
            )
            logger.info("Added comment to Notion page", page_id=page_id)
        except Exception as e:
            logger.warning("Failed to add comment to Notion page", page_id=page_id, error=str(e))

    # Notion Property Builders (Schema Mapping)
    @staticmethod
    def build_task_properties(task_data: dict[str, Any]) -> dict[str, Any]:
        """Builds Notion property payload from task field dictionary."""
        properties: dict[str, Any] = {}

        # 1. Title (Task)
        if "title" in task_data:
            properties["Task"] = {
                "title": [{"text": {"content": task_data["title"]}}]
            }

        # 2. Rich Text Fields
        rich_text_fields = {
            "description": "Description",
            "progress_summary": "Progress Summary",
            "completion_summary": "Completion Summary",
            "blocked_reason": "Blocked Reason",
            "updated_by": "Updated By"
        }
        for field, notion_prop in rich_text_fields.items():
            if field in task_data:
                val = task_data[field] or ""
                properties[notion_prop] = {
                    "rich_text": [{"text": {"content": val}}]
                }

        # 3. Status (Status type)
        if "status" in task_data:
            properties["Status"] = {
                "status": {"name": task_data["status"]}
            }

        # 4. Priority (Select type)
        if "priority" in task_data:
            properties["Priority"] = {
                "select": {"name": task_data["priority"]}
            }

        # 5. Date Fields (UTC ISO Strings)
        date_fields = {
            "due_date": "Due Date",
            "started_time": "Started Time",
            "completed_time": "Completed Time",
            "last_activity": "Last Activity"
        }
        for field, notion_prop in date_fields.items():
            if field in task_data:
                dt: datetime | None = task_data[field]
                if dt:
                    properties[notion_prop] = {
                        "date": {"start": dt.isoformat()}
                    }
                else:
                    properties[notion_prop] = {"date": None}

        # 6. Assignee (Notion user ID lists or multi-select dropdown names)
        if "notion_assignee_name" in task_data:
            name = task_data["notion_assignee_name"]
            if name:
                names = [x.strip() for x in name.split(",") if x.strip()]
                properties["Assigned to"] = {
                    "multi_select": [{"name": n} for n in names]
                }
        elif "notion_assignee_id" in task_data:
            assignee_id = task_data["notion_assignee_id"]
            if assignee_id:
                properties["Assignee"] = {
                    "people": [{"object": "user", "id": assignee_id}]
                }
            else:
                properties["Assignee"] = {"people": []}

        # 6b. Assigned By (Select dropdown)
        if "assigned_by_name" in task_data:
            ab_name = task_data["assigned_by_name"]
            if ab_name:
                properties["Assigned By"] = {
                    "select": {"name": ab_name}
                }

        # 7. URL / Link Collections (Stored as JSON/text arrays)
        link_fields = {
            "drive_links": "Drive Links",
            "github_links": "GitHub Links",
            "attachments": "Attachments"
        }
        for field, notion_prop in link_fields.items():
            if field in task_data:
                links_list = task_data[field]
                # Notion rich text strings mapped
                if isinstance(links_list, list):
                    # attachments can be list of dicts {url, name, type}, extract url
                    str_items = []
                    for item in links_list:
                        if isinstance(item, dict):
                            str_items.append(item.get("url", str(item)))
                        else:
                            str_items.append(str(item))
                    joined_links = ", ".join(str_items)
                else:
                    joined_links = links_list or ""
                properties[notion_prop] = {
                    "rich_text": [{"text": {"content": joined_links}}]
                }

        return properties

    @staticmethod
    def parse_notion_properties(page: dict[str, Any]) -> dict[str, Any]:
        """Parses Notion page properties into standard domain task dictionary format."""
        props = page.get("properties", {}) or {}
        parsed: dict[str, Any] = {
            "notion_page_id": page["id"],
            "last_activity": datetime.fromisoformat(page["last_edited_time"].replace("Z", "+00:00")),
            "description": None,
            "progress_summary": None,
            "completion_summary": None,
            "blocked_reason": None,
            "updated_by": None,
            "drive_links": [],
            "github_links": [],
            "attachments": []
        }

        # 1. Parse Title (Find property with type == "title" or title key)
        title_prop = None
        for k, v in props.items():
            if isinstance(v, dict) and (v.get("type") == "title" or "title" in v):
                title_prop = v
                break

        title_list = title_prop.get("title", []) if title_prop else []
        title_text = "".join([t.get("text", {}).get("content", "") for t in title_list]) if title_list else ""
        parsed["title"] = title_text.strip() if title_text.strip() else "Untitled Task"

        # 2. Parse Rich Text Properties
        rich_text_props = {
            "Description": "description",
            "Progress Summary": "progress_summary",
            "Progress": "progress_summary",
            "Completion Summary": "completion_summary",
            "Blocked Reason": "blocked_reason",
            "Blocked": "blocked_reason",
            "Blocker": "blocked_reason",
            "Blocker Reason": "blocked_reason",
            "Updated By": "updated_by"
        }
        for notion_prop, target_field in rich_text_props.items():
            if notion_prop in props:
                prop = props.get(notion_prop)
                text_list = prop.get("rich_text", []) if prop else []
                val = "".join([t.get("text", {}).get("content", "") for t in text_list]) if text_list else None
                if val and not parsed.get(target_field):
                    parsed[target_field] = val

        # 3. Parse Status
        status_prop = props.get("Status") or props.get("status")
        status_name = "Not Started"
        if status_prop:
            status_obj = status_prop.get("status")
            if status_obj:
                status_name = status_obj.get("name", "Not Started")
            else:
                select_obj = status_prop.get("select")
                if select_obj:
                    status_name = select_obj.get("name", "Not Started")

        clean_status = status_name.strip().lower()
        if clean_status in ("blocked", "stuck", "on hold", "stopped"):
            status_name = "Blocked"
        elif clean_status in ("in progress", "doing", "active", "working"):
            status_name = "In Progress"
        elif clean_status in ("done", "completed", "complete", "finished"):
            status_name = "Done"

        parsed["status"] = status_name

        # 4. Parse Priority
        priority_prop = props.get("Priority")
        priority_name = "Medium"
        if priority_prop:
            select_obj = priority_prop.get("select")
            if select_obj:
                priority_name = select_obj.get("name", "Medium")
        parsed["priority"] = priority_name

        # 5. Parse Date Fields
        date_props = {
            "Due Date": "due_date",
            "Due date": "due_date",
            "Date": "due_date",
            "date": "due_date",
            "Deadline": "due_date",
            "Target Date": "due_date",
            "Started Time": "started_time",
            "Completed Time": "completed_time"
        }
        for target_field in ["due_date", "started_time", "completed_time"]:
            parsed[target_field] = None

        for notion_prop, target_field in date_props.items():
            if notion_prop in props:
                prop = props.get(notion_prop)
                date_dict = prop.get("date") if prop else None
                if date_dict and date_dict.get("start"):
                    parsed[target_field] = datetime.fromisoformat(date_dict["start"].replace("Z", "+00:00"))

        # Fallback: scan any property of type 'date' if due_date was not matched by key
        if not parsed.get("due_date"):
            for prop_name, prop_val in props.items():
                if isinstance(prop_val, dict) and prop_val.get("date"):
                    date_dict = prop_val.get("date")
                    if date_dict and date_dict.get("start"):
                        try:
                            parsed["due_date"] = datetime.fromisoformat(date_dict["start"].replace("Z", "+00:00"))
                            break
                        except Exception:
                            pass

        # 6. Parse Assignee (People, Select dropdown, Multi-select, or Rich text)
        assignee_prop = (
            props.get("Assigned to")
            or props.get("Assigned To")
            or props.get("Assignee")
            or props.get("Assignees")
            or props.get("Owner")
            or props.get("Member")
        )
        assignee_id = None
        assignee_name = None
        assignee_names: list[str] = []

        if assignee_prop:
            # A) People type
            people = assignee_prop.get("people", [])
            if people:
                for p in people:
                    name = p.get("name") or p.get("id")
                    if name:
                        assignee_names.append(name)
                assignee_id = people[0].get("id")
                assignee_name = ", ".join(assignee_names)
            # B) Select type (Dropdown option)
            elif assignee_prop.get("select"):
                select_dict = assignee_prop.get("select", {})
                name = select_dict.get("name")
                if name:
                    assignee_names.append(name)
                    assignee_name = name
                    assignee_id = select_dict.get("id") or name
            # C) Multi-select type
            elif assignee_prop.get("multi_select"):
                multi_list = assignee_prop.get("multi_select", [])
                if multi_list:
                    for item in multi_list:
                        name = item.get("name")
                        if name:
                            assignee_names.append(name)
                    assignee_name = ", ".join(assignee_names)
                    assignee_id = multi_list[0].get("id") or (assignee_names[0] if assignee_names else None)
            # D) Rich text type
            elif assignee_prop.get("rich_text"):
                rt_list = assignee_prop.get("rich_text", [])
                if rt_list:
                    raw_text = "".join([t.get("text", {}).get("content", "") for t in rt_list])
                    assignee_names = [x.strip() for x in raw_text.split(",") if x.strip()]
                    assignee_name = ", ".join(assignee_names)
                    assignee_id = assignee_name

        parsed["notion_assignee_id"] = assignee_id
        parsed["notion_assignee_name"] = assignee_name
        parsed["assignee_names"] = assignee_names

        # 6b. Parse Assigned By (Select dropdown, Multi-select, People, or Rich text)
        assigned_by_prop = (
            props.get("Assigned By")
            or props.get("Assigned by")
            or props.get("Assigner")
            or props.get("Created By")
            or props.get("Created by")
        )
        assigned_by_name = None
        if assigned_by_prop:
            if assigned_by_prop.get("select"):
                assigned_by_name = assigned_by_prop.get("select", {}).get("name")
            elif assigned_by_prop.get("multi_select"):
                ms = assigned_by_prop.get("multi_select", [])
                if ms:
                    assigned_by_name = ms[0].get("name")
            elif assigned_by_prop.get("people"):
                ppl = assigned_by_prop.get("people", [])
                if ppl:
                    assigned_by_name = ppl[0].get("name")
            elif assigned_by_prop.get("rich_text"):
                rt = assigned_by_prop.get("rich_text", [])
                if rt:
                    assigned_by_name = "".join([t.get("text", {}).get("content", "") for t in rt])

        parsed["assigned_by_name"] = assigned_by_name

        # 7. Parse Link Arrays
        link_props = {
            "Drive Links": "drive_links",
            "GitHub Links": "github_links",
            "Attachments": "attachments"
        }
        for notion_prop, target_field in link_props.items():
            prop = props.get(notion_prop)
            text_list = prop.get("rich_text", []) if prop else []
            raw_text = "".join([t.get("text", {}).get("content", "") for t in text_list]) if text_list else ""
            parsed[target_field] = [link.strip() for link in raw_text.split(",") if link.strip()] if raw_text else []

        return parsed
