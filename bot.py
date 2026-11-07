"""
Render Max-Power Telegram Bot
Free tier optimized with webhook support, PostgreSQL persistence, and keep-alive endpoint.
"""
import os
import logging
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

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN environment variable is required")

# ─── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)

# ─── Database Pool ──────────────────────────────────────────────
db_pool: Optional[SimpleConnectionPool] = None

def init_db():
    """Initialize database connection pool and schema."""
    global db_pool
    if DATABASE_URL:
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
                    CREATE TABLE IF NOT EXISTS logs (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT REFERENCES users(user_id),
                        message TEXT,
                        response TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                """)
                conn.commit()
        logger.info("✅ Database initialized")
    else:
        logger.warning("⚠️ DATABASE_URL not set - running without persistence")

def upsert_user(user):
    """Insert or update user in database."""
    if not db_pool:
        return
    with db_pool.getconn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, last_seen, message_count)
                VALUES (%s, %s, %s, %s, NOW(), 1)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    last_seen = NOW(),
                    message_count = users.message_count + 1
            """, (user.id, user.username, user.first_name, user.last_name))
            conn.commit()

def log_interaction(user_id: int, message: str, response: str):
    """Log message/response pair."""
    if not db_pool:
        return
    with db_pool.getconn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO logs (user_id, message, response) VALUES (%s, %s, %s)",
                (user_id, message, response)
            )
            conn.commit()

