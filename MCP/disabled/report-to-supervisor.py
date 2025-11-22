#!/usr/bin/env python3
"""MCP: report-to-supervisor

Report findings to Trek Meridian Blackwater (supervisor) and exit the monitor loop.
This allows the agent to gracefully complete its task when monitoring file activity.

Future: This will integrate with LilyGO network deployment for remote reporting.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("report-to-supervisor")

# Supervisor details
SUPERVISOR_NAME = "Trek Meridian Blackwater"
REPORT_LOG_PATH = Path("/workspace/supervisor_reports.log")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


@mcp.tool()
async def report_to_supervisor(
    summary: str,
    task_type: str = "monitoring",
    files_processed: Optional[List[str]] = None,
    status: str = "completed",
    notes: str = "",
    agent_name: str = "Alpha India",
) -> Dict[str, object]:
    """Report task completion to supervisor Trek Meridian Blackwater and exit.

    This tool allows the agent to formally report findings from monitoring tasks
    and signal that the current monitoring session can be closed. Use this when:
    - Transcription jobs have been queued successfully
    - Files have been processed and no further action is needed
    - An error occurred that requires supervisor attention
    - The agent needs to exit the monitoring loop gracefully

    Args:
        summary: Brief summary of what was accomplished (1-2 sentences)
        task_type: Type of task (default: "monitoring"). Examples: "transcription",
                  "file_processing", "error_recovery"
        files_processed: List of files that were processed (optional)
        status: Task status - "completed", "partial", "failed", "queued"
        notes: Additional notes or observations for the supervisor (optional)

    Returns:
        Dictionary with report confirmation and details.

    Example:
        report_to_supervisor(
            summary="Queued transcription for transmission_20251019_141317_11.wav",
            task_type="transcription",
            files_processed=["/workspace/recordings/transmission_20251019_141317_11.wav"],
            status="queued",
            notes="Model loading in progress. Transcript will appear in /workspace/transcriptions/"
        )
    """

    timestamp = _utc_now()
    report_id = timestamp.strftime("%Y%m%d_%H%M%S")

    # Build report
    report_lines = [
        "=" * 70,
        "AGENT REPORT TO SUPERVISOR",
        f"From: {agent_name}",
        f"To: {SUPERVISOR_NAME}",
        f"Report ID: {report_id}",
        f"Timestamp: {_format_timestamp(timestamp)}",
        "=" * 70,
        "",
        f"Task Type: {task_type}",
        f"Status: {status.upper()}",
        "",
        "Summary:",
        f"  {summary}",
        "",
    ]

    if files_processed:
        report_lines.append("Files Processed:")
        for i, file_path in enumerate(files_processed, start=1):
            report_lines.append(f"  {i}. {file_path}")
        report_lines.append("")

    if notes:
        report_lines.append("Additional Notes:")
        report_lines.append(f"  {notes}")
        report_lines.append("")

    report_lines.extend([
        "Agent Status: Monitoring task complete, ready for next assignment",
        "=" * 70,
        "",
    ])

    report_text = "\n".join(report_lines)

    # Log to file
    try:
        # Ensure parent directory exists
        REPORT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Append to log file
        with open(REPORT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(report_text)

        log_status = "logged"
        # Use stderr to avoid interfering with MCP JSON protocol on stdout
        import sys
        print(f"[report-to-supervisor] Report {report_id} logged to {REPORT_LOG_PATH}", file=sys.stderr, flush=True)
    except Exception as exc:
        log_status = f"log_failed: {exc}"
        import sys
        print(f"[report-to-supervisor] Failed to log report: {exc}", file=sys.stderr, flush=True)

    # Print to stderr for visibility without breaking MCP protocol
    import sys
    print(report_text, file=sys.stderr, flush=True)

    # Future: Send to LilyGO network endpoint
    # network_status = await _send_to_lilygo_network(report_text)

    return {
        "success": True,
        "report_id": report_id,
        "agent": agent_name,
        "supervisor": SUPERVISOR_NAME,
        "timestamp": timestamp.isoformat(),
        "summary": summary,
        "task_type": task_type,
        "status": status,
        "files_processed": files_processed or [],
        "notes": notes,
        "log_status": log_status,
        "log_path": str(REPORT_LOG_PATH),
        "message": f"Report {report_id} from {agent_name} submitted to {SUPERVISOR_NAME}. Agent may now exit monitoring loop.",
        # "network_status": network_status,  # Future LilyGO integration
    }


@mcp.tool()
async def view_supervisor_reports(
    limit: int = 10,
    task_type: Optional[str] = None,
) -> Dict[str, object]:
    """View recent reports submitted to supervisor.

    Args:
        limit: Maximum number of reports to retrieve (default: 10)
        task_type: Filter by task type (optional)

    Returns:
        Dictionary with report history.
    """

    if not REPORT_LOG_PATH.exists():
        return {
            "success": True,
            "total_reports": 0,
            "reports": [],
            "message": "No reports found. Log file does not exist yet.",
        }

    try:
        content = REPORT_LOG_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to read report log: {exc}",
        }

    # Parse reports (simple split by separator)
    report_blocks = content.split("=" * 70)
    parsed_reports = []

    for block in report_blocks:
        if "AGENT REPORT TO SUPERVISOR" in block:
            # Extract key details using simple string parsing
            lines = block.strip().split("\n")
            report_info = {}

            for line in lines:
                if line.startswith("Report ID:"):
                    report_info["report_id"] = line.split(":", 1)[1].strip()
                elif line.startswith("Timestamp:"):
                    report_info["timestamp"] = line.split(":", 1)[1].strip()
                elif line.startswith("Task Type:"):
                    report_info["task_type"] = line.split(":", 1)[1].strip()
                elif line.startswith("Status:"):
                    report_info["status"] = line.split(":", 1)[1].strip()
                elif line.startswith("Summary:"):
                    # Get the next line as summary
                    idx = lines.index(line)
                    if idx + 1 < len(lines):
                        report_info["summary"] = lines[idx + 1].strip()

            if report_info:
                # Filter by task type if specified
                if task_type is None or report_info.get("task_type", "").lower() == task_type.lower():
                    parsed_reports.append(report_info)

    # Sort by report_id (timestamp-based) descending
    parsed_reports.sort(key=lambda x: x.get("report_id", ""), reverse=True)

    # Limit results
    limited_reports = parsed_reports[:limit]

    return {
        "success": True,
        "total_reports": len(parsed_reports),
        "showing": len(limited_reports),
        "reports": limited_reports,
        "log_path": str(REPORT_LOG_PATH),
    }


if __name__ == "__main__":
    mcp.run()
