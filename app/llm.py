import logging
import os
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

from app.config import settings

logger = logging.getLogger(__name__)

# Candidate locations for system prompt file (first existing wins)
_PROMPT_CANDIDATES = [
    Path("/project/prompts/system.md"),
    Path(__file__).parent.parent / "prompts" / "system.md",
]

# Fallback used only if no prompt file is found (keeps tests runnable)
_FALLBACK_PROMPT = "你是一个有用的AI助手。"


def _load_prompt_template() -> str:
    for path in _PROMPT_CANDIDATES:
        if path.exists():
            logger.info("Loading system prompt from %s", path)
            return path.read_text(encoding="utf-8")
    logger.warning("No system prompt file found; using fallback")
    return _FALLBACK_PROMPT


# Loaded once at import; mount prompts/ as a volume for hot-reload during dev
SYSTEM_PROMPT = _load_prompt_template()


def _build_prompt(chat_room_id: str = "") -> str:
    return SYSTEM_PROMPT.format(
        wkteam_api_url=settings.WKTEAM_API_URL,
        wkteam_token=settings.WKTEAM_TOKEN,
        wkteam_wid=settings.WKTEAM_WID,
        chat_room_id=chat_room_id,
    )


async def chat(user_message: str, chat_room_id: str = "") -> str:
    """Run Claude Agent with built-in tools."""
    result = ""
    prompt = _build_prompt(chat_room_id)

    def _on_stderr(line: str):
        logger.warning("CLI stderr: %s", line.strip())

    try:
        async for message in query(
            prompt=user_message,
            options=ClaudeAgentOptions(
                system_prompt=prompt,
                allowed_tools=["WebFetch", "WebSearch", "Bash", "Read", "Write"],
                permission_mode="acceptEdits",
                max_turns=10,
                stderr=_on_stderr,
                cwd="/project",
                setting_sources=["project"],
            ),
        ):
            if isinstance(message, ResultMessage) and message.result:
                result = message.result
    except Exception:
        logger.exception("Agent SDK query failed")
        raise

    return result or "无法生成回复"


async def extract(extraction_prompt: str) -> str:
    """Run a lightweight extraction call without tools, used for post-response memory update."""
    result = ""

    try:
        async for message in query(
            prompt=extraction_prompt,
            options=ClaudeAgentOptions(
                system_prompt="你是信息提取助手。严格按要求输出，不要解释。",
                allowed_tools=[],
                permission_mode="default",
                max_turns=1,
            ),
        ):
            if isinstance(message, ResultMessage) and message.result:
                result = message.result
    except Exception:
        logger.exception("Extraction call failed")
        return ""

    return result.strip()
