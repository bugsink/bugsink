"""
Renders a high-level Markdown summary of an Issue, suitable for human reading or LLM consumption.

Includes:
- Issue identity & status
- Event counts and time range
- Release / environment / deployment info
- Tag breakdown with percentages
- Turning-point history (state changes + comments)
- Latest-event stacktrace
- Relative browser links
"""

import json
from compat.timestamp import format_timestamp
from events.markdown_stacktrace import render_stacktrace_md
from .models import TurningPointKind


def _fmt(dt):
    """ISO-8601 UTC timestamp, or 'N/A'."""
    if dt is None:
        return "N/A"
    return format_timestamp(dt)


def _status(issue):
    if issue.is_resolved:
        return "resolved"
    if issue.is_muted:
        return "muted"
    return "open"


def _turning_point_label(tp):
    return TurningPointKind(tp.kind).label


def _turning_point_detail(tp):
    """Return a short human-readable string for the metadata of a turning point."""
    try:
        meta = json.loads(tp.metadata) if tp.metadata else {}
    except (ValueError, TypeError):
        meta = {}

    if "resolved_unconditionally" in meta:
        return "resolved unconditionally"
    if "resolve_by_next" in meta:
        return "resolved by next release"
    if "resolved_release" in meta:
        return f"resolved at release `{meta['resolved_release']}`"
    if "mute_unconditionally" in meta:
        return "muted unconditionally"
    if "mute_for" in meta:
        d = meta["mute_for"]
        plural_s = "" if d.get("nr_of_periods") == 1 else "s"
        return f"muted for {d.get('nr_of_periods')} {d.get('period_name')}{plural_s}"
    if "mute_until" in meta:
        d = meta["mute_until"]
        plural_s = "" if d.get("nr_of_periods") == 1 else "s"
        return f"muted until >{d.get('volume')} events per {d.get('nr_of_periods')} {d.get('period_name')}{plural_s}"

    return ""


