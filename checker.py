"""
checker.py — Telegram Session Validator (Telethon)
===================================================
Uses Telethon to connect with each session string.
Dead/banned sessions are marked in DB so they're never sold.
"""

import asyncio
import logging
from database import (
    get_all_unsold_accounts, mark_account_dead,
    mark_account_verified, get_account_by_id
)
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH

logger = logging.getLogger(__name__)


async def check_session(session_string: str) -> str:
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.errors import (
            AuthKeyUnregisteredError, UserDeactivatedBanError,
            SessionRevokedError, FloodWaitError
        )

        async with TelegramClient(
            StringSession(session_string),
            int(TELEGRAM_API_ID),
            str(TELEGRAM_API_HASH)
        ) as client:
            me = await client.get_me()
            logger.info(f"✅ Session alive: {me.phone}")
            return "alive"

    except Exception as e:
        error_str = str(e).lower()
        if any(x in error_str for x in ["auth", "banned", "deactivated", "revoked", "invalid"]):
            logger.warning(f"❌ Dead session: {e}")
            return "dead"
        if "flood" in error_str:
            return "error"
        logger.error(f"⚠️ Unknown error: {e}")
        return "error"


def extract_session(data: str) -> str | None:
    parts = data.strip().split("|")
    for part in reversed(parts):
        part = part.strip()
        if len(part) > 100:
            return part
    return None


async def check_account_by_id(account_id: int) -> str:
    acct = get_account_by_id(account_id)
    if not acct:
        return "not_found"

    session = extract_session(acct["data"])
    if not session:
        return "no_session"

    result = await check_session(session)

    if result == "dead":
        mark_account_dead(account_id)
    elif result == "alive":
        mark_account_verified(account_id)

    return result


async def bulk_check_all(
    delay_between: float = 2.0,
    progress_cb=None
) -> dict:
    accounts = get_all_unsold_accounts()
    results  = {"alive": 0, "dead": 0, "error": 0, "no_session": 0}
    total    = len(accounts)

    for i, acct in enumerate(accounts, 1):
        session = extract_session(acct["data"])

        if not session:
            results["no_session"] += 1
            if progress_cb:
                await progress_cb(i, total, acct["country"], "no_session")
            continue

        status = await check_session(session)
        results[status] = results.get(status, 0) + 1

        if status == "dead":
            mark_account_dead(acct["id"])
        elif status == "alive":
            mark_account_verified(acct["id"])

        if progress_cb:
            await progress_cb(i, total, acct["country"], status)

        await asyncio.sleep(delay_between)

    return results


async def _standalone():
    logging.basicConfig(level=logging.INFO)
    print("🔍 Checking all unsold sessions...")

    async def progress(i, total, country, status):
        icon = {"alive": "✅", "dead": "❌", "error": "⚠️", "no_session": "⏭"}.get(status, "?")
        print(f"  [{i}/{total}] {icon} {country} — {status}")

    results = await bulk_check_all(progress_cb=progress)
    print(f"\n📊 Done!\n  ✅ Alive: {results['alive']}"
          f"\n  ❌ Dead:  {results['dead']}"
          f"\n  ⚠️ Error: {results['error']}"
          f"\n  ⏭ No session: {results['no_session']}")


if __name__ == "__main__":
    asyncio.run(_standalone())
