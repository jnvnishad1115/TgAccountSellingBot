"""
account_handlers.py
Full automated flow:
  1. User buys → account reserved
  2. Bot shows phone + password + [🔐 Get Code] button
  3. User clicks Get Code
  4. Pyrogram connects with session_string
  5. Reads 777000 chat history → extracts OTP via regex
  6. Deducts money + marks account sold
  7. Delivers OTP instantly to user
"""

import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import (
    get_stock_summary, get_available_account, get_user,
    mark_reserved, mark_sold, unmark_sold,
    create_order, get_order,
    update_balance, get_country_price,
    mark_order_otp_sent
)
from config import CURRENCY_SYMBOL, COUNTRIES_PER_PAGE, TELEGRAM_API_ID, ADMIN_IDS
from checker import check_account_by_id, extract_session

CHECKER_ENABLED = bool(TELEGRAM_API_ID)
MAX_CHECK_TRIES = 5


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def build_country_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    stock       = get_stock_summary()
    total       = len(stock)
    start       = page * COUNTRIES_PER_PAGE
    end         = start + COUNTRIES_PER_PAGE
    chunk       = stock[start:end]
    total_pages = max(1, (total + COUNTRIES_PER_PAGE - 1) // COUNTRIES_PER_PAGE)

    buttons = []
    for row in chunk:
        buttons.append([InlineKeyboardButton(
            f"🌍 {row['country']}   {CURRENCY_SYMBOL}{row['price']:.0f}   [{row['cnt']} left] ✅",
            callback_data=f"country_{row['country']}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if end < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("◀️ Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def parse_account_data(data: str) -> dict:
    """
    Parses stored account string. Supported formats:
      phone|password
      phone|password|session_string
      phone|email|password|session_string
    Returns: {phone, password, session, raw}
    """
    parts  = [p.strip() for p in data.split("|")]
    result = {"phone": None, "password": None, "session": None, "raw": data}

    if len(parts) >= 1:
        result["phone"] = parts[0]

    if len(parts) == 2:
        result["password"] = parts[1]

    elif len(parts) == 3:
        result["password"] = parts[1]
        result["session"]  = parts[2] if len(parts[2]) > 50 else None

    elif len(parts) >= 4:
        result["password"] = parts[2]
        result["session"]  = parts[-1] if len(parts[-1]) > 50 else None

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Browse & Select
# ─────────────────────────────────────────────────────────────────────────────

async def buy_accounts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    stock = get_stock_summary()
    if not stock:
        await q.edit_message_text(
            "❌ <b>Out of Stock</b>\n\nNo accounts available right now.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Main Menu", callback_data="main_menu")
            ]])
        )
        return
    total = sum(s["cnt"] for s in stock)
    await q.edit_message_text(
        f"🛍 <b>Buy Telegram Accounts</b>\n\n"
        f"📦 Available: <b>{total}</b> accounts in <b>{len(stock)}</b> countries\n\n"
        f"Select a country:",
        parse_mode="HTML",
        reply_markup=build_country_keyboard(0)
    )


async def page_nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    page = int(q.data.split("_")[1])
    await q.edit_message_text(
        "🛍 <b>Buy Telegram Accounts</b>\n\nSelect a country:",
        parse_mode="HTML",
        reply_markup=build_country_keyboard(page)
    )


