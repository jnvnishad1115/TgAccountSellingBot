"""
otp_fetcher.py — Telethon based OTP Fetcher
=============================================
Uses Telethon instead of Pyrogram.
Session string generated via Telethon's StringSession.
"""

import re
import asyncio
import logging
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH

logger = logging.getLogger(__name__)

TELEGRAM_OTP_SENDER = 777000

OTP_PATTERNS = [
    r'(\d{5,6})\s+is your',
    r'code[:\s]+(\d{5,6})',
    r'login code[:\s]+(\d{5,6})',
    r'Login code:\s*(\d{5,6})',
    r'(?<!\d)(\d{5})(?!\d)',
    r'(?<!\d)(\d{6})(?!\d)',
]


def extract_otp_from_text(text: str) -> str | None:
    if not text:
        return None
    for pattern in OTP_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


async def fetch_otp(
    session_string: str,
    timeout: int = 60,
    retry_interval: int = 5
) -> dict:

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return {"success": False, "error": "API credentials not configured in config.py"}

    session_string = session_string.strip()
    if len(session_string) < 100:
        return {
            "success": False,
            "error": f"Session string too short ({len(session_string)} chars) — re-generate it"
        }

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.errors import (
            AuthKeyUnregisteredError, SessionRevokedError,
            UserDeactivatedBanError, FloodWaitError
        )

        async with TelegramClient(
            StringSession(session_string),
            int(TELEGRAM_API_ID),
            str(TELEGRAM_API_HASH)
        ) as client:

            logger.info("Telethon connected. Reading 777000...")

            elapsed = 0
            while elapsed < timeout:
                try:
                    messages = await client.get_messages(TELEGRAM_OTP_SENDER, limit=5)
                    for msg in messages:
                        text = msg.text or ""
                        otp = extract_otp_from_text(text)
                        if otp:
                            logger.info(f"✅ OTP found: {otp}")
                            return {
                                "success": True,
                                "otp": otp,
                                "full_message": text
                            }
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
                    elapsed += e.seconds
                    continue
                except Exception as e:
                    logger.warning(f"Read attempt failed: {e}")

                if elapsed == 0:
                    logger.info("No OTP yet — waiting...")

                await asyncio.sleep(retry_interval)
                elapsed += retry_interval

            return {"success": False, "error": "OTP not received within timeout. Try again in 30s."}

    except Exception as e:
        error_str = str(e)
        logger.error(f"OTP fetch error: {error_str}", exc_info=True)

        if "auth" in error_str.lower() or "session" in error_str.lower():
            return {
                "success": False,
                "error": "Session expired or invalid — re-generate using generate_session.py"
            }
        if "banned" in error_str.lower() or "deactivated" in error_str.lower():
            return {"success": False, "error": "Account banned or deactivated"}

        return {"success": False, "error": f"Error: {error_str}"}


async def fetch_new_otp(
    session_string: str,
    timeout: int = 120,
    retry_interval: int = 5
) -> dict:

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return {"success": False, "error": "API credentials not configured"}

    session_string = session_string.strip()

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.errors import FloodWaitError

        async with TelegramClient(
            StringSession(session_string),
            int(TELEGRAM_API_ID),
            str(TELEGRAM_API_HASH)
        ) as client:

            # Record baseline message ID
            last_id = 0
            try:
                messages = await client.get_messages(TELEGRAM_OTP_SENDER, limit=1)
                if messages:
                    last_id = messages[0].id
                logger.info(f"Baseline message ID: {last_id}")
            except Exception:
                pass

            # Poll for NEW message
            elapsed = 0
            while elapsed < timeout:
                await asyncio.sleep(retry_interval)
                elapsed += retry_interval

                try:
                    messages = await client.get_messages(TELEGRAM_OTP_SENDER, limit=3)
                    for msg in messages:
                        if msg.id <= last_id:
                            break
                        text = msg.text or ""
                        otp = extract_otp_from_text(text)
                        if otp:
                            return {"success": True, "otp": otp, "full_message": text}
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    logger.warning(f"Poll error: {e}")

            return {"success": False, "error": "OTP not received within timeout"}

    except Exception as e:
        return {"success": False, "error": str(e)}
