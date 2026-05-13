import asyncio
import logging
import os
from datetime import datetime, timezone

import aiosqlite
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

from .database import DB_PATH, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://localhost:8000")
ADMIN_IDS = [1977007206, 1322034030]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📊 Открыть менеджер",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ]
    )
    await update.message.reply_text(
        "👋 Привет! Я твой менеджер рекламных кампаний.\n\n"
        "Здесь ты можешь:\n"
        "• Добавлять рекламодателей\n"
        "• Управлять промо-ссылками\n"
        "• Ставить дедлайны и статусы\n"
        "• Вести заметки\n"
        "• Конвертировать USDT/RUB\n"
        "• Получать уведомления\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение 👇",
        reply_markup=keyboard,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📌 Команды:\n"
        "/start — Открыть приложение\n"
        "/help — Показать помощь\n"
        "/stats — Краткая статистика\n\n"
        "Всё управление — через мини-приложение 👇"
    )
    if update.effective_user.id in ADMIN_IDS:
        text += (
            "\n\n🔧 Админ-команды:\n"
            "/admin — Статистика системы\n"
            "/broadcast <текст> — Рассылка всем"
        )
    await update.message.reply_text(text)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        adv = await db.execute(
            "SELECT COUNT(*) as cnt FROM advertisers WHERE user_id = ?",
            (telegram_id,),
        )
        adv_count = (await adv.fetchone())["cnt"]

        promo = await db.execute(
            "SELECT COUNT(*) as cnt FROM promos WHERE user_id = ?",
            (telegram_id,),
        )
        promo_count = (await promo.fetchone())["cnt"]

        done = await db.execute(
            "SELECT COUNT(*) as cnt FROM promos WHERE user_id = ? AND status = 'done'",
            (telegram_id,),
        )
        done_count = (await done.fetchone())["cnt"]

        in_progress = await db.execute(
            "SELECT COUNT(*) as cnt FROM promos WHERE user_id = ? AND status = 'in_progress'",
            (telegram_id,),
        )
        in_progress_count = (await in_progress.fetchone())["cnt"]

    await update.message.reply_text(
        f"📊 Твоя статистика:\n\n"
        f"👤 Рекламодателей: {adv_count}\n"
        f"🔗 Промо всего: {promo_count}\n"
        f"✅ Готово: {done_count}\n"
        f"⏳ В процессе: {in_progress_count}\n"
        f"❌ Не готово: {promo_count - done_count - in_progress_count}"
    )


async def send_reminder_notifications(application: Application):
    while True:
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                rows = await db.execute(
                    "SELECT r.*, p.name as promo_name FROM reminders r LEFT JOIN promos p ON r.promo_id = p.id WHERE r.sent = 0 AND r.remind_at <= ?",
                    (now,),
                )
                reminders = await rows.fetchall()
                for reminder in reminders:
                    try:
                        text = f"🔔 Напоминание!\n"
                        if reminder["promo_name"]:
                            text += f"Промо: {reminder['promo_name']}\n"
                        if reminder["message"]:
                            text += f"Сообщение: {reminder['message']}"
                        await application.bot.send_message(
                            chat_id=reminder["user_id"], text=text
                        )
                        await db.execute(
                            "UPDATE reminders SET sent = 1 WHERE id = ?",
                            (reminder["id"],),
                        )
                    except Exception as e:
                        logger.error(f"Failed to send reminder {reminder['id']}: {e}")
                await db.commit()
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
        await asyncio.sleep(30)


async def check_deadlines(application: Application):
    while True:
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                rows = await db.execute(
                    "SELECT p.*, a.name as advertiser_name FROM promos p LEFT JOIN advertisers a ON p.advertiser_id = a.id WHERE p.status != 'done' AND p.deadline IS NOT NULL AND p.deadline <= ? AND p.deadline > datetime(?, '-1 hour')",
                    (now, now),
                )
                promos = await rows.fetchall()
                for promo in promos:
                    try:
                        text = (
                            f"⚠️ Дедлайн наступил!\n\n"
                            f"📋 Промо: {promo['name']}\n"
                            f"👤 Рекламодатель: {promo['advertiser_name'] or '—'}\n"
                            f"📅 Дедлайн: {promo['deadline']}\n"
                            f"Статус: {'⏳ В процессе' if promo['status'] == 'in_progress' else '❌ Не готово'}"
                        )
                        await application.bot.send_message(
                            chat_id=promo["user_id"], text=text
                        )
                    except Exception as e:
                        logger.error(f"Failed deadline notification for promo {promo['id']}: {e}")
        except Exception as e:
            logger.error(f"Deadline check error: {e}")
        await asyncio.sleep(60)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if telegram_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        users = await (await db.execute("SELECT COUNT(*) as cnt FROM users")).fetchone()
        advs = await (await db.execute("SELECT COUNT(*) as cnt FROM advertisers")).fetchone()
        promos = await (await db.execute("SELECT COUNT(*) as cnt FROM promos")).fetchone()
        done = await (await db.execute("SELECT COUNT(*) as cnt FROM promos WHERE status = 'done'")).fetchone()
    await update.message.reply_text(
        f"🔧 Админ-панель\n\n"
        f"Пользователей: {users['cnt']}\n"
        f"Рекламодателей: {advs['cnt']}\n"
        f"Промо всего: {promos['cnt']}\n"
        f"Выполнено: {done['cnt']}\n\n"
        f"Команды:\n"
        f"/broadcast <текст> — рассылка всем"
    )


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if telegram_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Использование: /broadcast <текст сообщения>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute("SELECT telegram_id FROM users")
        users = await rows.fetchall()
    sent = 0
    failed = 0
    for user in users:
        try:
            await update.get_bot().send_message(chat_id=user["telegram_id"], text=text)
            sent += 1
        except Exception as e:
            logger.error(f"Broadcast to {user['telegram_id']} failed: {e}")
            failed += 1
    await update.message.reply_text(f"Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}")


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        await init_db()
        async with application:
            await application.start()
            await application.updater.start_polling()
            reminder_task = asyncio.create_task(send_reminder_notifications(application))
            deadline_task = asyncio.create_task(check_deadlines(application))
            try:
                await asyncio.Event().wait()
            finally:
                reminder_task.cancel()
                deadline_task.cancel()
                await application.updater.stop()
                await application.stop()

    loop.run_until_complete(run())


if __name__ == "__main__":
    main()
