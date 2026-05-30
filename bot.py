"""
bot.py — Main entry point
Starts the Telegram bot with manual UPI payment flow.
"""
import logging
import asyncio
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
from config import BOT_TOKEN
from handlers import user_handlers, payment_handlers, admin_handlers, account_handlers
from handlers.user_handlers import BTN_BUY, BTN_WALLET, BTN_PROFILE, BTN_ORDERS, BTN_SUPPORT

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

WAITING_AMOUNT        = 1
WAITING_UTR           = 2
WAITING_ADD_ACCOUNT   = 3
WAITING_SUPPORT_MSG   = 4
WAITING_BROADCAST_IMG = 10
WAITING_SET_PRICE     = 11

MENU_BUTTONS_FILTER = filters.Regex(
    f"^({BTN_BUY}|{BTN_WALLET}|{BTN_PROFILE}|{BTN_ORDERS}|{BTN_SUPPORT})$"
)


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # ── User commands ──────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",   user_handlers.start))
    app.add_handler(CommandHandler("wallet",  user_handlers.wallet))
    app.add_handler(CommandHandler("profile", user_handlers.profile))
    app.add_handler(CommandHandler("orders",  user_handlers.order_history))

    # ── Admin commands ─────────────────────────────────────────────────────
    app.add_handler(CommandHandler("admin",         admin_handlers.admin_panel))
    app.add_handler(CommandHandler("addstock",      admin_handlers.add_stock_cmd))
    app.add_handler(CommandHandler("pendingpay",    admin_handlers.list_pending_payments))
    app.add_handler(CommandHandler("broadcast",     admin_handlers.broadcast))
    app.add_handler(CommandHandler("checksessions", admin_handlers.check_sessions_cmd))
    app.add_handler(CommandHandler("otp",           admin_handlers.send_otp))
    app.add_handler(CommandHandler("buyers",        admin_handlers.active_buyers))
    app.add_handler(CommandHandler("accounts",      admin_handlers.accounts_list))
    app.add_handler(CommandHandler("setprice",      admin_handlers.set_price_cmd))
    app.add_handler(CommandHandler("broadcastimg",  admin_handlers.broadcast_image_start))

    # ── Add Funds conversation ─────────────────────────────────────────────
    add_funds_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(payment_handlers.add_funds_start, pattern="^add_funds$")],
        states={
            WAITING_AMOUNT: [MessageHandler(
                filters.TEXT & ~filters.COMMAND & ~MENU_BUTTONS_FILTER,
                payment_handlers.receive_amount
            )],
            WAITING_UTR: [MessageHandler(
                filters.TEXT & ~filters.COMMAND & ~MENU_BUTTONS_FILTER,
                payment_handlers.receive_utr
            )],
        },
        fallbacks=[
            CommandHandler("cancel", payment_handlers.cancel),
            MessageHandler(MENU_BUTTONS_FILTER, payment_handlers.cancel),
        ],
    )
    app.add_handler(add_funds_conv)

    # ── Support conversation ───────────────────────────────────────────────
    support_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(user_handlers.support_start, pattern="^support$"),
            MessageHandler(filters.Regex(f"^{BTN_SUPPORT}$"), user_handlers._show_support),
        ],
        states={
            WAITING_SUPPORT_MSG: [MessageHandler(
                filters.TEXT & ~filters.COMMAND & ~MENU_BUTTONS_FILTER,
                user_handlers.support_message
            )],
        },
        fallbacks=[
            CommandHandler("cancel", payment_handlers.cancel),
            MessageHandler(MENU_BUTTONS_FILTER, payment_handlers.cancel),
        ],
    )
    app.add_handler(support_conv)

    # ── Add stock conversation (Admin) ─────────────────────────────────────
    add_stock_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_handlers.add_stock_start, pattern="^admin_addstock_")],
        states={
            WAITING_ADD_ACCOUNT: [MessageHandler(
                filters.TEXT & ~filters.COMMAND & ~MENU_BUTTONS_FILTER,
                admin_handlers.receive_stock
            )],
        },
        fallbacks=[CommandHandler("cancel", payment_handlers.cancel)],
    )
    app.add_handler(add_stock_conv)

    # ── Persistent menu button handler ─────────────────────────────────────
    app.add_handler(MessageHandler(MENU_BUTTONS_FILTER, user_handlers.button_handler))

    # ── Callback buttons ───────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(user_handlers.main_menu,        pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(user_handlers.wallet_menu,      pattern="^wallet_menu$"))
    app.add_handler(CallbackQueryHandler(user_handlers.profile_cb,       pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(user_handlers.order_history_cb, pattern="^order_history$"))
    app.add_handler(CallbackQueryHandler(account_handlers.buy_accounts,  pattern="^buy_accounts$"))
    app.add_handler(CallbackQueryHandler(account_handlers.select_country,pattern="^country_"))
    app.add_handler(CallbackQueryHandler(account_handlers.confirm_buy,   pattern="^confirm_buy_"))
    app.add_handler(CallbackQueryHandler(account_handlers.page_nav,      pattern="^page_"))
    app.add_handler(CallbackQueryHandler(account_handlers.get_code,      pattern="^getcode_"))
    app.add_handler(CallbackQueryHandler(admin_handlers.approve_payment, pattern="^approve_pay_"))
    app.add_handler(CallbackQueryHandler(admin_handlers.reject_payment,  pattern="^reject_pay_"))
    app.add_handler(CallbackQueryHandler(admin_handlers.delete_dead_cb,  pattern="^admin_delete_dead$"))
    app.add_handler(CallbackQueryHandler(admin_handlers.admin_panel_cb,  pattern="^admin_"))

    return app


async def main():
    app = build_app()
    await app.initialize()

    logger.info("🤖 Starting bot with Manual UPI Payment...")
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("✅ Bot is running! Manual UPI payment flow active.")
    logger.info(f"   Admins will receive payment requests to approve/reject.")

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
