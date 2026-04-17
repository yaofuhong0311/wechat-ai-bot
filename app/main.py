import logging
import re
import time
import base64
import tempfile
from collections import defaultdict, deque

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app import llm, wechat, memory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="panorama-data-sync", docs_url=None, redoc_url=None)

# Realtime group chat buffer: {group_id: deque([(sender, type, summary, timestamp), ...])}
MSG_HISTORY: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))

MSG_TYPE_LABELS = {
    "80001": "文字",
    "80002": "图片",
    "80003": "视频",
    "80004": "语音",
    "80005": "名片",
    "80006": "文件",
    "80008": "文件",
    "80009": "文件",
    "80010": "链接/小程序",
    "80011": "合并聊天记录",
    "80014": "引用消息",
    "80018": "撤回消息",
}


async def _record_msg(group_id: str, sender: str, msg_type: str, content: str, data: dict = None):
    """Record a message to group chat buffer."""
    label = MSG_TYPE_LABELS.get(msg_type, f"消息({msg_type})")
    if msg_type == "80001":
        summary = content[:200]
    elif msg_type == "80002":
        summary = await _download_and_save_image(data) if data else "[图片]"
    elif msg_type in ("80006", "80008", "80009"):
        summary = await _download_and_save_file(data, content) if data else "[文件]"
    elif msg_type == "80011":
        summary = _parse_merged_chat_records(content)
    elif msg_type == "80014":
        title_match = re.search(r"<title>(.*?)</title>", content)
        refer_content = re.search(r"<content>(.*?)</content>", content)
        refer_name = re.search(r"<displayname>(.*?)</displayname>", content)
        parts = []
        if title_match:
            parts.append(title_match.group(1))
        if refer_name and refer_content:
            parts.append(f"(引用 {refer_name.group(1)}: {refer_content.group(1)[:80]})")
        summary = " ".join(parts) if parts else "[引用消息]"
    elif msg_type == "80018":
        summary = "[撤回了一条消息]"
    elif msg_type == "80010":
        title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", content)
        url = re.search(r"<url>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</url>", content)
        des = re.search(r"<des>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</des>", content)
        parts = []
        if title:
            parts.append(title.group(1))
        if des:
            parts.append(des.group(1)[:100])
        if url:
            parts.append(f"url={url.group(1)}")
        summary = f"[链接] {' | '.join(parts)}" if parts else "[链接]"
    else:
        text = re.sub(r"<[^>]+>", "", content).strip()
        summary = f"[{label}] {text[:100]}" if text else f"[{label}]"
    MSG_HISTORY[group_id].append((sender, label, summary, time.time()))


async def _download_and_save_image(data: dict) -> str:
    msg_id = data.get("msgId")
    content_xml = data.get("content", "")
    if msg_id and content_xml:
        try:
            image_url = await wechat.download_image(msg_id, content_xml)
            if image_url:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
                    resp = await c.get(image_url)
                    resp.raise_for_status()
                    suffix = ".png" if b"PNG" in resp.content[:8] else ".jpg"
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="/tmp")
                    tmp.write(resp.content)
                    tmp.close()
                    return f"[图片已保存: {tmp.name}，可用Read工具查看]"
        except Exception:
            logger.warning("Image download failed for msgId=%s", msg_id)
    thumb_b64 = data.get("img", "")
    if thumb_b64:
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg", dir="/tmp")
            tmp.write(base64.b64decode(thumb_b64))
            tmp.close()
            return f"[图片缩略图已保存: {tmp.name}，可用Read工具查看]"
        except Exception:
            pass
    return "[图片，下载失败]"