# ─── Bot Handlers ───────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)
    
    keyboard = [
        [InlineKeyboardButton("📊 My Stats", callback_data="stats")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh")],
        [InlineKeyboardButton("ℹ️ About This Bot", callback_data="about")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = (
        f"🚀 *Render Max-Power Bot Active!*\n\n"
        f"Hey {user.first_name}! I'm running on Render's **free tier** with:\n"
        f"• 🌐 Web Service (auto-sleeps without keep-alive)\n"
        f"• 🐘 PostgreSQL (free 90 days)\n"
        f"• 🔄 Webhook mode (instant responses)\n"
        f"• 💾 Full persistence\n\n"
        f"Use the buttons below or send any message!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    log_interaction(user.id, "/start", "welcome_message")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 *Available Commands:*\n"
        "/start - Show main menu\n"
        "/help - This message\n"
        "/stats - Your usage statistics\n"
        "/dbtest - Test database connection\n"
        "/health - Health check endpoint\n"
        "/ping - Keep-alive test\n\n"
        "💡 *Tip:* This bot uses webhooks for instant responses!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    log_interaction(update.effective_user.id, "/help", "help_message")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)
    
    if not db_pool:
        await update.message.reply_text("❌ Database not configured")
        return
    
    with db_pool.getconn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT message_count, joined_at, last_seen FROM users WHERE user_id = %s",
                (user.id,)
            )
            row = cur.fetchone()
    
    if row:
        count, joined, last_seen = row
        msg = (
            f"📊 *Your Stats*\n"
            f"Messages sent: {count}\n"
            f"Joined: {joined.strftime('%Y-%m-%d %H:%M')}\n"
            f"Last seen: {last_seen.strftime('%Y-%m-%d %H:%M')}"
        )
    else:
        msg = "No stats found. Send a message first!"
    
    await update.message.reply_text(msg, parse_mode="Markdown")
    log_interaction(user.id, "/stats", "stats_response")

async def dbtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db_pool:
        await update.message.reply_text("❌ DATABASE_URL not set")
        return
    try:
        with db_pool.getconn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
        await update.message.reply_text(f"✅ *Database Connected*\n```\n{version}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Database error: {e}")

async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Health check - also used by uptime monitors."""
    status = {
        "bot": "healthy",
        "database": "connected" if db_pool else "not configured",
        "timestamp": datetime.utcnow().isoformat(),
        "render_url": RENDER_URL,
    }
    await update.message.reply_text(f"🏥 *Health Check*\n```json\n{status}\n```", parse_mode="Markdown")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple ping for keep-alive."""
    await update.message.reply_text("🏓 Pong!")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)
    
    text = update.message.text
    response = f"Echo: {text}"
    
    # Add some fun responses
    if text.lower() in ["hello", "hi", "hey"]:
        response = f"Hey there, {user.first_name}! 👋"
    elif "render" in text.lower():
        response = "🚀 Render.com - Best free cloud hosting!"
    elif "github" in text.lower():
        response = "🐙 GitHub - Where code lives!"
    elif "?" in text:
        response = "Good question! 🤔"
    
    await update.message.reply_text(response)
    log_interaction(user.id, text, response)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    upsert_user(user)
    
    if query.data == "stats":
        if not db_pool:
            await query.edit_message_text("❌ Database not configured")
            return
        with db_pool.getconn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT message_count, joined_at FROM users WHERE user_id = %s", (user.id,))
                row = cur.fetchone()
        if row:
            count, joined = row
            await query.edit_message_text(f"📊 Messages: {count}\nJoined: {joined.strftime('%Y-%m-%d')}")
    
    elif query.data == "refresh":
        await query.edit_message_text("🔄 Refreshed! " + datetime.utcnow().strftime("%H:%M:%S"))
    
    elif query.data == "about":
        await query.edit_message_text(
            "🤖 *About This Bot*\n\n"
            "Running on Render Free Tier:\n"
            "• Python 3.11 + python-telegram-bot v20\n"
            "• PostgreSQL (90 days free)\n"
            "• Webhook mode for zero latency\n"
            "• Auto-deploy from GitHub\n\n"
            "Source: github.com/plasma4peace/render-telegram-bot",
            parse_mode="Markdown"
        )

# ─── Webhook Server ─────────────────────────────────────────────
async def handle_webhook(request: web.Request) -> web.Response:
    """Process incoming Telegram webhook."""
    try:
        data = await request.json()
        logger.debug(f"Webhook received: {data}")
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.Response(status=500, text=str(e))

async def handle_health(request: web.Request) -> web.Response:
    """Health endpoint for Render + uptime monitors."""
    return web.json_response({
        "status": "healthy",
        "database": "connected" if db_pool else "not configured",
        "timestamp": datetime.utcnow().isoformat(),
    })

async def handle_root(request: web.Request) -> web.Response:
    """Root endpoint - keep-alive target."""
    return web.Response(text="🤖 Render Telegram Bot is running!")

async def handle_debug(request: web.Request) -> web.Response:
    """Debug endpoint to check bot status."""
    return web.json_response({
        "bot_token_set": bool(TELEGRAM_TOKEN),
        "render_url": RENDER_URL,
        "port": PORT,
        "database_url_set": bool(DATABASE_URL),
        "db_pool_active": db_pool is not None,
    })

async def on_startup(app: web.Application):
    """Set webhook on startup."""
    webhook_url = f"{RENDER_URL}/webhook"
    logger.info(f"Setting webhook to: {webhook_url}")
    try:
        await application.bot.set_webhook(webhook_url, drop_pending_updates=True)
        logger.info(f"✅ Webhook set successfully to {webhook_url}")
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")

async def on_shutdown(app: web.Application):
    """Cleanup on shutdown."""
    await application.bot.delete_webhook()
    if db_pool:
        db_pool.closeall()
    logger.info("🛑 Shutdown complete")

# ─── Main ───────────────────────────────────────────────────────
# Build application
application = (
    ApplicationBuilder()
    .token(TELEGRAM_TOKEN)
    .build()
)

# Add handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_cmd))
application.add_handler(CommandHandler("stats", stats))
application.add_handler(CommandHandler("dbtest", dbtest))
application.add_handler(CommandHandler("health", health))
application.add_handler(CommandHandler("ping", ping))
application.add_handler(CallbackQueryHandler(button_callback))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# Initialize database
init_db()

# Create aiohttp app
web_app = web.Application()
web_app.router.add_get("/", handle_root)
web_app.router.add_get("/health", handle_health)
web_app.router.add_get("/debug", handle_debug)
web_app.router.add_post("/webhook", handle_webhook)
web_app.on_startup.append(on_startup)
web_app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    logger.info(f"🚀 Starting server on port {PORT}")
    logger.info(f"🌐 Render URL: {RENDER_URL}")
    logger.info(f"🔗 Webhook URL: {RENDER_URL}/webhook")
    web.run_app(web_app, host="0.0.0.0", port=PORT)
