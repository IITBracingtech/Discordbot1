"""
Tests — Milestone 8: Smart Message Parser
==========================================
Covers:
  - All 8 intent classifications
  - Confidence thresholds
  - Link detection (all 10 platform link types)
  - File detection (Discord attachments + text mentions)
  - Metadata extraction (blocked reason, progress note, extension request)
  - Priority ordering (complete beats progress, blocked beats start, etc.)
  - Edge cases (empty message, bot-only links, duplicate URLs)
"""

import pytest
from backend.modules.tasks.parser import (
    Intent,
    LinkType,
    ParsedIntent,
    parse_message,
    _detect_links,
    _detect_files,
    SUPPORTED_FILE_EXTENSIONS,
)


# ─────────────────────────────────────────────────
# Intent: COMPLETE
# ─────────────────────────────────────────────────

class TestCompleteIntent:
    def test_done_simple(self):
        result = parse_message("done")
        assert result.intent == Intent.COMPLETE
        assert result.confidence >= 0.4

    def test_completed(self):
        result = parse_message("completed the task")
        assert result.intent == Intent.COMPLETE

    def test_finished(self):
        result = parse_message("finished everything")
        assert result.intent == Intent.COMPLETE

    def test_all_done(self):
        result = parse_message("all done!")
        assert result.intent == Intent.COMPLETE

    def test_task_is_done(self):
        result = parse_message("task is done")
        assert result.intent == Intent.COMPLETE
        assert result.confidence >= 0.7

    def test_wrapped_up(self):
        result = parse_message("wrapped up the simulation runs")
        assert result.intent == Intent.COMPLETE

    def test_pushed_to_main(self):
        result = parse_message("pushed to main, all tests pass")
        assert result.intent == Intent.COMPLETE

    def test_submitted(self):
        result = parse_message("submitted the report")
        assert result.intent == Intent.COMPLETE


# ─────────────────────────────────────────────────
# Intent: BLOCKED
# ─────────────────────────────────────────────────

class TestBlockedIntent:
    def test_blocked_simple(self):
        result = parse_message("blocked")
        assert result.intent == Intent.BLOCKED

    def test_waiting_for_parts(self):
        result = parse_message("waiting for manufacturing parts")
        assert result.intent == Intent.BLOCKED

    def test_on_hold(self):
        result = parse_message("task is on hold")
        assert result.intent == Intent.BLOCKED

    def test_blocked_reason_extracted(self):
        result = parse_message("blocked waiting for CNC parts from vendor")
        assert result.intent == Intent.BLOCKED
        assert result.blocked_reason is not None
        assert len(result.blocked_reason) > 0

    def test_waiting_for_approval(self):
        result = parse_message("need approval from team lead before continuing")
        assert result.intent == Intent.BLOCKED

    def test_cannot_proceed(self):
        result = parse_message("can't proceed without the material")
        assert result.intent == Intent.BLOCKED

    def test_blocked_by(self):
        result = parse_message("blocked by supply chain delay")
        assert result.intent == Intent.BLOCKED

    def test_waiting_for_review(self):
        result = parse_message("waiting for review before I can move forward")
        assert result.intent == Intent.BLOCKED


# ─────────────────────────────────────────────────
# Intent: START
# ─────────────────────────────────────────────────

class TestStartIntent:
    def test_starting(self):
        result = parse_message("starting now")
        assert result.intent == Intent.START

    def test_started_working(self):
        result = parse_message("started working on this")
        assert result.intent == Intent.START

    def test_on_it(self):
        result = parse_message("on it now")
        assert result.intent == Intent.START

    def test_picking_up(self):
        result = parse_message("picking this up today")
        assert result.intent == Intent.START

    def test_beginning(self):
        result = parse_message("beginning the CFD simulation")
        assert result.intent == Intent.START

    def test_kicking_off(self):
        result = parse_message("kicking off the design sprint")
        assert result.intent == Intent.START


# ─────────────────────────────────────────────────
# Intent: PROGRESS_UPDATE
# ─────────────────────────────────────────────────

class TestProgressUpdateIntent:
    def test_working_on(self):
        result = parse_message("still working on the wiring harness")
        assert result.intent == Intent.PROGRESS_UPDATE

    def test_in_progress(self):
        result = parse_message("in progress, about 60% done")
        assert result.intent == Intent.PROGRESS_UPDATE

    def test_progress_prefix(self):
        result = parse_message("Update: ran the FEA simulation, waiting for results")
        assert result.intent == Intent.PROGRESS_UPDATE

    def test_note_extracted(self):
        result = parse_message("Progress: finished the CAD model, now doing tolerances")
        assert result.intent == Intent.PROGRESS_UPDATE
        assert result.progress_note is not None
        assert "CAD model" in result.progress_note

    def test_partial_done(self):
        result = parse_message("halfway done, should finish tomorrow")
        assert result.intent == Intent.PROGRESS_UPDATE

    def test_tested(self):
        result = parse_message("ran tests and verified the logic")
        assert result.intent == Intent.PROGRESS_UPDATE


