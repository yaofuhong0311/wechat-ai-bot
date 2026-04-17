import httpx
import logging

from app.config import settings

logger = logging.getLogger(__name__)


async def send_text(to_wcid: str, content: str, at: str | None = None) -> dict:
    """Send text message via wkteam API."""
    url = f"{settings.WKTEAM_API_URL}/sendText"
    headers = {
        "Content-Type": "application/json",
        "Authorization": settings.WKTEAM_TOKEN,
    }
    payload = {
        "wId": settings.WKTEAM_WID,
        "wcId": to_wcid,
        "content": content,
    }
    if at:
        payload["at"] = at

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        data = resp.json()

    if data.get("code") == "1000":
        logger.info("Message sent to %s", to_wcid)
    else:
        logger.error("Send failed: %s", data)

    return data


async def download_image(msg_id: int, content_xml: str) -> str | None:
    """Download image via wkteam API, return image URL."""
    url = f"{settings.WKTEAM_API_URL}/getMsgImg"
    headers = {
        "Content-Type": "application/json",
        "Authorization": settings.WKTEAM_TOKEN,
    }
    payload = {
        "wId": settings.WKTEAM_WID,
        "msgId": msg_id,
        "content": content_xml,
        "type": 0,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        data = resp.json()

    if data.get("code") == "1000" and data.get("data", {}).get("url"):
        return data["data"]["url"]

    # Retry with HD
    payload["type"] = 1
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        data = resp.json()

    if data.get("code") == "1000" and data.get("data", {}).get("url"):
        return data["data"]["url"]

    logger.error("Image download failed: %s", data)
    return None


async def download_file(msg_id: int, content_xml: str) -> str | None:
    """Download file via wkteam API, return file URL. Retries on failure."""
    import asyncio
    url = f"{settings.WKTEAM_API_URL}/getMsgFile"
    headers = {
        "Content-Type": "application/json",
        "Authorization": settings.WKTEAM_TOKEN,
    }
    payload = {
        "wId": settings.WKTEAM_WID,
        "msgId": msg_id,
        "content": content_xml,
    }

    for attempt in range(3):
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            data = resp.json()

        if data.get("code") == "1000" and data.get("data", {}).get("url"):
            return data["data"]["url"]

        logger.warning("File download attempt %d failed: %s", attempt + 1, data.get("message", ""))
        if attempt < 2:
            await asyncio.sleep(5)

    logger.error("File download failed after 3 attempts")
    return None


async def set_callback(callback_url: str) -> dict:
    """Set webhook callback URL in wkteam."""
    url = f"{settings.WKTEAM_API_URL}/setHttpCallbackUrl"
    headers = {
        "Content-Type": "application/json",
        "Authorization": settings.WKTEAM_TOKEN,
    }
    payload = {
        "httpUrl": callback_url,
        "type": 2,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        data = resp.json()

    logger.info("Set callback result: %s", data)
    return data
