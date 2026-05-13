import asyncio
import logging
import os
from datetime import datetime, timezone

import aiosqlite
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from .database import DB_PATH, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://localhost:8000")
ADMIN_IDS = [1977007206, 1322034030]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "User"

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Подтвердить ID", callback_data="confirm_id")]]
    )
    await update.message.reply_text(
        f"<b>Promo Empire</b>\n\n"
        f"👤 {first_name} · <code>{user_id}</code>\n\n"
        f"Подтвердите ID для доступа.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def confirm_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id

    await query.answer(f"ID подтверждён: {user_id}", show_alert=False)

    # Edit original message to show confirmed state
    await query.edit_message_text(
        f"<b>Promo Empire</b>\n\n"
        f"👤 {user.first_name or 'User'} · <code>{user_id}</code>\n"
        f"✓ ID подтверждён",
        parse_mode="HTML",
    )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("PROMO", web_app=WebAppInfo(url=WEBAPP_URL))]]
    )
    await query.message.reply_text(
        f"<b>Менеджер промо-кампаний</b>\n\n"
        f"▸ Управление промо и дедлайнами\n"
        f"▸ Конвертер USDT/RUB\n"
        f"▸ Уведомления о сроках\n\n"
        f"Открыть 👇",
        reply_markup=keyboard,
        parse_mode="HTML",
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
        f"📊 Статистика:\n\n"
        f"Промо: {promo_count}\n"
        f"Готово: {done_count}\n"
        f"В процессе: {in_progress_count}\n"
        f"Не готово: {promo_count - done_count - in_progress_count}"
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
    notified = set()
    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                rows = await db.execute(
                    "SELECT * FROM promos WHERE status != 'done' AND deadline IS NOT NULL"
                )
                promos_list = await rows.fetchall()
                now = datetime.now(timezone.utc)
                for promo in promos_list:
                    try:
                        dl = datetime.fromisoformat(promo["deadline"].replace(" ", "T"))
                        diff = (dl - now).total_seconds()
                        key_24 = f"{promo['id']}_24h"
                        key_1 = f"{promo['id']}_1h"
                        key_over = f"{promo['id']}_over"
                        if 0 < diff <= 86400 and key_24 not in notified:
                            hours = int(diff // 3600)
                            await application.bot.send_message(
                                chat_id=promo["user_id"],
                                text=f"⏰ До дедлайна ~{hours}ч\n{promo['name']}",
                            )
                            notified.add(key_24)
                        elif 0 < diff <= 3600 and key_1 not in notified:
                            mins = int(diff // 60)
                            await application.bot.send_message(
                                chat_id=promo["user_id"],
                                text=f"🔴 До дедлайна {mins} мин!\n{promo['name']}",
                            )
                            notified.add(key_1)
                        elif diff <= 0 and key_over not in notified:
                            await application.bot.send_message(
                                chat_id=promo["user_id"],
                                text=f"⚠️ Дедлайн прошёл!\n{promo['name']}",
                            )
                            notified.add(key_over)
                    except Exception as e:
                        logger.error(f"Deadline notify error promo {promo['id']}: {e}")
        except Exception as e:
            logger.error(f"Deadline check error: {e}")
        await asyncio.sleep(60)


async def check_payment_overdue(application: Application):
    notified_payments = set()
    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                rows = await db.execute(
                    "SELECT * FROM promos WHERE status = 'done' AND payment_status = 'pending' AND price_usdt > 0"
                )
                overdue = await rows.fetchall()
                for promo in overdue:
                    key = f"pay_{promo['id']}"
                    if key not in notified_payments:
                        try:
                            adv = promo["advertiser_name"] or "рекламодателю"
                            await application.bot.send_message(
                                chat_id=promo["user_id"],
                                text=f"💰 Пора напомнить {adv}, что пора платить по счетам!\n"
                                     f"Промо: {promo['name']}\n"
                                     f"Сумма: ${promo['price_usdt']} USDT",
                            )
                            notified_payments.add(key)
                        except Exception as e:
                            logger.error(f"Payment notify error promo {promo['id']}: {e}")
        except Exception as e:
            logger.error(f"Payment check error: {e}")
        await asyncio.sleep(3600)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if telegram_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        users = await (await db.execute("SELECT COUNT(*) as cnt FROM users")).fetchone()
        promos = await (await db.execute("SELECT COUNT(*) as cnt FROM promos")).fetchone()
        done = await (await db.execute("SELECT COUNT(*) as cnt FROM promos WHERE status = 'done'")).fetchone()
    await update.message.reply_text(
        f"🔧 Система\n\n"
        f"Пользователей: {users['cnt']}\n"
        f"Промо: {promos['cnt']}\n"
        f"Выполнено: {done['cnt']}\n\n"
        f"/broadcast <текст> — рассылка"
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
    application.add_handler(CallbackQueryHandler(confirm_id_callback, pattern="^confirm_id$"))
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
            payment_task = asyncio.create_task(check_payment_overdue(application))
            try:
                await asyncio.Event().wait()
            finally:
                reminder_task.cancel()
                deadline_task.cancel()
                payment_task.cancel()
                await application.updater.stop()
                await application.stop()

    loop.run_until_complete(run())


if __name__ == "__main__":
    main()
