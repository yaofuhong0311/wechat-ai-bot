#!/usr/bin/env python3
"""Headless browser page fetcher.

Used by the AI bot to retrieve dynamic content that WebFetch cannot handle
(B站 video pages, 小红书 notes, SPA sites, etc).

Usage:
    python fetch_page.py <url>
    python fetch_page.py <url> --wait 3

Outputs extracted text to stdout.

The script tries to be resilient: if Playwright is not installed or the page
fails to load, it falls back to a plain HTTP GET via requests so callers
always get something back.
"""
import argparse
import re
import sys


PLAIN_TEXT_LIMIT = 8000


def _clean_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    # Remove script/style blocks entirely
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace tags with space
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode a few common HTML entities without pulling in html.parser
    replacements = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:PLAIN_TEXT_LIMIT]


def fetch_via_playwright(url: str, wait_seconds: float = 2.0) -> str:
    """Render the page in a headless browser and extract visible text."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(int(wait_seconds * 1000))

        title = page.title()
        body_text = page.evaluate("document.body ? document.body.innerText : ''")
        browser.close()

    lines = [f"[页面标题] {title}", "", "[正文]", body_text.strip()]
    joined = "\n".join(lines)
    return joined[:PLAIN_TEXT_LIMIT]


def fetch_via_http(url: str) -> str:
    """Fallback for when Playwright is unavailable."""
    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as c:
        resp = c.get(url)
        resp.raise_for_status()
        return _clean_text(resp.text)


def main():
    parser = argparse.ArgumentParser(description="Fetch and extract text from a URL.")
    parser.add_argument("url", help="Page URL")
    parser.add_argument("--wait", type=float, default=2.0, help="Seconds to wait after DOM load")
    parser.add_argument("--no-browser", action="store_true", help="Skip Playwright, use plain HTTP")
    args = parser.parse_args()

    try:
        if args.no_browser:
            print(fetch_via_http(args.url))
            return

        try:
            print(fetch_via_playwright(args.url, wait_seconds=args.wait))
        except ImportError:
            print("[警告] playwright 未安装，使用普通HTTP模式", file=sys.stderr)
            print(fetch_via_http(args.url))
        except Exception as e:
            print(f"[警告] 浏览器模式失败 ({type(e).__name__}: {e})，回退到HTTP", file=sys.stderr)
            print(fetch_via_http(args.url))
    except Exception as e:
        print(f"[错误] 抓取失败: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