def render_issue_md(issue):
    lines = []

    # ── Title ────────────────────────────────────────────────────────────────
    lines += [
        f"# {issue.title()}",
        f"**{issue.friendly_id()}** · {_status(issue)}",
        "",
    ]

    # ── Links ────────────────────────────────────────────────────────────────
    issue_url = f"/issues/issue/{issue.id}/event/last/"
    tags_url = f"/issues/issue/{issue.id}/tags/"
    history_url = f"/issues/issue/{issue.id}/history/"
    events_url = f"/issues/issue/{issue.id}/events/"
    grouping_url = f"/issues/issue/{issue.id}/grouping/"

    lines += [
        "## Links",
        "",
        f"- [Issue (latest event)]({issue_url})",
        f"- [Tags]({tags_url})",
        f"- [Event list]({events_url})",
        f"- [History]({history_url})",
        f"- [Grouping]({grouping_url})",
        "",
    ]

    # ── Identity & status ────────────────────────────────────────────────────
    lines += [
        "## Identity",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Issue ID | `{issue.id}` |",
        f"| Friendly ID | `{issue.friendly_id()}` |",
        f"| Project | `{issue.project.slug}` |",
        f"| Status | {_status(issue)} |",
        f"| Is resolved | {issue.is_resolved} |",
        f"| Resolved by next release | {issue.is_resolved_by_next_release} |",
        f"| Is muted | {issue.is_muted} |",
        "",
    ]

    # ── Event counts & time range ─────────────────────────────────────────────
    lines += [
        "## Event Counts",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Digested event count | {issue.digested_event_count} |",
        f"| Stored event count | {issue.stored_event_count} |",
        f"| First seen | {_fmt(issue.first_seen)} |",
        f"| Last seen | {_fmt(issue.last_seen)} |",
        "",
    ]

    # ── Last frame info ───────────────────────────────────────────────────────
    if any([issue.last_frame_filename, issue.last_frame_module, issue.last_frame_function]):
        lines += [
            "## Last Frame",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
        ]
        if issue.last_frame_filename:
            lines.append(f"| Filename | `{issue.last_frame_filename}` |")
        if issue.last_frame_module:
            lines.append(f"| Module | `{issue.last_frame_module}` |")
        if issue.last_frame_function:
            lines.append(f"| Function | `{issue.last_frame_function}` |")
        lines.append("")

    # ── Transaction ───────────────────────────────────────────────────────────
    if issue.transaction:
        lines += [
            "## Transaction",
            "",
            f"`{issue.transaction}`",
            "",
        ]

    # ── Release / deployment info ─────────────────────────────────────────────
    events_at = issue.get_events_at()
    fixed_at = issue.get_fixed_at()
    if events_at or fixed_at:
        lines += ["## Release Info", ""]
        if events_at:
            releases = [r if r else "(no release)" for r in events_at]
            lines.append(f"**Seen in releases:** {', '.join(f'`{r}`' for r in releases)}")
        if fixed_at:
            fixes = [r if r else "(no release)" for r in fixed_at]
            lines.append(f"**Fixed at releases:** {', '.join(f'`{r}`' for r in fixes)}")
        lines.append("")

    # ── Mute conditions ───────────────────────────────────────────────────────
    if issue.is_muted:
        lines += ["## Mute Conditions", ""]
        if issue.unmute_after:
            lines.append(f"- Unmute after: {_fmt(issue.unmute_after)}")
        vbcs = issue.get_unmute_on_volume_based_conditions()
        for vbc in vbcs:
            lines.append(f"- Unmute when >{vbc.volume} events per {vbc.nr_of_periods} {vbc.period}")
        if not issue.unmute_after and not vbcs:
            lines.append("- Muted unconditionally")
        lines.append("")

    # ── Tags ──────────────────────────────────────────────────────────────────
    tags_all = issue.tags_all
    if tags_all:
        lines += ["## Tags", ""]
        for tag_group in tags_all:
            if not tag_group:
                continue
            # key is on the first real IssueTag object (dict entries are the "Other…" bucket)
            first = tag_group[0]
            key_name = first.key.key if hasattr(first, "key") else "unknown"
            lines.append(f"### `{key_name}`")
            lines.append("")
            lines.append("| Value | Count | % |")
            lines.append("|-------|------:|--:|")
            for entry in tag_group:
                if hasattr(entry, "value"):
                    val = entry.value.value
                    count = entry.count
                    pct = getattr(entry, "pct", "")
                else:
                    # dict — the "Other…" bucket
                    val = entry["value"].value
                    count = entry["count"]
                    pct = entry.get("pct", "")
                pct_str = f"{pct}%" if pct != "" else ""
                lines.append(f"| {val} | {count} | {pct_str} |")
            lines.append("")

    # ── History (turning points) ──────────────────────────────────────────────
    turning_points = issue.turningpoint_set_all()
    if turning_points:
        lines += ["## History", ""]
        for tp in turning_points:
            who = tp.user.username if tp.user else "system"
            label = _turning_point_label(tp)
            detail = _turning_point_detail(tp)
            detail_str = f" — {detail}" if detail else ""
            comment_str = f"\n  > {tp.comment}" if tp.comment else ""
            lines.append(f"- **{_fmt(tp.timestamp)}** · {label}{detail_str} _(by {who})_{comment_str}")
        lines.append("")

    # ── Latest event stacktrace ───────────────────────────────────────────────
    last_event = issue.event_set.order_by("-digest_order").first()
    if last_event:
        event_url = f"/issues/issue/{issue.id}/event/{last_event.id}/"
        event_details_url = f"/issues/issue/{issue.id}/event/{last_event.id}/details/"
        event_md_url = f"/events/event/{last_event.id}/md/"
        lines += [
            "## Latest Event",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Event ID | `{last_event.id}` |",
            f"| External ID | `{last_event.event_id}` |",
            f"| Timestamp | {_fmt(last_event.timestamp)} |",
            f"| Ingested at | {_fmt(last_event.ingested_at)} |",
            f"| [View stacktrace]({event_url}) | [View details]({event_details_url}) | [Markdown]({event_md_url}) |",
            "",
            "### Stacktrace",
            "",
            render_stacktrace_md(last_event, in_app_only=False, include_locals=True),
            "",
        ]

    return "\n".join(lines).strip()