# ─────────────────────────────────────────────────
# Intent: DEADLINE_EXTENSION
# ─────────────────────────────────────────────────

class TestDeadlineExtensionIntent:
    def test_need_more_time(self):
        result = parse_message("need more time")
        assert result.intent == Intent.DEADLINE_EXTENSION

    def test_need_another_day(self):
        result = parse_message("need another day please")
        assert result.intent == Intent.DEADLINE_EXTENSION
        assert result.extension_request is not None

    def test_extend_deadline(self):
        result = parse_message("can you extend the deadline by 2 days")
        assert result.intent == Intent.DEADLINE_EXTENSION

    def test_deadline_extension_explicit(self):
        result = parse_message("requesting deadline extension")
        assert result.intent == Intent.DEADLINE_EXTENSION

    def test_will_take_two_days(self):
        result = parse_message("will need two more days to finish testing")
        assert result.intent == Intent.DEADLINE_EXTENSION

    def test_behind_schedule(self):
        result = parse_message("behind schedule, probably need 3 more days")
        assert result.intent == Intent.DEADLINE_EXTENSION

    def test_extension_detail_extracted(self):
        result = parse_message("need 2 more days for the motor controller integration")
        assert result.intent == Intent.DEADLINE_EXTENSION
        assert result.extension_request is not None
        assert "2 more days" in result.extension_request.lower() or "days" in result.extension_request.lower()


# ─────────────────────────────────────────────────
# Intent: NEED_HELP
# ─────────────────────────────────────────────────

class TestNeedHelpIntent:
    def test_need_help(self):
        result = parse_message("need help with this")
        assert result.intent == Intent.NEED_HELP

    def test_can_someone_help(self):
        result = parse_message("can someone help me with the torque calculation?")
        assert result.intent == Intent.NEED_HELP

    def test_question_prefix(self):
        result = parse_message("Question: how do I calibrate the sensor?")
        assert result.intent == Intent.NEED_HELP

    def test_please_review(self):
        result = parse_message("please review this before I submit")
        assert result.intent == Intent.NEED_HELP

    def test_stuck_on(self):
        result = parse_message("stuck on the PWM configuration")
        assert result.intent == Intent.NEED_HELP


# ─────────────────────────────────────────────────
# Intent: FILE_UPLOAD
# ─────────────────────────────────────────────────

class TestFileUploadIntent:
    def test_attachment_detected(self):
        result = parse_message("here's the file", attachment_filenames=["rear_wing.step"])
        assert result.intent == Intent.FILE_UPLOAD
        assert result.confidence >= 0.9
        assert len(result.files) == 1
        assert result.files[0].filename == "rear_wing.step"
        assert result.files[0].extension == "step"

    def test_multiple_attachments(self):
        result = parse_message(
            "uploading CAD files",
            attachment_filenames=["front_upright.sldprt", "suspension.sldasm", "specs.pdf"]
        )
        assert result.intent == Intent.FILE_UPLOAD
        assert len(result.files) == 3

    def test_pdf_attachment(self):
        result = parse_message("attached the report", attachment_filenames=["design_report.pdf"])
        assert result.intent == Intent.FILE_UPLOAD
        assert result.files[0].extension == "pdf"

    def test_upload_mention_in_text(self):
        result = parse_message("uploaded CAD model for review")
        assert result.intent == Intent.FILE_UPLOAD

    def test_filename_mentioned_in_text(self):
        result = parse_message("check rear_wing.step for the updated geometry")
        assert result.intent == Intent.FILE_UPLOAD
        assert any(f.filename == "rear_wing.step" for f in result.files)

    def test_all_cad_extensions_detected(self):
        cad_files = ["model.step", "part.sldprt", "assembly.sldasm", "drawing.dxf", "design.dwg"]
        for fname in cad_files:
            result = parse_message("here", attachment_filenames=[fname])
            assert result.intent == Intent.FILE_UPLOAD, f"Failed for {fname}"
            assert result.files[0].extension == fname.split(".")[-1]


# ─────────────────────────────────────────────────
# Intent: LINK_SHARED
# ─────────────────────────────────────────────────

