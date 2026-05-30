"""
payment_handlers.py — Manual UPI Payment
=========================================
Flow:
  1. User clicks Add Funds
  2. Bot asks how much to add (min ₹10)
  3. Bot sends QR code + UPI ID
  4. User pays and sends Transaction ID (UTR)
  5. Admin gets a notification with Approve / Reject buttons
  6. On Approve → money added to wallet + user notified
  7. On Reject  → user notified with reason
"""

import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import get_user, create_payment, update_payment_status, update_balance, get_payment
from config import CURRENCY_SYMBOL, UPI_ID, UPI_NAME, UPI_QR_PATH, ADMIN_IDS
from handlers.user_handlers import MAIN_MENU_KEYBOARD

logger = logging.getLogger(__name__)

# Conversation states
WAITING_AMOUNT = 1
WAITING_UTR    = 2


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — User clicks "Add Funds"
# ─────────────────────────────────────────────────────────────────────────────
async def add_funds_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    user = get_user(q.from_user.id)
    bal  = user["balance"] if user else 0.0

    await q.edit_message_text(
        f"➕ <b>Add Funds to Wallet</b>\n\n"
        f"💰 Current Balance: <b>{CURRENCY_SYMBOL}{bal:.2f}</b>\n"
        f"💳 Payment Mode: <b>Manual UPI</b>\n\n"
        f"Enter the amount you want to add (minimum {CURRENCY_SYMBOL}10):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="wallet_menu")]
        ])
    )
    return WAITING_AMOUNT


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Receive amount → send QR code + UPI details
# ─────────────────────────────────────────────────────────────────────────────
async def receive_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number (e.g. 200):")
        return WAITING_AMOUNT

    if amount < 10:
        await update.message.reply_text(f"❌ Minimum deposit is {CURRENCY_SYMBOL}10. Please try again:")
        return WAITING_AMOUNT

    ctx.user_data["pay_amount"] = amount
    return await _send_upi_details(update, ctx, amount)


async def _send_upi_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE, amount: float):
    caption = (
        f"📲 <b>Pay via UPI</b>\n\n"
        f"💵 Amount: <b>{CURRENCY_SYMBOL}{amount:.2f}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏦 UPI ID: <code>{UPI_ID}</code>\n"
        f"👤 Name: <b>{UPI_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Steps to pay:</b>\n"
        f"1️⃣ Open PhonePe / GPay / Paytm / Any UPI app\n"
        f"2️⃣ Scan the QR code or pay to UPI ID above\n"
        f"3️⃣ Enter exact amount <b>{CURRENCY_SYMBOL}{amount:.2f}</b>\n"
        f"4️⃣ Complete the payment\n"
        f"5️⃣ Send your <b>Transaction ID / UTR</b> below ⬇️\n\n"
        f"⚠️ <i>Do NOT close this chat until you send the Transaction ID.</i>"
    )

    qr_sent = False
    if UPI_QR_PATH and os.path.exists(UPI_QR_PATH):
        try:
            with open(UPI_QR_PATH, "rb") as f:
                await update.message.reply_photo(photo=f, caption=caption, parse_mode="HTML")
            qr_sent = True
        except Exception as e:
            logger.warning(f"Could not send QR image: {e}")

    if not qr_sent:
        await update.message.reply_text(caption, parse_mode="HTML")

    return WAITING_UTR


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Receive Transaction ID (UTR) → save + notify admin
# ─────────────────────────────────────────────────────────────────────────────
async def receive_utr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    utr    = update.message.text.strip()
    amount = ctx.user_data.get("pay_amount", 0)
    u      = update.effective_user

    # Basic UTR validation
    if len(utr) < 6 or len(utr) > 50 or " " in utr:
        await update.message.reply_text(
            "❌ Invalid Transaction ID.\n\n"
            "Please copy it directly from your payment app and try again:"
        )
        return WAITING_UTR

    # Save pending payment in DB
    pay_id = create_payment(u.id, amount, utr)

    # Confirm to user
    await update.message.reply_text(
        f"✅ <b>Payment Request Submitted!</b>\n\n"
        f"💰 Amount: <b>{CURRENCY_SYMBOL}{amount:.2f}</b>\n"
        f"🔢 Transaction ID: <code>{utr}</code>\n"
        f"🆔 Request ID: <code>#{pay_id}</code>\n\n"
        f"⏳ Admin will verify your payment and credit your wallet shortly.\n"
        f"You will be notified once approved.",
        parse_mode="HTML",
        reply_markup=MAIN_MENU_KEYBOARD
    )

    # Notify all admins with Approve / Reject buttons
    username_str = f"@{u.username}" if u.username else "no username"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_pay_{pay_id}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject_pay_{pay_id}"),
    ]])

    for admin_id in ADMIN_IDS:
        try:
            await ctx.bot.send_message(
                admin_id,
                f"💰 <b>New Payment Request #{pay_id}</b>\n\n"
                f"👤 <b>User:</b> {u.full_name} ({username_str})\n"
                f"🆔 <b>User ID:</b> <code>{u.id}</code>\n"
                f"💵 <b>Amount:</b> {CURRENCY_SYMBOL}{amount:.2f}\n"
                f"🔢 <b>Transaction ID:</b> <code>{utr}</code>\n\n"
                f"Please verify the payment and approve or reject below:",
                parse_mode="HTML",
                reply_markup=kb
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
# Cancel
# ─────────────────────────────────────────────────────────────────────────────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=MAIN_MENU_KEYBOARD)
    return ConversationHandler.END
