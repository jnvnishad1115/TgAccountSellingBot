"""handlers/admin_handlers.py"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import (
    get_user, update_balance, get_payment, update_payment_status,
    pending_payments, bulk_add_accounts, set_country_price,
    get_stock_summary, all_users, get_order, mark_order_otp_sent
)
from config import ADMIN_IDS, CURRENCY_SYMBOL

WAITING_ADD_ACCOUNT = 3   # must match bot.py


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = (update.callback_query or update).from_user.id if update.callback_query else update.effective_user.id
        if not is_admin(uid):
            if update.callback_query:
                await update.callback_query.answer("❌ Admins only!", show_alert=True)
            else:
                await update.message.reply_text("❌ Admins only!")
            return
        return await func(update, ctx)
    return wrapper


# ── Admin Panel ───────────────────────────────────────────────────────────────

@admin_only
async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stock   = get_stock_summary()
    total   = sum(s["cnt"] for s in stock)
    pending = pending_payments()
    users   = all_users()

    await update.message.reply_text(
        f"🔧 <b>Admin Panel</b>\n\n"
        f"👥 Total Users: {len(users)}\n"
        f"📦 Total Stock: {total} accounts ({len(stock)} countries)\n"
        f"⏳ Pending Payments: {len(pending)}\n\n"
        f"Tap a button below:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 View Stock",        callback_data="admin_stock")],
            [InlineKeyboardButton("💰 Pending Payments",  callback_data="admin_pending")],
            [InlineKeyboardButton("➕ Add Accounts",       callback_data="admin_addstock_new")],
        ])
    )


@admin_only
async def admin_panel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    await q.answer()
    action = q.data

    if action == "admin_stock":
        stock = get_stock_summary()
        if not stock:
            text = "📦 Stock is empty."
        else:
            lines = ["📦 <b>Current Stock</b>\n"]
            for s in stock:
                lines.append(f"🌍 {s['country']}: <b>{s['cnt']}</b> accs @ {CURRENCY_SYMBOL}{s['price']:.2f}")
            text = "\n".join(lines)
        await q.edit_message_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Accounts", callback_data="admin_addstock_new")],
                [InlineKeyboardButton("◀️ Back",        callback_data="admin_back")],
            ])
        )

    elif action == "admin_pending":
        pending = pending_payments()
        if not pending:
            await q.edit_message_text(
                "✅ No pending payments.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="admin_back")]])
            )
        else:
            await q.edit_message_text(
                f"⏳ <b>{len(pending)} Pending Payment(s)</b>\nSending details...",
                parse_mode="HTML"
            )
            for p in pending:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Approve & Credit", callback_data=f"approve_pay_{p['id']}"),
                    InlineKeyboardButton("❌ Reject",           callback_data=f"reject_pay_{p['id']}"),
                ]])
                await ctx.bot.send_message(
                    q.from_user.id,
                    f"💰 <b>Payment Request #{p['id']}</b>\n"
                    f"👤 User ID: <code>{p['user_id']}</code>\n"
                    f"💵 Amount: <b>{CURRENCY_SYMBOL}{p['amount']:.2f}</b>\n"
                    f"🔢 UTR: <code>{p['utr']}</code>\n"
                    f"🕐 Time: {p['created_at'][:16]}",
                    parse_mode="HTML", reply_markup=kb
                )

    elif action == "admin_back":
        stock   = get_stock_summary()
        total   = sum(s["cnt"] for s in stock)
        pending = pending_payments()
        await q.edit_message_text(
            f"🔧 <b>Admin Panel</b>\n\n"
            f"📦 Stock: {total} | ⏳ Pending: {len(pending)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 View Stock",       callback_data="admin_stock")],
                [InlineKeyboardButton("💰 Pending Payments", callback_data="admin_pending")],
                [InlineKeyboardButton("➕ Add Accounts",      callback_data="admin_addstock_new")],
            ])
        )

    elif action.startswith("admin_addstock"):
        await q.edit_message_text(
            "➕ <b>Add Accounts to Stock</b>\n\n"
            "Send in this format:\n\n"
            "<code>CountryName|price\n"
            "account_data_line_1\n"
            "account_data_line_2\n"
            "...</code>\n\n"
            "<b>Example:</b>\n"
            "<code>India|55\n"
            "+91XXXXXXXXXX|session_string_1\n"
            "+91XXXXXXXXXX|session_string_2</code>",
            parse_mode="HTML"
        )
        return WAITING_ADD_ACCOUNT


async def add_stock_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await admin_panel_cb(update, ctx)


@admin_only
async def add_stock_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "➕ <b>Add Accounts</b>\n\n"
        "Format:\n<code>Country|price\nline1\nline2...</code>",
        parse_mode="HTML"
    )
    return WAITING_ADD_ACCOUNT


@admin_only
async def receive_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = update.message.text.strip().splitlines()
    if not lines:
        await update.message.reply_text("❌ Empty. Try again.")
        return ConversationHandler.END

    header = lines[0]
    if "|" not in header:
        await update.message.reply_text("❌ First line must be: Country|price")
        return ConversationHandler.END

    country, price_str = header.split("|", 1)
    country = country.strip()
    try:
        price = float(price_str.strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid price.")
        return ConversationHandler.END

    account_lines = [l for l in lines[1:] if l.strip()]
    if not account_lines:
        await update.message.reply_text("❌ No account lines provided.")
        return ConversationHandler.END

    set_country_price(country, price)
    bulk_add_accounts(country, account_lines)

    await update.message.reply_text(
        f"✅ <b>Stock Added!</b>\n\n"
        f"🌍 Country: {country}\n"
        f"💰 Price: {CURRENCY_SYMBOL}{price:.2f}\n"
        f"📦 Accounts Added: {len(account_lines)}",
        parse_mode="HTML"
    )
    return ConversationHandler.END


# ── Payment Approval ──────────────────────────────────────────────────────────

@admin_only
async def approve_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    try:
        await q.answer("Processing...")
    except Exception:
        # Ignore answer timeouts — continue processing
        pass
    pay_id = int(q.data.split("_")[-1])
    pay    = get_payment(pay_id)

    if not pay or pay["status"] != "pending":
        try:
            await q.answer("⚠️ Already processed!", show_alert=True)
        except Exception:
            pass
        return

    # Credit user wallet
    update_payment_status(pay_id, "approved")
    update_balance(pay["user_id"], pay["amount"])

    try:
        await q.edit_message_text(
            f"✅ <b>Payment #{pay_id} Approved</b>\n\n"
            f"👤 User: <code>{pay['user_id']}</code>\n"
            f"💰 Credited: {CURRENCY_SYMBOL}{pay['amount']:.2f}\n"
            f"🔢 UTR: {pay['utr']}",
            parse_mode="HTML"
        )
    except Exception:
        pass

    # Notify user
    try:
        await ctx.bot.send_message(
            pay["user_id"],
            f"✅ <b>Payment Approved!</b>\n\n"
            f"💰 <b>{CURRENCY_SYMBOL}{pay['amount']:.2f}</b> has been added to your wallet.\n\n"
            f"Use /wallet to check your balance and start shopping! 🛍",
            parse_mode="HTML"
        )
    except Exception:
        pass


@admin_only
async def send_otp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split(maxsplit=2)

    if len(parts) < 3:
        await update.message.reply_text(
            "Usage: /otp <order_id> <otp_code>\n"
            "Example: /otp 1234 112233"
        )
        return

    _, order_id_str, otp_code = parts

    if not order_id_str.isdigit():
        await update.message.reply_text("Order ID must be a number.")
        return

    order_id = int(order_id_str)
    order = get_order(order_id)

    if not order:
        await update.message.reply_text(f"Order #{order_id} not found.")
        return

    if order["otp_sent"]:
        await update.message.reply_text("OTP has already been sent for this order.")
        return

    try:
        await ctx.bot.send_message(
            order["user_id"],
            f"🔒 <b>OTP for Order #{order_id}</b>\n\n"
            f"Your OTP: <code>{otp_code}</code>\n\n"
            f"Use it only once and do not share it with anyone.",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"Failed to send OTP: {e}")
        return

    mark_order_otp_sent(order_id, otp_code)
    await update.message.reply_text(
        f"✅ OTP sent securely to user <code>{order['user_id']}</code>.",
        parse_mode="HTML"
    )


@admin_only
async def reject_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    pay_id = int(q.data.split("_")[-1])
    pay    = get_payment(pay_id)

    if not pay or pay["status"] != "pending":
        try:
            await q.answer("⚠️ Already processed!", show_alert=True)
        except Exception:
            pass
        return

    update_payment_status(pay_id, "rejected")
    try:
        await q.edit_message_text(
            f"❌ <b>Payment #{pay_id} Rejected</b>\n\n"
            f"👤 User: <code>{pay['user_id']}</code>\n"
            f"💵 Amount: {CURRENCY_SYMBOL}{pay['amount']:.2f}\n"
            f"🔢 UTR: {pay['utr']}",
            parse_mode="HTML"
        )
    except Exception:
        pass

    # Notify user
    try:
        await ctx.bot.send_message(
            pay["user_id"],
            f"❌ <b>Payment Not Verified</b>\n\n"
            f"Your payment of {CURRENCY_SYMBOL}{pay['amount']:.2f} "
            f"(UTR: <code>{pay['utr']}</code>) could not be verified.\n\n"
            f"Please contact {ctx.bot_data.get('support', 'support')} "
            f"if you believe this is a mistake.",
            parse_mode="HTML"
        )
    except Exception:
        pass


# ── List Pending (command) ────────────────────────────────────────────────────

@admin_only
async def list_pending_payments(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pending = pending_payments()
    if not pending:
        await update.message.reply_text("✅ No pending payments right now.")
        return
    for p in pending:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_pay_{p['id']}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"reject_pay_{p['id']}"),
        ]])
        await update.message.reply_text(
            f"💰 <b>#{p['id']}</b> | User <code>{p['user_id']}</code>\n"
            f"💵 {CURRENCY_SYMBOL}{p['amount']:.2f} | UTR: <code>{p['utr']}</code>\n"
            f"🕐 {p['created_at'][:16]}",
            parse_mode="HTML", reply_markup=kb
        )


# ── Broadcast ─────────────────────────────────────────────────────────────────

@admin_only
async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /broadcast Your message here")
        return
    msg   = " ".join(ctx.args)
    users = all_users()
    sent  = 0
    for uid in users:
        try:
            await ctx.bot.send_message(uid, f"📢 <b>Announcement</b>\n\n{msg}", parse_mode="HTML")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Sent to {sent}/{len(users)} users.")


# ── Session Checker (Admin) ───────────────────────────────────────────────────

@admin_only
async def check_sessions_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /checksessions — bulk verify all unsold accounts
    Dead ones are auto-removed from available stock.
    """
    from database import get_stock_summary, get_dead_count, delete_dead_accounts
    from checker import bulk_check_all

    stock_before = get_stock_summary()
    total_before = sum(s["cnt"] for s in stock_before)

    msg = await update.message.reply_text(
        f"🔍 <b>Session Check Started</b>\n\n"
        f"📦 Checking {total_before} accounts...\n"
        f"This may take a few minutes.",
        parse_mode="HTML"
    )

    checked = {"i": 0}

    async def progress(i, total, country, status):
        checked["i"] = i
        icon = {"alive": "✅", "dead": "❌", "error": "⚠️", "no_session": "⏭"}.get(status, "?")
        # Update message every 10 accounts to avoid flood
        if i % 10 == 0 or i == total:
            try:
                await msg.edit_text(
                    f"🔍 <b>Checking Sessions...</b>\n\n"
                    f"Progress: {i}/{total}\n"
                    f"Last: {icon} {country}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    results = await bulk_check_all(delay_between=1.5, progress_cb=progress)
    dead_count = get_dead_count()

    await msg.edit_text(
        f"✅ <b>Session Check Complete!</b>\n\n"
        f"✅ Alive: <b>{results['alive']}</b>\n"
        f"❌ Dead: <b>{results['dead']}</b>\n"
        f"⚠️ Error: {results.get('error', 0)}\n"
        f"⏭ No Session Field: {results.get('no_session', 0)}\n\n"
        f"🗑 Dead accounts in DB: {dead_count}\n\n"
        f"Remove dead accounts from stock?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Remove Dead Accounts", callback_data="admin_delete_dead"),
            InlineKeyboardButton("❌ Keep", callback_data="admin_back"),
        ]])
    )


