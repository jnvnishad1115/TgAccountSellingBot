# ── config.py — Railway Environment Variables ──────────────────────────────
# All sensitive values are read from environment variables (Railway → Variables tab)
# DO NOT hardcode secrets here

import os

# ── Bot ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

# ── UPI Payment ─────────────────────────────────────────────────────────────
UPI_ID      = os.environ.get("UPI_ID", "yourname@upi")
UPI_NAME    = os.environ.get("UPI_NAME", "Your Shop")
UPI_QR_PATH = os.environ.get("UPI_QR_PATH", "qr.png")

# ── Telegram API ───────────────────────────────────────────────────────────
TELEGRAM_API_ID   = int(os.environ.get("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")

# ── MongoDB ────────────────────────────────────────────────────────────────
MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB  = os.environ.get("MONGO_DB", "tgbot")

# ── Currency ───────────────────────────────────────────────────────────────
CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "₹")
CURRENCY_CODE   = os.environ.get("CURRENCY_CODE", "INR")

# ── Pagination ─────────────────────────────────────────────────────────────
COUNTRIES_PER_PAGE = int(os.environ.get("COUNTRIES_PER_PAGE", "8"))

# ── Support ────────────────────────────────────────────────────────────────
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "@admin")
SUPPORT_HOURS    = os.environ.get("SUPPORT_HOURS", "9 AM – 9 PM")