def _parse_merged_chat_records(content_xml: str) -> str:
    record_match = re.search(r"<recorditem><!\[CDATA\[(.*?)\]\]></recorditem>", content_xml, re.DOTALL)
    if not record_match:
        record_match = re.search(r"<recorditem>(.*?)</recorditem>", content_xml, re.DOTALL)
    if not record_match:
        return "[合并聊天记录，解析失败]"
    record_xml = record_match.group(1)
    title_match = re.search(r"<title>(.*?)</title>", record_xml)
    title = title_match.group(1) if title_match else "聊天记录"
    messages = []
    items = re.finditer(
        r"<dataitem[^>]*datatype=\"(\d+)\"[^>]*>.*?"
        r"<sourcename>(.*?)</sourcename>.*?"
        r"<datadesc>(.*?)</datadesc>.*?"
        r"</dataitem>",
        record_xml, re.DOTALL,
    )
    for item in items:
        datatype, sender, desc = item.group(1), item.group(2), item.group(3)
        if datatype == "1":
            messages.append(f"{sender}: {desc}")
        elif datatype == "2":
            messages.append(f"{sender}: [图片]")
        elif datatype == "3":
            messages.append(f"{sender}: [视频]")
        elif datatype == "4":
            messages.append(f"{sender}: [链接] {desc}")
        else:
            messages.append(f"{sender}: [{desc[:50]}]")
    if not messages:
        desc_match = re.search(r"<desc>(.*?)</desc>", record_xml, re.DOTALL)
        if desc_match:
            return f"[合并聊天记录: {title}]\n{desc_match.group(1)[:500]}"
        return f"[合并聊天记录: {title}，内容解析失败]"
    chat_text = "\n".join(messages[:30])
    return f"[合并聊天记录: {title}]\n{chat_text}"


async def _download_and_save_file(data: dict, content_xml: str) -> str:
    msg_id = data.get("msgId")
    filename_match = re.search(r"<title>(.*?)</title>", content_xml)
    filename = filename_match.group(1) if filename_match else "file"
    if msg_id and content_xml:
        try:
            file_url = await wechat.download_file(msg_id, content_xml)
            if file_url:
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
                    resp = await c.get(file_url)
                    resp.raise_for_status()
                    ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir="/tmp")
                    tmp.write(resp.content)
                    tmp.close()
                    return f"[文件已保存: {tmp.name}，文件名: {filename}，可用Read工具或Bash查看]"
        except Exception:
            logger.warning("File download failed for msgId=%s", msg_id)
    return f"[文件: {filename}，下载失败]"


def _build_realtime_context(group_id: str) -> str:
    """Build realtime group chat context from buffer."""
    history = MSG_HISTORY.get(group_id)
    if not history:
        return ""
    lines = ["[实时群聊消息]"]
    for sender, label, summary, ts in history:
        t = time.strftime("%H:%M", time.localtime(ts))
        lines.append(f"[{t}] {sender}: {summary}")
    return "\n".join(lines)


def _is_group_allowed(group_id: str) -> bool:
    if not settings.ALLOWED_GROUPS:
        return True
    allowed = [g.strip() for g in settings.ALLOWED_GROUPS.split(",") if g.strip()]
    return group_id in allowed


@app.get("/health")
@app.get("/deploy/sync-api/health")
async def health():
    return {"status": "ok"}


@app.post("/deploy/sync-api/v1/sync")
async def webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"code": "ok"})

    msg_type = str(body.get("messageType", ""))
    data = body.get("data", {})

    if data.get("self"):
        return JSONResponse({"code": "ok"})

    # Record ALL group messages to realtime buffer
    from_group = data.get("fromGroup", "")
    if from_group and msg_type.startswith("8"):
        from_user = data.get("fromUser", "")
        content = data.get("content", "")
        await _record_msg(from_group, from_user, msg_type, content, data)

    # Only process @mentions
    if msg_type == "80001":
        at_list = data.get("atlist", [])
        if at_list and settings.BOT_WCID in at_list:
            await handle_group_text(data)

    return JSONResponse({"code": "ok"})


async def handle_group_text(data: dict):
    from_group = data.get("fromGroup", "")
    from_user = data.get("fromUser", "")
    content = data.get("content", "")

    if not _is_group_allowed(from_group):
        logger.warning("Blocked: group %s not in whitelist", from_group)
        return

    cleaned = re.sub(r"@\S+\s*", "", content).strip()
    if not cleaned:
        cleaned = "请分析上面的内容"

    logger.info("Text from %s in %s: %s", from_user, from_group, cleaned[:100])

    # Build full context: memory + realtime chat + user question
    parts = []

    # 1. Long-term memory (user profile + group summary + recent history)
    mem_ctx = memory.build_memory_context(from_group, wxid=from_user)
    if mem_ctx:
        parts.append(mem_ctx)

    # 2. Realtime group chat buffer
    rt_ctx = _build_realtime_context(from_group)
    if rt_ctx:
        parts.append(rt_ctx)

    # 3. User question
    parts.append(f"---\n用户(@你的人: {from_user})说: {cleaned}")

    prompt = "\n\n".join(parts)

    try:
        reply = await llm.chat(prompt, chat_room_id=from_group)
    except Exception as e:
        logger.exception("LLM failed")
        reply = f"服务暂时不可用 ({type(e).__name__})"

    if len(reply) > 4000:
        reply = reply[:3997] + "..."

    # Save to memory
    memory.save_exchange(from_group, from_user, cleaned, reply)

    # Send reply first (don't block on memory maintenance)
    try:
        await wechat.send_text(from_group, reply)
    except Exception:
        logger.exception("Send failed")

    # Memory maintenance (async, after reply)
    try:
        await _update_user_profile(from_user, cleaned, reply)
    except Exception:
        logger.exception("User profile update failed")

    if memory.needs_compression(from_group):
        try:
            await _compress_memory(from_group)
        except Exception:
            logger.exception("Group memory compression failed")