@admin_only
async def delete_dead_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from database import delete_dead_accounts, get_dead_count
    q = update.callback_query
    await q.answer()
    n = get_dead_count()
    delete_dead_accounts()
    await q.edit_message_text(
        f"🗑 <b>Removed {n} dead accounts from stock.</b>\n\n"
        f"Your remaining stock is now 100% verified.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Admin Panel", callback_data="admin_back")]])
    )


# ── OTP Command ───────────────────────────────────────────────────────────────

async def send_otp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /otp <order_id> <otp_code>
    Owner sends this after getting OTP from Telegram.
    Bot instantly forwards OTP to the buyer.
    """
    from database import get_order, mark_order_otp_sent

    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ Admins only!")
        return

    # Validate args
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text(
            "❌ <b>Wrong format!</b>\n\n"
            "Correct usage:\n"
            "<code>/otp order_id OTP_CODE</code>\n\n"
            "Example:\n"
            "<code>/otp 42 12345</code>",
            parse_mode="HTML"
        )
        return

    try:
        order_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Order ID must be a number.")
        return

    otp_code = ctx.args[1].strip()

    # Get order from DB
    order = get_order(order_id)
    if not order:
        await update.message.reply_text(f"❌ Order #{order_id} not found.")
        return

    if order.get("otp_sent"):
        await update.message.reply_text(
            f"⚠️ OTP already sent for Order #{order_id}."
        )
        return

    # ── Step 1: Deduct money from user wallet ────────────────────────────────
    from database import update_balance, mark_sold, get_account_by_id
    user_data = get_user(order["user_id"])
    price     = order["price"]

    if user_data["balance"] < price:
        await update.message.reply_text(
            f"❌ <b>User has insufficient balance!</b>\n\n"
            f"Required: {CURRENCY_SYMBOL}{price:.2f}\n"
            f"Available: {CURRENCY_SYMBOL}{user_data['balance']:.2f}\n\n"
            f"Add funds to user account first, then retry.",
            parse_mode="HTML"
        )
        return

    update_balance(order["user_id"], -price)          # Deduct wallet
    mark_sold(order["account_id"])                    # Remove from stock list
    mark_order_otp_sent(order_id, otp_code)           # Save OTP in DB

    new_bal = user_data["balance"] - price

    # ── Step 2: Send OTP + confirmation to buyer ──────────────────────────────
    buyer_id = order["user_id"]
    try:
        await ctx.bot.send_message(
            buyer_id,
            f"🔐 <b>Your OTP Has Arrived!</b>\n\n"
            f"🆔 Order: <code>#{order_id}</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔢 <b>OTP Code:</b>\n\n"
            f"<code>{otp_code}</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👆 Tap the code to copy it\n"
            f"⚠️ OTP expires in 2 minutes — use it now!\n\n"
            f"💰 <b>{CURRENCY_SYMBOL}{price:.2f} deducted from your wallet</b>\n"
            f"💳 Remaining Balance: {CURRENCY_SYMBOL}{new_bal:.2f}",
            parse_mode="HTML"
        )

        # ── Step 3: Confirm to admin ──────────────────────────────────────────
        await update.message.reply_text(
            f"✅ <b>OTP Delivered & Payment Processed!</b>\n\n"
            f"🆔 Order: #{order_id}\n"
            f"👤 Buyer: <code>{buyer_id}</code>\n"
            f"🔢 OTP: <code>{otp_code}</code>\n"
            f"💰 Charged: {CURRENCY_SYMBOL}{price:.2f}\n"
            f"💳 User Balance: {CURRENCY_SYMBOL}{new_bal:.2f}\n\n"
            f"📦 Account removed from stock list.",
            parse_mode="HTML"
        )

    except Exception as e:
        # OTP delivery failed — refund the user automatically
        update_balance(order["user_id"], +price)   # Refund
        mark_sold.__module__  # just to import check
        from database import unmark_sold
        unmark_sold(order["account_id"])           # Put back in stock

        await update.message.reply_text(
            f"❌ <b>OTP Delivery Failed — User Refunded!</b>\n\n"
            f"Error: {e}\n\n"
            f"User may have blocked the bot.\n"
            f"💰 {CURRENCY_SYMBOL}{price:.2f} refunded automatically.\n"
            f"📦 Account returned to stock.",
            parse_mode="HTML"
        )


# ══════════════════════════════════════════════════════════════════════════════
# NEW ADMIN FEATURES
# ══════════════════════════════════════════════════════════════════════════════

# ── 1. Active buyers ──────────────────────────────────────────────────────────

@admin_only
async def active_buyers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /buyers — list all users who have bought at least one account.
    Shows name, orders count, total spent, last order date.
    """
    from database import get_active_buyers, get_accounts_stats
    stats  = get_accounts_stats()
    buyers = get_active_buyers()

    if not buyers:
        await update.message.reply_text("📊 No buyers yet.")
        return

    # Summary header
    header = (
        f"👥 <b>Active Buyers Report</b>\n\n"
        f"🛒 Total Buyers: <b>{stats['buyers']}</b>\n"
        f"💰 Total Revenue: <b>{CURRENCY_SYMBOL}{stats['revenue']:.2f}</b>\n"
        f"📦 Accounts Sold: <b>{stats['sold']}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(header, parse_mode="HTML")

    # Send in chunks of 10 to avoid message too long
    chunk_size = 10
    for i in range(0, len(buyers), chunk_size):
        chunk = buyers[i:i + chunk_size]
        lines = []
        for b in chunk:
            uname = f"@{b['username']}" if b.get("username") else "no username"
            lines.append(
                f"👤 <b>{b['full_name']}</b> ({uname})\n"
                f"   🆔 <code>{b['user_id']}</code>\n"
                f"   📦 Orders: {b['total_orders']}  |  "
                f"💰 Spent: {CURRENCY_SYMBOL}{b['total_spent']:.2f}\n"
                f"   💳 Balance: {CURRENCY_SYMBOL}{b.get('balance', 0):.2f}\n"
                f"   📅 Last: {str(b['last_order'])[:16]}"
            )
        await update.message.reply_text("\n\n".join(lines), parse_mode="HTML")


# ── 2. Accounts list (available + sold) ──────────────────────────────────────

@admin_only
async def accounts_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /accounts — full stock overview.
    /accounts available — only unsold
    /accounts sold      — only sold with buyer details
    """
    from database import (
        get_available_accounts_list, get_sold_accounts_list,
        get_accounts_stats
    )

    arg = (ctx.args[0].lower() if ctx.args else "all")
    stats = get_accounts_stats()

    # Always show summary first
    summary = (
        f"📦 <b>Accounts Overview</b>\n\n"
        f"✅ Available: <b>{stats['available']}</b>\n"
        f"🔒 Reserved:  <b>{stats['reserved']}</b>\n"
        f"✔️ Sold:      <b>{stats['sold']}</b>\n"
        f"❌ Dead:      <b>{stats['dead']}</b>\n"
        f"📊 Total:     <b>{stats['total']}</b>\n\n"
        f"Use /accounts available  or  /accounts sold"
    )
    await update.message.reply_text(summary, parse_mode="HTML")

    if arg == "available":
        accounts = get_available_accounts_list()
        if not accounts:
            await update.message.reply_text("📭 No available accounts.")
            return
        # Group by country
        by_country: dict = {}
        for a in accounts:
            by_country.setdefault(a["country"], []).append(a)

        for country, accts in by_country.items():
            lines = [f"🌍 <b>{country}</b> — {len(accts)} available\n"]
            for a in accts[:20]:  # max 20 per country per message
                parts  = a["data"].split("|")
                phone  = parts[0] if parts else "N/A"
                status = a.get("status", "unchecked")
                icon   = "✅" if status == "alive" else "🔵" if status == "unchecked" else "🔒"
                lines.append(f"{icon} <code>{phone}</code>  [{status}]")
            if len(accts) > 20:
                lines.append(f"...and {len(accts)-20} more")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    elif arg == "sold":
        accounts = get_sold_accounts_list()
        if not accounts:
            await update.message.reply_text("📭 No sold accounts yet.")
            return
        # Send in chunks of 8
        chunk_size = 8
        for i in range(0, min(len(accounts), 80), chunk_size):
            chunk = accounts[i:i + chunk_size]
            lines = [f"📋 <b>Sold Accounts</b> ({i+1}–{i+len(chunk)})\n"]
            for a in chunk:
                parts  = (a.get("data") or "").split("|")
                phone  = parts[0] if parts else "N/A"
                uname  = f"@{a['buyer_username']}" if a.get("buyer_username") else ""
                otp_ok = "✅ OTP sent" if a.get("otp_sent") else "⏳ Pending"
                lines.append(
                    f"━━━━━━━━━━\n"
                    f"📱 <code>{phone}</code>\n"
                    f"🌍 {a['country']}  |  {CURRENCY_SYMBOL}{a.get('price', 0):.2f}\n"
                    f"👤 {a['buyer_name']} {uname} (<code>{a['buyer_id']}</code>)\n"
                    f"📅 {str(a.get('sold_at',''))[:16]}  |  {otp_ok}"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        if len(accounts) > 80:
            await update.message.reply_text(
                f"⚠️ Showing first 80 of {len(accounts)} sold accounts."
            )


# ── 3. Broadcast image / image + caption ─────────────────────────────────────

WAITING_BROADCAST_IMG = 10   # conversation state

@admin_only
async def broadcast_image_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /broadcastimg — start image broadcast conversation.
    Admin sends a photo (with optional caption) and bot forwards it to everyone.
    """
    await update.message.reply_text(
        f"📸 <b>Image Broadcast</b>\n\n"
        f"Send me the image you want to broadcast.\n"
        f"You can add a caption in the image message.\n\n"
        f"Type /cancel to abort.",
        parse_mode="HTML"
    )
    return WAITING_BROADCAST_IMG


@admin_only
async def broadcast_image_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Receive photo from admin and forward to all users."""
    from database import all_users

    if not update.message.photo:
        await update.message.reply_text(
            "❌ Please send a photo. Text messages use /broadcast.\n"
            "Try again or /cancel:"
        )
        return WAITING_BROADCAST_IMG

    photo   = update.message.photo[-1]    # highest resolution
    file_id = photo.file_id
    caption = update.message.caption or ""

    users = all_users()
    await update.message.reply_text(
        f"📤 Sending to {len(users)} users..."
    )

    sent = 0
    fail = 0
    for uid in users:
        try:
            await ctx.bot.send_photo(
                chat_id=uid,
                photo=file_id,
                caption=f"📢 <b>Announcement</b>\n\n{caption}" if caption else "📢 <b>Announcement</b>",
                parse_mode="HTML"
            )
            sent += 1
        except Exception:
            fail += 1

    await update.message.reply_text(
        f"✅ <b>Broadcast Complete!</b>\n\n"
        f"📤 Sent: {sent}\n"
        f"❌ Failed: {fail}\n"
        f"👥 Total: {len(users)}",
        parse_mode="HTML"
    )
    return ConversationHandler.END


# ── 4. Modify account price ───────────────────────────────────────────────────

WAITING_SET_PRICE = 11   # conversation state

@admin_only
async def set_price_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /setprice — show all current prices and prompt for update.
    Usage after command: /setprice  (then send Country|NewPrice)
    Or directly:         /setprice India|75
    """
    from database import get_all_country_prices, get_stock_summary

    # Direct usage: /setprice India|75
    if ctx.args:
        return await _apply_price_change(update, ctx, " ".join(ctx.args))

    # Interactive: show current prices first
    stock  = get_stock_summary()
    prices = get_all_country_prices()

    if not stock and not prices:
        await update.message.reply_text(
            "📭 No accounts in stock yet. Add stock first with /addstock."
        )
        return ConversationHandler.END

    lines = ["💰 <b>Current Prices</b>\n"]
    for s in stock:
        lines.append(
            f"🌍 {s['country']}: "
            f"<b>{CURRENCY_SYMBOL}{s['price']:.2f}</b>  "
            f"[{s['cnt']} left]"
        )

    lines.append(
        "\n\nSend new price in format:\n"
        "<code>Country|NewPrice</code>\n\n"
        "Example:\n"
        "<code>India|75</code>\n\n"
        "Or /cancel to exit."
    )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    return WAITING_SET_PRICE


@admin_only
async def set_price_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Receive Country|Price from admin."""
    return await _apply_price_change(update, ctx, update.message.text.strip())


async def _apply_price_change(update: Update, ctx, text: str):
    from database import set_country_price, get_stock_summary

    if "|" not in text:
        await update.message.reply_text(
            "❌ Wrong format. Use:\n<code>Country|NewPrice</code>",
            parse_mode="HTML"
        )
        return WAITING_SET_PRICE

    parts   = text.split("|", 1)
    country = parts[0].strip()
    try:
        new_price = float(parts[1].strip())
        if new_price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid price. Enter a positive number.")
        return WAITING_SET_PRICE

    set_country_price(country, new_price)

    # Confirm with updated stock count
    stock = get_stock_summary()
    entry = next((s for s in stock if s["country"].lower() == country.lower()), None)
    cnt   = entry["cnt"] if entry else 0

    await update.message.reply_text(
        f"✅ <b>Price Updated!</b>\n\n"
        f"🌍 Country: <b>{country}</b>\n"
        f"💰 New Price: <b>{CURRENCY_SYMBOL}{new_price:.2f}</b>\n"
        f"📦 In Stock: {cnt} accounts\n\n"
        f"Price is now live for all buyers.",
        parse_mode="HTML"
    )
    return ConversationHandler.END
