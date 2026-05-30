"""handlers/user_handlers.py — ReplyKeyboardMarkup persistent menu"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import upsert_user, get_user, get_orders
from config import CURRENCY_SYMBOL, SUPPORT_USERNAME, SUPPORT_HOURS, ADMIN_IDS

WAITING_SUPPORT_MSG = 4   # must match bot.py

# ── Persistent bottom menu (always visible) ───────────────────────────────────
MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🛍 Buy Telegram Account"],
        ["💳 Wallet",  "👤 Profile"],
        ["📦 Orders",  "🆘 Support"],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
    input_field_placeholder="Choose an option..."
)

# Text labels — used in button_handler to match pressed button
BTN_BUY     = "🛍 Buy Telegram Account"
BTN_WALLET  = "💳 Wallet"
BTN_PROFILE = "👤 Profile"
BTN_ORDERS  = "📦 Orders"
BTN_SUPPORT = "🆘 Support"


# ─────────────────────────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    upsert_user(u.id, u.username or "", u.full_name)
    await update.message.reply_text(
        f"👋 Welcome, <b>{u.first_name}</b>!\n\n"
        f"Use the menu buttons below 👇",
        parse_mode="HTML",
        reply_markup=MAIN_MENU_KEYBOARD
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main button handler — fired when user taps any menu button
# ─────────────────────────────────────────────────────────────────────────────
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == BTN_BUY:
        await _show_buy(update, ctx)

    elif text == BTN_WALLET:
        await _show_wallet(update, ctx)

    elif text == BTN_PROFILE:
        await _show_profile(update, ctx)

    elif text == BTN_ORDERS:
        await _show_orders(update, ctx)

    elif text == BTN_SUPPORT:
        await _show_support(update, ctx)


# ─────────────────────────────────────────────────────────────────────────────
# 🛍 Buy Telegram Account
# ─────────────────────────────────────────────────────────────────────────────
async def _show_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from database import get_stock_summary
    from config import COUNTRIES_PER_PAGE

    stock = get_stock_summary()
    if not stock:
        await update.message.reply_text(
            "❌ <b>Out of Stock</b>\n\nNo accounts available right now. Check back soon!",
            parse_mode="HTML"
        )
        return

    total       = sum(s["cnt"] for s in stock)
    page        = 0
    start       = page * COUNTRIES_PER_PAGE
    end         = start + COUNTRIES_PER_PAGE
    chunk       = stock[start:end]
    total_pages = max(1, (len(stock) + COUNTRIES_PER_PAGE - 1) // COUNTRIES_PER_PAGE)

    buttons = []
    for row in chunk:
        buttons.append([InlineKeyboardButton(
            f"🌍 {row['country']}   {CURRENCY_SYMBOL}{row['price']:.0f}   [{row['cnt']} left] ✅",
            callback_data=f"country_{row['country']}"
        )])
    nav = []
    if end < len(stock):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data="page_1"))
    if nav:
        buttons.append(nav)

    await update.message.reply_text(
        f"🛍 <b>Buy Telegram Accounts</b>\n\n"
        f"📦 Available: <b>{total}</b> accounts in <b>{len(stock)}</b> countries\n\n"
        f"Select a country:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ─────────────────────────────────────────────────────────────────────────────
# 💳 Wallet
# ─────────────────────────────────────────────────────────────────────────────
async def _show_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    bal  = user["balance"] if user else 0.0
    await update.message.reply_text(
        f"💳 <b>Wallet</b>\n\n"
        f"💰 Balance: <b>{CURRENCY_SYMBOL}{bal:.2f}</b>\n\n"
        f"Tap below to add funds:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")]
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
# 👤 Profile
# ─────────────────────────────────────────────────────────────────────────────
async def _show_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u      = update.effective_user
    user   = get_user(u.id)
    orders = get_orders(u.id)
    await update.message.reply_text(
        f"👤 <b>User Profile</b>\n\n"
        f"🪪 ID: <code>{u.id}</code>\n"
        f"👤 Name: {u.full_name}\n"
        f"💰 Balance: <b>{CURRENCY_SYMBOL}{user['balance']:.2f}</b>\n"
        f"📦 Total Orders: {len(orders)}\n"
        f"📅 Joined: {user['joined_at'][:10]}\n"
        f"💱 Currency: INR",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 View Orders", callback_data="order_history")]
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
# 📦 Orders
# ─────────────────────────────────────────────────────────────────────────────
async def _show_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    orders = get_orders(update.effective_user.id)
    if not orders:
        await update.message.reply_text(
            "📦 <b>Order History</b>\n\nNo orders yet.\n\nTap <b>Buy Telegram Account</b> to get started!",
            parse_mode="HTML"
        )
        return

    lines = ["📦 <b>Order History</b>\n"]
    for o in orders:
        data     = o.get("account_data") or ""
        parts    = [p.strip() for p in data.split("|")]
        phone    = parts[0] if len(parts) > 0 else "N/A"
        password = parts[1] if len(parts) > 1 else "N/A"
        otp_code = o.get("otp_code")
        otp_sent = o.get("otp_sent", 0)
        otp_line = f"🔐 <b>OTP:</b> <code>{otp_code}</code>" if (otp_sent and otp_code) else "🔐 OTP: ⏳ Waiting..."

        lines.append(
            f"━━━━━━━━━━━━━━\n"
            f"🌍 <b>{o['country']}</b>  |  {CURRENCY_SYMBOL}{o['price']:.2f}\n"
            f"📅 {o['ordered_at'][:16]}\n"
            f"🆔 Order: <code>#{o['id']}</code>\n"
            f"📱 <b>Phone:</b> <code>{phone}</code>\n"
            f"🔑 <b>Password:</b> <code>{password}</code>\n"
            f"{otp_line}"
        )

    # Get Code buttons for pending orders
    kb_rows = []
    for o in orders:
        if not o.get("otp_sent"):
            parts       = (o.get("account_data") or "").split("|")
            has_session = any(len(p.strip()) > 50 for p in parts[2:])
            if has_session:
                kb_rows.append([InlineKeyboardButton(
                    f"🔐 Get Code — Order #{o['id']}",
                    callback_data=f"getcode_{o['id']}"
                )])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb_rows) if kb_rows else None
    )


# ─────────────────────────────────────────────────────────────────────────────
# 🆘 Support
# ─────────────────────────────────────────────────────────────────────────────
async def _show_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆘 <b>Support</b>\n\n"
        f"📱 Contact admin: {SUPPORT_USERNAME}\n"
        f"🕐 Hours: {SUPPORT_HOURS}\n\n"
        f"Or type your message below and we'll forward it to the admin:",
        parse_mode="HTML"
    )
    return WAITING_SUPPORT_MSG


# ─────────────────────────────────────────────────────────────────────────────
# Callback query versions (for inline back buttons)
# ─────────────────────────────────────────────────────────────────────────────
async def main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Called by inline ◀️ Back buttons — just show the menu keyboard again."""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🏠 Choose an option from the menu below 👇",
        parse_mode="HTML"
    )


