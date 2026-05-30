"""
generate_session.py — Telethon version
───────────────────────────────────────
Run this script once per account to get its session string.
Then add it to your bot stock in format:  phone|password|SESSION_STRING

Usage:
  pip install telethon
  python generate_session.py
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from telethon import TelegramClient
from telethon.sessions import StringSession
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH

print("=" * 55)
print("   Telegram Session String Generator (Telethon)")
print("=" * 55)

if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
    print("\n❌ Set TELEGRAM_API_ID and TELEGRAM_API_HASH in config.py first!")
    sys.exit(1)

print(f"\n✅ Using API ID: {TELEGRAM_API_ID}")
print("📱 Enter the phone number of the account you want to sell.\n")


async def main():
    async with TelegramClient(
        StringSession(),
        int(TELEGRAM_API_ID),
        str(TELEGRAM_API_HASH)
    ) as client:
        session = client.session.save()
        me = await client.get_me()
        phone = me.phone or "unknown"

        print(f"\n✅ Session generated for: +{phone}")
        print(f"\n{'=' * 55}")
        print("SESSION STRING (copy EVERYTHING on the next line):")
        print(f"{'=' * 55}\n")
        print(session)
        print(f"\n{'=' * 55}")
        print("\n📋 Add to stock in this format:")
        print(f"   +{phone}|YOUR_2FA_PASSWORD|{session}")
        print("\n⚠️  If no 2FA password, leave it blank:")
        print(f"   +{phone}||{session}")
        print(f"\n{'=' * 55}")
        print(f"✅ Session length: {len(session)} characters")


asyncio.run(main())