async def _update_user_profile(wxid: str, question: str, reply: str):
    """Forced extraction: scan the exchange for facts worth adding to the user profile.

    Runs after the main reply is sent. Uses a lightweight tool-less call so it stays fast.
    CC may already have updated the profile via Write during the main turn; this is a safety net.
    """
    current = memory.load_user_profile(wxid)

    extraction_prompt = (
        "任务：根据本次对话判断是否有关于【用户本人】的新信息需要更新到档案。\n\n"
        f"用户ID: {wxid}\n"
        f"现有档案:\n{current or '（空）'}\n\n"
        f"本次对话:\n用户: {question}\nbot: {reply}\n\n"
        "规则：\n"
        "- 【严格判断主语】只提取关于发言用户本人的事实，不提取关于其他人的信息\n"
        "- 如果用户在说『他/她/某人如何』，那不是用户本人的信息，忽略\n"
        "- 如果用户在说『我如何』或用户在回答关于自己的问题，才算用户本人信息\n"
        "- 只记录长期事实（体重/水平/车型/常骑路线/偏好/身份）\n"
        "- 忽略一次性问题、天气查询、临时讨论\n"
        "- 如果没有新信息，只输出 NO_UPDATE（不要加任何别的文字）\n"
        "- 如果有新信息，输出【完整的更新后档案文字】（不要加解释、不要markdown、不要代码块）\n"
    )

    output = await llm.extract(extraction_prompt)
    logger.info("User profile extraction for %s: output=%r", wxid, output[:200] if output else None)
    if not output or output.strip() == "NO_UPDATE":
        return

    new_profile = output.strip()
    # Trim if absurdly long; the compression pass would kick in otherwise
    if len(new_profile) > memory.MAX_USER_PROFILE_CHARS * 2:
        new_profile = new_profile[: memory.MAX_USER_PROFILE_CHARS * 2]

    memory.save_user_profile(wxid, new_profile)
    logger.info("Updated user profile for %s (%d chars)", wxid, len(new_profile))

    # Second-level compression if profile itself got bloated
    if memory.needs_user_profile_compression(wxid):
        compress_prompt = (
            "以下用户档案内容太长了，请精简到2000字以内，只保留关键长期事实，"
            "删除重复、临时或琐碎内容。输出纯文本档案：\n\n" + new_profile
        )
        compressed = await llm.extract(compress_prompt)
        if compressed and compressed != "NO_UPDATE":
            memory.save_user_profile(wxid, compressed)


async def _compress_memory(group_id: str):
    """Compress old history into summary."""
    to_compress, to_keep = memory.get_entries_to_compress(group_id)
    if not to_compress:
        return

    text = memory.format_entries_for_compression(to_compress)
    existing_summary = memory.load_summary(group_id)

    compress_prompt = (
        "请将以下对话记录总结成简洁的要点，保留关键信息（人名、地点、约定、重要决定）。"
        "用中文，纯文本，不要markdown格式。控制在500字以内。\n\n"
    )
    if existing_summary:
        compress_prompt += f"已有的历史摘要：\n{existing_summary}\n\n"
    compress_prompt += f"需要总结的新对话：\n{text}"

    summary = await llm.chat(compress_prompt, chat_room_id=group_id)

    # If summary itself is too large, re-compress
    if memory.needs_summary_compression(group_id):
        re_compress_prompt = (
            "以下是之前的对话摘要，内容太长了，请精简到500字以内，只保留最重要的信息：\n\n"
            f"{summary}"
        )
        summary = await llm.chat(re_compress_prompt, chat_room_id=group_id)

    memory.save_summary(group_id, summary)
    memory.rewrite_history(group_id, to_keep)
    logger.info("Memory compressed for group %s: %d entries → summary", group_id, len(to_compress))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