async def wallet_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    user = get_user(q.from_user.id)
    bal  = user["balance"] if user else 0.0
    await q.edit_message_text(
        f"💳 <b>Wallet</b>\n\n"
        f"💰 Balance: <b>{CURRENCY_SYMBOL}{bal:.2f}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")]
        ])
    )


async def profile_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    await q.answer()
    user   = get_user(q.from_user.id)
    orders = get_orders(q.from_user.id)
    await q.edit_message_text(
        f"👤 <b>User Profile</b>\n\n"
        f"🪪 ID: <code>{q.from_user.id}</code>\n"
        f"💰 Balance: {CURRENCY_SYMBOL}{user['balance']:.2f}\n"
        f"📦 Total Orders: {len(orders)}\n"
        f"📅 Joined: {user['joined_at'][:10]}\n"
        f"💱 Currency: INR",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Order History", callback_data="order_history")]
        ])
    )


async def order_history_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    await q.answer()
    orders = get_orders(q.from_user.id)

    if not orders:
        await q.edit_message_text("📦 <b>Order History</b>\n\nNo orders yet.", parse_mode="HTML")
        return

    lines = ["📦 <b>Order History</b>\n"]
    for o in orders:
        data     = o.get("account_data") or ""
        parts    = [p.strip() for p in data.split("|")]
        phone    = parts[0] if len(parts) > 0 else "N/A"
        password = parts[1] if len(parts) > 1 else "N/A"
        otp_code = o.get("otp_code")
        otp_sent = o.get("otp_sent", 0)
        otp_line = f"🔐 <b>OTP:</b> <code>{otp_code}</code>" if (otp_sent and otp_code) else "🔐 OTP: ⏳ Waiting..."
        lines.append(
            f"━━━━━━━━━━━━━━\n"
            f"🌍 <b>{o['country']}</b>  |  {CURRENCY_SYMBOL}{o['price']:.2f}\n"
            f"📅 {o['ordered_at'][:16]}\n"
            f"🆔 Order: <code>#{o['id']}</code>\n"
            f"📱 <b>Phone:</b> <code>{phone}</code>\n"
            f"🔑 <b>Password:</b> <code>{password}</code>\n"
            f"{otp_line}"
        )

    kb_rows = []
    for o in orders:
        if not o.get("otp_sent"):
            parts       = (o.get("account_data") or "").split("|")
            has_session = any(len(p.strip()) > 50 for p in parts[2:])
            if has_session:
                kb_rows.append([InlineKeyboardButton(
                    f"🔐 Get Code — Order #{o['id']}",
                    callback_data=f"getcode_{o['id']}"
                )])
    await q.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb_rows) if kb_rows else None
    )


async def support_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        f"🆘 <b>Support</b>\n\n"
        f"📱 Contact admin: {SUPPORT_USERNAME}\n"
        f"🕐 Hours: {SUPPORT_HOURS}\n\n"
        f"Type your message and we'll forward it to the admin:",
        parse_mode="HTML"
    )
    return WAITING_SUPPORT_MSG


async def support_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u   = update.effective_user
    msg = update.message.text
    for admin_id in ADMIN_IDS:
        try:
            await ctx.bot.send_message(
                admin_id,
                f"📩 <b>Support Message</b>\n"
                f"From: {u.full_name} (@{u.username})\n"
                f"ID: <code>{u.id}</code>\n\n"
                f"{msg}",
                parse_mode="HTML"
            )
        except Exception:
            pass
    await update.message.reply_text(
        "✅ Message sent! We'll reply soon.",
        reply_markup=MAIN_MENU_KEYBOARD
    )
    return ConversationHandler.END


# ── Command shortcuts ─────────────────────────────────────────────────────────
async def wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_wallet(update, ctx)

async def profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_profile(update, ctx)

async def order_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_orders(update, ctx)
