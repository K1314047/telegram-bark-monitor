import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import aiohttp
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError

import config


# ---------- logging ----------
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("telegram-bark")


# ---------- database ----------
class DedupDB:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_messages (
                fingerprint TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL
            )
        """)
        self.conn.commit()

    def cleanup(self, ttl: int):
        cutoff = int(datetime.now(timezone.utc).timestamp()) - ttl
        self.conn.execute("DELETE FROM sent_messages WHERE created_at < ?", (cutoff,))
        self.conn.commit()

    def seen(self, fingerprint: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sent_messages WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        return row is not None

    def add(self, fingerprint: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO sent_messages(fingerprint, created_at) VALUES (?, ?)",
            (fingerprint, int(datetime.now(timezone.utc).timestamp())),
        )
        self.conn.commit()


# ---------- helpers ----------
def parse_proxy(proxy: str):
    if not proxy:
        return None

    p = urlparse(proxy)
    if p.scheme not in {"socks5", "socks5h", "http"}:
        raise ValueError("TELEGRAM_PROXY only supports socks5:// or http://")

    # Telethon/PySocks tuple:
    # (proxy_type, addr, port, rdns, username, password)
    if p.scheme in {"socks5", "socks5h"}:
        import socks
        return (
            socks.SOCKS5,
            p.hostname,
            p.port,
            p.scheme == "socks5h",
            p.username,
            p.password,
        )

    return {
        "proxy_type": "http",
        "addr": p.hostname,
        "port": p.port,
        "username": p.username,
        "password": p.password,
    }


def normalize_channel(value: str):
    value = value.strip()
    if not value:
        return value
    return value.rstrip("/")


def is_private_invite_link(value: str) -> bool:
    return bool(
        re.match(
            r"^(?:https?://)?(?:www\.)?t\.me/\+[A-Za-z0-9_-]+/?$",
            value,
            re.IGNORECASE,
        )
    )


def is_channel_id(value: str) -> bool:
    return bool(re.fullmatch(r"-?\d+", value.strip()))


async def resolve_channel(client: TelegramClient, item: str):
    """解析公开频道、私人频道邀请链接、数字频道 ID。"""
    item = normalize_channel(item)

    if is_private_invite_link(item):
        from telethon.tl.functions.messages import CheckChatInviteRequest
        from telethon.tl.types import ChatInviteAlready

        invite_hash = item.rstrip("/").split("/")[-1][1:]
        result = await client(CheckChatInviteRequest(invite_hash))

        if isinstance(result, ChatInviteAlready):
            return result.chat

        raise RuntimeError(
            "该私人频道邀请链接有效，但当前 Telegram 账号尚未加入频道。"
            "请先加入频道，然后重新启动监控程序。"
        )

    if is_channel_id(item):
        return await client.get_entity(int(item))

    return await client.get_entity(item)


def matches_keyword(text: str) -> bool:
    if config.FILTER_MODE == "all":
        return True

    if config.FILTER_MODE != "keyword":
        logger.warning("Unknown FILTER_MODE=%s; falling back to keyword mode", config.FILTER_MODE)

    if not config.KEYWORDS:
        logger.warning("FILTER_MODE=keyword but KEYWORDS is empty; no messages will be sent")
        return False

    haystack = text.lower() if config.KEYWORD_CASE_INSENSITIVE else text
    for keyword in config.KEYWORDS:
        needle = keyword.lower() if config.KEYWORD_CASE_INSENSITIVE else keyword
        if needle in haystack:
            return True
    return False


def clean_text(text: str, max_len: int = 3500) -> str:
    text = re.sub(r"\n{4,}", "\n\n", text.strip())
    if len(text) > max_len:
        text = text[:max_len - 20] + "\n…（内容已截断）"
    return text


def message_url(event, chat):
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{event.message.id}"

    # Private/supergroup message links may use this format when available.
    chat_id = getattr(chat, "id", None)
    if chat_id:
        internal_id = str(chat_id)
        if internal_id.startswith("-100"):
            internal_id = internal_id[4:]
        return f"https://t.me/c/{internal_id}/{event.message.id}"

    return ""


def fingerprint(event, chat) -> str:
    chat_id = getattr(chat, "id", "")
    msg_id = getattr(event.message, "id", "")
    text = getattr(event.message, "message", "") or ""
    raw = f"{chat_id}:{msg_id}:{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------- Bark ----------
async def send_bark(session: aiohttp.ClientSession, title: str, body: str, url: str = ""):
    if not config.BARK_KEY:
        raise RuntimeError("BARK_KEY is empty")

    endpoint = f"{config.BARK_URL}/{quote(config.BARK_KEY, safe='')}/{quote(title, safe='')}/{quote(body, safe='')}"

    params = {}
    if config.BARK_SOUND:
        params["sound"] = config.BARK_SOUND
    if config.BARK_GROUP:
        params["group"] = config.BARK_GROUP
    if config.BARK_LEVEL:
        params["level"] = config.BARK_LEVEL
    if url:
        params["url"] = url

    timeout = aiohttp.ClientTimeout(total=15)
    async with session.get(endpoint, params=params, timeout=timeout) as resp:
        data = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"Bark HTTP {resp.status}: {data[:500]}")
        logger.info("Bark sent: HTTP %s", resp.status)


# ---------- Telegram ----------
async def login_interactively(client: TelegramClient):
    await client.connect()

    if await client.is_user_authorized():
        logger.info("Telegram session already authorized.")
        return

    if not config.TG_PHONE:
        raise RuntimeError("TG_PHONE is required for first login.")

    logger.info("First login: requesting Telegram login code...")
    await client.send_code_request(config.TG_PHONE)

    code = input("请输入 Telegram 登录验证码: ").strip()

    try:
        await client.sign_in(config.TG_PHONE, code)
    except SessionPasswordNeededError:
        password = input("请输入 Telegram 两步验证密码: ")
        await client.sign_in(password=password)

    if not await client.is_user_authorized():
        raise RuntimeError("Telegram authorization failed.")

    logger.info("Telegram login successful. Session saved.")


async def main():
    if not config.TG_API_ID or not config.TG_API_HASH:
        raise RuntimeError("TG_API_ID / TG_API_HASH are required.")

    if not config.BARK_KEY:
        raise RuntimeError("BARK_KEY is required.")

    if not config.CHANNELS:
        raise RuntimeError("CHANNELS is empty.")

    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    db = DedupDB(config.DB_PATH)
    db.cleanup(config.DEDUP_TTL_SECONDS)

    session_path = "/app/data/telegram"
    proxy = parse_proxy(config.TELEGRAM_PROXY)

    client = TelegramClient(
        session_path,
        config.TG_API_ID,
        config.TG_API_HASH,
        proxy=proxy,
        auto_reconnect=True,
        request_retries=5,
        connection_retries=5,
        flood_sleep_threshold=60,
        device_model="Telegram-Bark-Monitor",
        app_version="1.0.0",
        system_version="Docker",
    )

    await login_interactively(client)

    # Resolve public usernames, private invite links, and numeric IDs once.
    channels = [normalize_channel(x) for x in config.CHANNELS]
    entities = []

    for item in channels:
        try:
            entity = await resolve_channel(client, item)
            entities.append(entity)

            name = (
                getattr(entity, "title", None)
                or getattr(entity, "username", None)
                or str(item)
            )
            logger.info("Monitoring channel: %s (%s)", name, item)

        except Exception as exc:
            logger.error("Cannot access channel %s: %s", item, exc)

    if not entities:
        raise RuntimeError("No configured channels could be resolved.")

    http_connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=http_connector) as http:

        @client.on(events.NewMessage(chats=entities))
        async def handler(event):
            try:
                text = event.raw_text or ""
                chat = await event.get_chat()
                chat_title = getattr(chat, "title", None) or getattr(chat, "username", None) or "Telegram"

                if not matches_keyword(text):
                    logger.debug("Filtered: %s", chat_title)
                    return

                fp = fingerprint(event, chat)

                if config.DEDUP_ENABLED and db.seen(fp):
                    logger.debug("Duplicate skipped: %s/%s", chat_title, event.message.id)
                    return

                body = clean_text(text)
                if not body:
                    body = "（媒体消息，无文字内容）"

                title = f"【TG】{chat_title}"
                url = message_url(event, chat)

                await send_bark(http, title, body, url=url)

                if config.DEDUP_ENABLED:
                    db.add(fp)

                logger.info(
                    "Forwarded: %s | message_id=%s",
                    chat_title,
                    event.message.id,
                )

            except Exception:
                logger.exception("Error while processing Telegram message")

        logger.info("Telegram → Bark monitor started.")
        logger.info("Filter mode: %s | Keywords: %s", config.FILTER_MODE, ", ".join(config.KEYWORDS))
        await client.run_until_disconnected()


def print_help():
    print("""
Telegram → Bark Monitor

First-time login:
  docker compose run --rm telegram-bark python main.py --login

Normal start:
  docker compose up -d --build

Logs:
  docker logs -f telegram-bark-monitor

After login, the session is stored in:
  ./data/telegram.session
""")


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print_help()
        raise SystemExit(0)

    # --login uses the same normal startup path; after authorization the session remains saved.
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped.")
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        raise
