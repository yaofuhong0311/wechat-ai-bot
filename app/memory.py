"""Two-tier persistent memory system.

Directory layout:
    /project/memory/
    ├── groups/{group_id}/
    │   ├── history.jsonl   ← raw Q&A log, appended per exchange
    │   └── summary.md      ← compressed long-term summary
    └── users/{wxid}.md     ← free-text user profile, CC-maintained
"""
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

MEMORY_DIR = "/project/memory"
GROUPS_DIR = os.path.join(MEMORY_DIR, "groups")
USERS_DIR = os.path.join(MEMORY_DIR, "users")

MAX_HISTORY = 100
COMPRESS_THRESHOLD = 80
MAX_SUMMARY_CHARS = 5000
MAX_USER_PROFILE_CHARS = 2000


# ---------------------------------------------------------------------------
# Group memory
# ---------------------------------------------------------------------------


def _group_dir(group_id: str) -> str:
    path = os.path.join(GROUPS_DIR, group_id)
    os.makedirs(path, exist_ok=True)
    return path


def _history_path(group_id: str) -> str:
    return os.path.join(_group_dir(group_id), "history.jsonl")


def _summary_path(group_id: str) -> str:
    return os.path.join(_group_dir(group_id), "summary.md")


def save_exchange(group_id: str, user: str, question: str, reply: str):
    """Append a Q&A exchange to the group's history."""
    path = _history_path(group_id)
    entry = {
        "ts": time.time(),
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "user": user,
        "question": question[:500],
        "reply": reply[:1000],
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_history(group_id: str, limit: int = 20) -> list[dict]:
    path = _history_path(group_id)
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries[-limit:]


def load_summary(group_id: str) -> str:
    path = _summary_path(group_id)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_summary(group_id: str, summary: str):
    path = _summary_path(group_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(summary)


def count_history(group_id: str) -> int:
    path = _history_path(group_id)
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def needs_compression(group_id: str) -> bool:
    return count_history(group_id) > MAX_HISTORY


def needs_summary_compression(group_id: str) -> bool:
    return len(load_summary(group_id)) > MAX_SUMMARY_CHARS


def get_entries_to_compress(group_id: str) -> tuple[list[dict], list[dict]]:
    """Split history into (to_compress, to_keep)."""
    path = _history_path(group_id)
    if not os.path.exists(path):
        return [], []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    split_at = len(entries) - (MAX_HISTORY - COMPRESS_THRESHOLD)
    return entries[:split_at], entries[split_at:]


def rewrite_history(group_id: str, entries: list[dict]):
    path = _history_path(group_id)
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def format_entries_for_compression(entries: list[dict]) -> str:
    lines = []
    for entry in entries:
        t = entry.get("time", "")
        user = entry.get("user", "")
        q = entry.get("question", "")
        r = entry.get("reply", "")
        lines.append(f"[{t}] {user}: {q}")
        lines.append(f"bot: {r[:200]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# User memory
# ---------------------------------------------------------------------------


def _user_path(wxid: str) -> str:
    os.makedirs(USERS_DIR, exist_ok=True)
    # Sanitize wxid to prevent path traversal
    safe = wxid.replace("/", "_").replace("..", "_")
    return os.path.join(USERS_DIR, f"{safe}.md")


def load_user_profile(wxid: str) -> str:
    path = _user_path(wxid)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def save_user_profile(wxid: str, profile: str):
    path = _user_path(wxid)
    with open(path, "w", encoding="utf-8") as f:
        f.write(profile.strip() + "\n")


def needs_user_profile_compression(wxid: str) -> bool:
    return len(load_user_profile(wxid)) > MAX_USER_PROFILE_CHARS


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def build_memory_context(group_id: str, wxid: str = "") -> str:
    """Assemble the long-term + short-term memory block for a prompt."""
    parts = []

    if wxid:
        profile = load_user_profile(wxid)
        if profile:
            parts.append(f"[用户档案: {wxid}]\n{profile}")

    summary = load_summary(group_id)
    if summary:
        parts.append(f"[长期记忆摘要]\n{summary}")

    history = load_history(group_id, limit=20)
    if history:
        lines = ["[最近的对话记录]"]
        for entry in history:
            t = entry.get("time", "")
            user = entry.get("user", "")
            q = entry.get("question", "")
            r = entry.get("reply", "")
            lines.append(f"[{t}] {user} 问: {q}")
            lines.append(f"[{t}] bot 答: {r[:200]}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)
