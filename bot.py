"""
Render Max-Power Telegram Bot
DEBUG VERSION
"""
import os
import logging
import sys
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from aiohttp import web

# ─── Configuration ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "9129907249:AAE31Px34Hp0jooFz-foXtZINA7dM_iLAzI")
DATABASE_URL = os.environ.get("DATABASE_URL")
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://render-telegram-bot-rruj.onrender.com")
PORT = int(os.environ.get("PORT", 10000))

# ─── DEBUGGING SETUP ────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("MAX_POWER_DEBUG")
logger.info("DEBUG MODE ENABLED: All logs will be streamed to stdout")

# ─── Database Pool ──────────────────────────────────────────────
db_pool: Optional[SimpleConnectionPool] = None

def init_db():
    global db_pool
    logger.debug(f"Attempting DB init with URL: {DATABASE_URL[:15]}..." if DATABASE_URL else "No DATABASE_URL provided")
    if DATABASE_URL:
        try:
            db_pool = SimpleConnectionPool(1, 5, DATABASE_URL)
            with db_pool.getconn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS users (
                            user_id BIGINT PRIMARY KEY,
                            username TEXT,
                            first_name TEXT,
                            last_name TEXT,
                            joined_at TIMESTAMP DEFAULT NOW(),
                            last_seen TIMESTAMP DEFAULT NOW(),
                            message_count INT DEFAULT 0
                        );
                    """)
                    conn.commit()
            logger.info("✅ Database initialized successfully")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
    else:
        logger.warning("⚠️ DATABASE_URL not set - Persistence disabled")

def upsert_user(user):
    if not db_pool: return
    try:
        with db_pool.getconn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users (user_id, username, first_name, last_name, last_seen, message_count) VALUES (%s, %s, %s, %s, NOW(), 1) ON CONFLICT (user_id) DO UPDATE SET last_seen = NOW(), message_count = users.message_count + 1", (user.id, user.username, user.first_name, user.last_name))
                conn.commit()
    except Exception as e:
        logger.error(f"DB Upsert Error: {e}")

# ─── Bot Handlers ───────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.debug(f"START command received from {update.effective_user.id}")
    user = update.effective_user
    upsert_user(user)
    await update.message.reply_text(f"DEBUG ACTIVE: @{user.username}, bot is responding!")

async def debug_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.debug("DEBUG_STATUS command received")
    status = {
        "token_set": bool(TELEGRAM_TOKEN),
        "db_connected": db_pool is not None,
        "render_url": RENDER_URL,
        "timestamp": datetime.utcnow().isoformat()
    }
    await update.message.reply_text(f"🛠 *Debug Status:*\n`{status}`", parse_mode="Markdown")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.debug(f"Message from {update.effective_user.id}: {update.message.text}")
    await update.message.reply_text(f"DEBUG: Received your message: {update.message.text}")

# ─── Webhook Server ─────────────────────────────────────────────
async def handle_webhook(request: web.Request) -> web.Response:
    try:
        body = await request.text()
        logger.debug(f"RAW WEBHOOK BODY: {body}")
        data = await request.json()
        logger.debug(f"JSON WEBHOOK DATA: {data}")
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}", exc_info=True)
        return web.Response(status=500, text=str(e))

async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "healthy", "db": "ok" if db_pool else "no"})

async def handle_debug_page(request: web.Request) -> web.Response:
    return web.Response(text=f"Bot is running. Token: {TELEGRAM_TOKEN[:5]}... URL: {RENDER_URL}")

async def on_startup(app: web.Application):
    webhook_url = f"{RENDER_URL}/webhook"
    logger.info(f"Setting webhook to {webhook_url}")
    try:
        await application.bot.set_webhook(webhook_url, drop_pending_updates=True)
        logger.info("✅ Webhook set successfully")
    except Exception as e:
        logger.error(f"❌ Webhook set failed: {e}")

# ─── Main ───────────────────────────────────────────────────────
application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("debug", debug_status))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

init_db()

web_app = web.Application()
web_app.router.add_get("/health", handle_health)
web_app.router.add_get("/debug_page", handle_debug_page)
web_app.router.add_post("/webhook", handle_webhook)
web_app.on_startup.append(on_startup)

if __name__ == "__main__":
    logger.info(f"🚀 DEBUG SERVER STARTING ON PORT {PORT}")
    web.run_app(web_app, host="0.0.0.0", port=PORT)