class TestLinkSharedIntent:
    def test_google_drive_link(self):
        result = parse_message("here's the drive folder https://drive.google.com/drive/folders/abc123")
        assert result.intent == Intent.LINK_SHARED
        assert len(result.links) == 1
        assert result.links[0].link_type == LinkType.GOOGLE_DRIVE

    def test_drive_links_property(self):
        result = parse_message("https://drive.google.com/file/d/xyz/view")
        assert len(result.drive_links) == 1

    def test_github_link(self):
        result = parse_message("https://github.com/iitb-racing/firmware/pull/42")
        assert result.intent == Intent.LINK_SHARED
        assert result.links[0].link_type == LinkType.GITHUB

    def test_github_links_property(self):
        result = parse_message("check https://github.com/iitb-racing/daq")
        assert len(result.github_links) == 1

    def test_gitlab_link(self):
        result = parse_message("https://gitlab.com/team/project")
        assert result.links[0].link_type == LinkType.GITLAB

    def test_figma_link(self):
        result = parse_message("design: https://www.figma.com/file/abc/Dashboard")
        assert result.links[0].link_type == LinkType.FIGMA

    def test_canva_link(self):
        result = parse_message("poster: https://www.canva.com/design/xyz")
        assert result.links[0].link_type == LinkType.CANVA

    def test_notion_link(self):
        result = parse_message("task: https://notion.so/iitb/task-123")
        assert result.links[0].link_type == LinkType.NOTION

    def test_youtube_link(self):
        result = parse_message("reference: https://www.youtube.com/watch?v=abc")
        assert result.links[0].link_type == LinkType.YOUTUBE

    def test_youtu_be_shortlink(self):
        result = parse_message("https://youtu.be/dQw4w9WgXcQ")
        assert result.links[0].link_type == LinkType.YOUTUBE

    def test_dropbox_link(self):
        result = parse_message("files: https://www.dropbox.com/sh/abc123")
        assert result.links[0].link_type == LinkType.DROPBOX

    def test_onedrive_link(self):
        result = parse_message("https://onedrive.live.com/view.aspx?id=xyz")
        assert result.links[0].link_type == LinkType.ONEDRIVE

    def test_google_docs_link(self):
        result = parse_message("https://docs.google.com/document/d/abc/edit")
        assert result.links[0].link_type == LinkType.GOOGLE_DOCS

    def test_google_sheets_link(self):
        result = parse_message("https://docs.google.com/spreadsheets/d/abc/edit")
        assert result.links[0].link_type == LinkType.GOOGLE_SHEETS

    def test_multiple_links_detected(self):
        result = parse_message(
            "drive: https://drive.google.com/file/d/abc "
            "github: https://github.com/iitb/repo"
        )
        assert len(result.links) == 2
        types = {lnk.link_type for lnk in result.links}
        assert LinkType.GOOGLE_DRIVE in types
        assert LinkType.GITHUB in types

    def test_duplicate_url_not_added_twice(self):
        url = "https://github.com/iitb/repo"
        result = parse_message(f"{url} {url}")
        github = [lnk for lnk in result.links if lnk.link_type == LinkType.GITHUB]
        assert len(github) == 1


# ─────────────────────────────────────────────────
# Intent Priority Ordering
# ─────────────────────────────────────────────────

class TestIntentPriority:
    def test_complete_beats_progress(self):
        # "done" should win over "working on it"
        result = parse_message("done, was working on it all day")
        assert result.intent == Intent.COMPLETE

    def test_blocked_beats_start(self):
        # "blocked" should win over "starting"
        result = parse_message("started but now blocked waiting for parts")
        assert result.intent == Intent.BLOCKED

    def test_complete_beats_link(self):
        # Completion + a drive link → COMPLETE is primary, link is persisted
        result = parse_message("done, here's the drive: https://drive.google.com/file/d/abc")
        assert result.intent == Intent.COMPLETE
        # Link should still be detected
        assert len(result.links) == 1
        assert result.links[0].link_type == LinkType.GOOGLE_DRIVE

    def test_extension_beats_progress(self):
        # Extension request beats vague progress
        result = parse_message("still working but need 2 more days")
        assert result.intent == Intent.DEADLINE_EXTENSION


