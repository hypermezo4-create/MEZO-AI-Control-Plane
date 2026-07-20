import html
import re

from mezo_control_plane.core.domain import EvidenceItem, TaskRecord

_SENSITIVE = re.compile(
    r"(?i)(api[_-]?key|token|secret|private[_-]?key|authorization)\s*[:=]\s*\S+"
)


def redact(text: str) -> str:
    return _SENSITIVE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)


def escape(text: str) -> str:
    return html.escape(redact(text), quote=False)


def chunks(text: str, maximum: int = 4_000) -> list[str]:
    if maximum < 32:
        raise ValueError("Telegram chunk size is too small")
    output: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= maximum:
            output.append(remaining)
            break
        boundary = remaining.rfind("\n", 0, maximum + 1)
        if boundary < maximum // 2:
            boundary = maximum
        output.append(remaining[:boundary])
        remaining = remaining[boundary:].lstrip("\n")
    return output or [""]


def task_status(task: TaskRecord) -> str:
    return (
        f"<b>Task</b> <code>{escape(str(task.id))}</code>\n"
        f"<b>State</b> {escape(task.state.value)}\n"
        f"<b>Repository</b> {escape(task.request.repository)}"
    )


def evidence_summary(items: list[EvidenceItem]) -> str:
    if not items:
        return "No evidence has been recorded."
    lines = [f"• <b>{escape(item.kind)}</b>: {escape(item.summary)}" for item in items]
    return "\n".join(lines)