async def select_country(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q       = update.callback_query
    await q.answer()
    country = q.data.replace("country_", "", 1)
    user    = get_user(q.from_user.id)
    price   = get_country_price(country)
    acct    = get_available_account(country)

    if not acct:
        await q.answer("❌ Just went out of stock!", show_alert=True)
        return

    bal     = user["balance"] if user else 0.0
    can_buy = bal >= price
    after   = bal - price

    kb_rows = []
    if can_buy:
        kb_rows.append([InlineKeyboardButton(
            f"✅ Buy Now — {CURRENCY_SYMBOL}{price:.2f}",
            callback_data=f"confirm_buy_{country}"
        )])
    else:
        kb_rows.append([InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")])
    kb_rows.append([InlineKeyboardButton("◀️ Back", callback_data="buy_accounts")])

    await q.edit_message_text(
        f"🌍 <b>{country} Telegram Account</b>\n\n"
        f"💰 Price: <b>{CURRENCY_SYMBOL}{price:.2f}</b>\n"
        f"💳 Your Balance: {CURRENCY_SYMBOL}{bal:.2f}\n"
        + (f"📉 After Purchase: {CURRENCY_SYMBOL}{after:.2f}\n" if can_buy else "") +
        f"\n{'✅ Sufficient balance.' if can_buy else f'❌ Need {CURRENCY_SYMBOL}{price - bal:.2f} more.'}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb_rows)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Confirm Buy → Reserve account, show credentials + Get Code button
# ─────────────────────────────────────────────────────────────────────────────

async def confirm_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q       = update.callback_query
    await q.answer("Processing...")
    country = q.data.replace("confirm_buy_", "", 1)
    user    = get_user(q.from_user.id)
    price   = get_country_price(country)

    if user["balance"] < price:
        await q.edit_message_text(
            f"❌ <b>Insufficient Balance</b>\n\n"
            f"Required: {CURRENCY_SYMBOL}{price:.2f}\n"
            f"Available: {CURRENCY_SYMBOL}{user['balance']:.2f}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")],
                [InlineKeyboardButton("◀️ Back",      callback_data="buy_accounts")],
            ])
        )
        return

    # Session check loop
    if CHECKER_ENABLED:
        await q.edit_message_text(
            "🔍 <b>Verifying account...</b>\n\n⏳ Please wait...",
            parse_mode="HTML"
        )

    delivered = None
    for _ in range(MAX_CHECK_TRIES):
        acct = get_available_account(country)
        if not acct:
            break
        if CHECKER_ENABLED and extract_session(acct["data"]):
            if await check_account_by_id(acct["id"]) == "dead":
                continue
        delivered = acct
        break

    if not delivered:
        await q.edit_message_text(
            f"❌ <b>No Valid Accounts Available</b>\n\n"
            f"All {country} accounts failed verification.\n"
            f"Your balance was <b>not</b> deducted.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛍 Other Countries", callback_data="buy_accounts")],
                [InlineKeyboardButton("🏠 Main Menu",       callback_data="main_menu")],
            ])
        )
        return

    # ── Reserve account (no deduction yet) ───────────────────────────────────
    mark_reserved(delivered["id"])
    order_id = create_order(
        q.from_user.id, delivered["id"],
        country, price,
        account_data=delivered["data"]
    )

    parsed   = parse_account_data(delivered["data"])
    phone    = parsed["phone"]    or "N/A"
    password = parsed["password"] or "N/A"
    has_session = bool(parsed["session"])

    # ── Show credentials + Get Code button ────────────────────────────────────
    if has_session:
        # Fully automatic — user just clicks Get Code
        action_text = (
            "🤖 <b>Fully Automatic!</b>\n"
            "Tap below to fetch OTP instantly."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Get Code", callback_data=f"getcode_{order_id}")],
            [InlineKeyboardButton("📦 Orders",   callback_data="order_history"),
             InlineKeyboardButton("🏠 Menu",     callback_data="main_menu")],
        ])
    else:
        # No session string — manual OTP needed from admin
        action_text = (
            "⏳ <b>Waiting for OTP...</b>\n"
            "OTP will be delivered automatically."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Orders", callback_data="order_history"),
             InlineKeyboardButton("🏠 Menu",   callback_data="main_menu")],
        ])

    await q.edit_message_text(
        f"📋 <b>Account Details</b>\n\n"
        f"🌍 Country: <b>{country}</b>\n"
        f"💰 Price: <b>{CURRENCY_SYMBOL}{price:.2f}</b>\n"
        f"🆔 Order ID: <code>#{order_id}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📱 <b>Phone Number:</b>\n<code>{phone}</code>\n\n"
        f"🔑 <b>Password:</b>\n<code>{password}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{action_text}\n\n"
        f"💳 Wallet charged <b>only after OTP is delivered</b>.",
        parse_mode="HTML",
        reply_markup=kb
    )

    # Notify admin
    u            = q.from_user
    username_str = f"@{u.username}" if u.username else "no username"
    for admin_id in ADMIN_IDS:
        try:
            await ctx.bot.send_message(
                admin_id,
                f"🛒 <b>New Account Reserved</b>\n\n"
                f"👤 {u.full_name} ({username_str})\n"
                f"🆔 User ID: <code>{u.id}</code>\n"
                f"🌍 Country: {country}\n"
                f"💰 Price: {CURRENCY_SYMBOL}{price:.2f}\n"
                f"🆔 Order: <code>#{order_id}</code>\n\n"
                f"📱 Phone: <code>{phone}</code>\n"
                f"🔑 Password: <code>{password}</code>\n\n"
                f"{'🤖 Auto OTP enabled — user will fetch it.' if has_session else f'⚡ Send OTP manually: /otp {order_id} CODE'}",
                parse_mode="HTML"
            )
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Get Code button → Auto-fetch OTP from 777000
# ─────────────────────────────────────────────────────────────────────────────