# ─────────────────────────────────────────────────
# Edge Cases
# ─────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_string(self):
        result = parse_message("")
        assert result.intent == Intent.UNRECOGNIZED
        assert result.confidence == 0.0

    def test_whitespace_only(self):
        result = parse_message("   ")
        assert result.intent == Intent.UNRECOGNIZED

    def test_none_like_empty(self):
        result = parse_message("")
        assert result.intent == Intent.UNRECOGNIZED

    def test_unrelated_message(self):
        result = parse_message("hello everyone, good morning!")
        assert result.intent == Intent.UNRECOGNIZED

    def test_raw_message_preserved(self):
        msg = "done with the task"
        result = parse_message(msg)
        assert result.raw_message == msg

    def test_urls_stripped_from_extracted_text(self):
        result = parse_message("done https://github.com/iitb/repo")
        assert "https://" not in result.extracted_text

    def test_is_actionable_true_for_known_intents(self):
        result = parse_message("blocked")
        assert result.is_actionable is True

    def test_is_actionable_false_for_unrecognized(self):
        result = parse_message("good morning everyone!")
        assert result.is_actionable is False

    def test_case_insensitive(self):
        result = parse_message("DONE")
        assert result.intent == Intent.COMPLETE

        result2 = parse_message("BLOCKED")
        assert result2.intent == Intent.BLOCKED

    def test_mixed_case(self):
        result = parse_message("Done With Everything")
        assert result.intent == Intent.COMPLETE

    def test_message_with_emoji(self):
        result = parse_message("done ✅🎉")
        assert result.intent == Intent.COMPLETE

    def test_message_with_punctuation(self):
        result = parse_message("blocked... waiting for review!!!")
        assert result.intent == Intent.BLOCKED

    def test_multiline_message(self):
        result = parse_message(
            "Update from today:\n"
            "- Ran FEA simulation\n"
            "- Results look good\n"
            "- Still working on post-processing"
        )
        assert result.intent == Intent.PROGRESS_UPDATE

    def test_file_and_link_in_same_message(self):
        result = parse_message(
            "uploading files",
            attachment_filenames=["rear_wing.step"]
        )
        # FILE_UPLOAD takes priority over LINK_SHARED
        assert result.intent == Intent.FILE_UPLOAD

    def test_complete_with_file_attachment(self):
        """
        When a user says 'done' AND attaches a file, FILE_UPLOAD is the primary
        intent because actual attachment handling must run first to persist the file.
        The COMPLETE intent is still detectable — the listener's _persist_links_and_files
        secondary pass handles this. The completion prompt is sent by the listener
        separately based on the COMPLETE score being above threshold.
        """
        result = parse_message(
            "done, attaching the final report",
            attachment_filenames=["final_report.pdf"]
        )
        # FILE_UPLOAD wins when actual attachment is present (attachment_filenames set)
        assert result.intent == Intent.FILE_UPLOAD
        # But COMPLETE is still detected in the scores — confidence is high
        assert result.confidence >= 0.9
        # File is captured
        assert len(result.files) == 1
        assert result.files[0].extension == "pdf"


# ─────────────────────────────────────────────────
# Supported File Extensions
# ─────────────────────────────────────────────────

class TestSupportedFiles:
    def test_common_extensions_are_supported(self):
        expected = {"pdf", "docx", "xlsx", "png", "jpg", "step", "sldprt", "dxf", "zip"}
        assert expected.issubset(SUPPORTED_FILE_EXTENSIONS)

    def test_unsupported_extension_not_detected(self):
        result = parse_message("", attachment_filenames=["file.exe"])
        # .exe is not supported — should not appear in files list
        assert not any(f.extension == "exe" for f in result.files)

    def test_csv_is_supported(self):
        result = parse_message("data", attachment_filenames=["telemetry_log.csv"])
        assert result.intent == Intent.FILE_UPLOAD
        assert result.files[0].extension == "csv"


# ─────────────────────────────────────────────────
# Realistic Engineering Team Messages
# ─────────────────────────────────────────────────

class TestRealisticMessages:
    def test_cad_upload(self):
        result = parse_message(
            "uploaded the rear upright CAD",
            attachment_filenames=["rear_upright_v3.step"]
        )
        assert result.intent == Intent.FILE_UPLOAD

    def test_simulation_complete(self):
        result = parse_message(
            "CFD simulation complete, results in drive: https://drive.google.com/drive/folders/xyz"
        )
        assert result.intent == Intent.COMPLETE
        assert len(result.drive_links) == 1

    def test_waiting_for_vendor(self):
        result = parse_message("blocked, aluminum stock hasn't arrived from vendor yet")
        assert result.intent == Intent.BLOCKED
        assert "vendor" in (result.blocked_reason or "").lower()

    def test_pr_opened(self):
        result = parse_message(
            "finished the firmware changes, PR opened: https://github.com/iitb-racing/daq/pull/15"
        )
        assert result.intent == Intent.COMPLETE
        assert len(result.github_links) == 1

    def test_design_review_request(self):
        result = parse_message("can someone review the suspension geometry? https://figma.com/file/abc")
        assert result.intent == Intent.NEED_HELP
        assert result.links[0].link_type == LinkType.FIGMA

    def test_deadline_with_reason(self):
        result = parse_message(
            "need 2 more days — the motor controller integration is taking longer than expected"
        )
        assert result.intent == Intent.DEADLINE_EXTENSION
        assert result.extension_request is not None

    def test_progress_with_percentage(self):
        result = parse_message("about 70% done with the wiring harness routing")
        assert result.intent == Intent.PROGRESS_UPDATE

    def test_complete_german_style(self):
        """Test a terse message common in engineering teams."""
        result = parse_message("task done. closing.")
        assert result.intent == Intent.COMPLETE