async def get_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Called when user taps [🔐 Get Code].
    Connects with session_string → reads 777000 → extracts OTP → delivers.
    Deducts money + marks sold only on success.
    """
    from otp_fetcher import fetch_otp

    q        = update.callback_query
    await q.answer("Connecting to Telegram...")
    order_id = int(q.data.replace("getcode_", "", 1))
    order    = get_order(order_id)

    if not order:
        await q.edit_message_text("❌ Order not found.")
        return

    if order.get("otp_sent"):
        await q.edit_message_text(
            f"✅ <b>OTP Already Delivered</b>\n\n"
            f"Check your Order History for the code.\n"
            f"🆔 Order: #{order_id}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📦 Order History", callback_data="order_history")
            ]])
        )
        return

    parsed     = parse_account_data(order["account_data"])
    session    = parsed["session"]
    phone      = parsed["phone"]    or "N/A"
    password   = parsed["password"] or "N/A"
    user       = get_user(q.from_user.id)
    price      = order["price"]
    country    = order["country"]

    if not session:
        await q.edit_message_text(
            "❌ No session string found for this account.\n"
            "Please wait for admin to send OTP manually.",
            parse_mode="HTML"
        )
        return

    # ── Step 1: Show "Fetching..." to user ────────────────────────────────────
    await q.edit_message_text(
        f"🔄 <b>Fetching OTP Automatically...</b>\n\n"
        f"📱 Phone: <code>{phone}</code>\n\n"
        f"⏳ Connecting to Telegram servers...\n"
        f"This takes 5–15 seconds.",
        parse_mode="HTML"
    )

    # ── Step 2: Run OTP fetcher in background ─────────────────────────────────
    result = await fetch_otp(session_string=session, timeout=60, retry_interval=5)

    # ── Step 3a: Success → deduct + mark sold + deliver ───────────────────────
    if result["success"]:
        otp = result["otp"]

        # Check balance again (race condition guard)
        user = get_user(q.from_user.id)
        if user["balance"] < price:
            await q.edit_message_text(
                f"❌ <b>Insufficient Balance</b>\n\n"
                f"Your balance is {CURRENCY_SYMBOL}{user['balance']:.2f} "
                f"but account costs {CURRENCY_SYMBOL}{price:.2f}.\n"
                f"Please add funds.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")
                ]])
            )
            return

        update_balance(q.from_user.id, -price)     # 💰 Deduct wallet
        mark_sold(order["account_id"])             # 📦 Remove from stock
        mark_order_otp_sent(order_id, otp)         # 💾 Save OTP in DB

        new_bal = user["balance"] - price

        await q.edit_message_text(
            f"🎉 <b>Complete! Account Ready to Use</b>\n\n"
            f"🌍 Country: <b>{country}</b>\n"
            f"🆔 Order: <code>#{order_id}</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📱 <b>Phone:</b>\n<code>{phone}</code>\n\n"
            f"🔑 <b>Password:</b>\n<code>{password}</code>\n\n"
            f"🔐 <b>OTP Code:</b>\n<code>{otp}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 Charged: {CURRENCY_SYMBOL}{price:.2f}\n"
            f"💳 Remaining Balance: {CURRENCY_SYMBOL}{new_bal:.2f}\n\n"
            f"⚠️ OTP expires in 2 minutes — login now!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛍 Buy Another",   callback_data="buy_accounts")],
                [InlineKeyboardButton("📦 Order History", callback_data="order_history")],
                [InlineKeyboardButton("🏠 Main Menu",     callback_data="main_menu")],
            ])
        )

        # Notify admin of successful auto-delivery
        for admin_id in ADMIN_IDS:
            try:
                await ctx.bot.send_message(
                    admin_id,
                    f"✅ <b>Auto OTP Delivered</b>\n\n"
                    f"🆔 Order: #{order_id}\n"
                    f"👤 User: <code>{q.from_user.id}</code>\n"
                    f"💰 Charged: {CURRENCY_SYMBOL}{price:.2f}\n"
                    f"🔢 OTP: <code>{otp}</code>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    # ── Step 3b: Failed → show retry OR release account back to stock ───────────
    else:
        error = result.get("error", "Unknown error")

        # Permanent errors → release account back to stock (unmark reserved)
        # Temporary errors → keep reserved so user can retry
        permanent_errors = [
            "Session is invalid", "Session has expired", "Session expired",
            "Session string format mismatch", "Session format mismatch",
            "banned", "deactivated", "invalid session", "revoked"
        ]
        is_permanent = any(e.lower() in error.lower() for e in permanent_errors)

        if is_permanent:
            # Release account back to available stock
            unmark_sold(order["account_id"])
            extra_note = (
                "⚠️ This account's session is broken.\n"
                "It has been <b>returned to stock</b> automatically.\n"
                "Please contact support or try buying another account."
            )
            retry_buttons = [
                [InlineKeyboardButton("🛍 Buy Another", callback_data="buy_accounts")],
                [InlineKeyboardButton("🆘 Support",     callback_data="support")],
                [InlineKeyboardButton("🏠 Main Menu",   callback_data="main_menu")],
            ]
        else:
            # Temporary — keep reserved, let user retry
            extra_note = "💡 Your wallet was <b>NOT charged</b>.\nTap Retry after 30 seconds."
            retry_buttons = [
                [InlineKeyboardButton("🔄 Retry",     callback_data=f"getcode_{order_id}")],
                [InlineKeyboardButton("🆘 Support",   callback_data="support")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
            ]

        await q.edit_message_text(
            f"⚠️ <b>Could Not Fetch OTP</b>\n\n"
            f"📱 Phone: <code>{phone}</code>\n\n"
            f"Reason: {error}\n\n"
            f"{extra_note}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(retry_buttons)
        )