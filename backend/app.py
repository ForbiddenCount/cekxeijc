import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, unquote

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .database import DB_PATH, get_db, init_db

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [1977007206, 1322034030]


def verify_telegram_data(init_data: str) -> dict | None:
    if not BOT_TOKEN:
        return None
    parsed = parse_qs(init_data)
    check_hash = parsed.get("hash", [None])[0]
    if not check_hash:
        return None
    data_pairs = []
    for key, values in parsed.items():
        if key == "hash":
            continue
        data_pairs.append(f"{key}={unquote(values[0])}")
    data_pairs.sort()
    data_check_string = "\n".join(data_pairs)
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(computed_hash, check_hash):
        return None
    user_data = parsed.get("user", [None])[0]
    if user_data:
        return json.loads(unquote(user_data))
    return None


async def get_current_user(x_telegram_init_data: str = Header(default="")):
    if not x_telegram_init_data:
        raise HTTPException(401, "Missing Telegram init data")
    if not BOT_TOKEN:
        try:
            return json.loads(x_telegram_init_data)
        except Exception:
            return {"id": 0, "first_name": "Dev"}
    user = verify_telegram_data(x_telegram_init_data)
    if not user:
        raise HTTPException(401, "Invalid Telegram init data")
    return user


def is_admin(user: dict) -> bool:
    return user.get("id", 0) in ADMIN_IDS


async def require_admin(user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Admin access required")
    return user


@asynccontextmanager
async def lifespan(application: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Ad Manager Bot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "frontend", "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "frontend", "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


# ── Users ──

@app.post("/api/auth")
async def auth_user(user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    username = user.get("username", "")
    first_name = user.get("first_name", "")
    last_name = user.get("last_name", "")
    existing = await db.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    )
    row = await existing.fetchone()
    if not row:
        await db.execute(
            "INSERT INTO users (telegram_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
            (telegram_id, username, first_name, last_name),
        )
        await db.commit()
        existing = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await existing.fetchone()
    result = dict(row)
    result["is_admin"] = is_admin(user)
    return result


@app.get("/api/profile")
async def get_profile(user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    row = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    profile = await row.fetchone()
    if not profile:
        raise HTTPException(404, "User not found")

    adv_count = await db.execute(
        "SELECT COUNT(*) as cnt FROM advertisers WHERE user_id = ?", (telegram_id,)
    )
    adv = await adv_count.fetchone()

    promo_count = await db.execute(
        "SELECT COUNT(*) as cnt FROM promos WHERE user_id = ?", (telegram_id,)
    )
    promo = await promo_count.fetchone()

    done_count = await db.execute(
        "SELECT COUNT(*) as cnt FROM promos WHERE user_id = ? AND status = 'done'",
        (telegram_id,),
    )
    done = await done_count.fetchone()

    yokoso_total = await db.execute(
        "SELECT COUNT(*) as cnt FROM promos WHERE user_id = ? AND category = 'yokoso'", (telegram_id,)
    )
    yokoso_t = await yokoso_total.fetchone()
    yokoso_done = await db.execute(
        "SELECT COUNT(*) as cnt FROM promos WHERE user_id = ? AND category = 'yokoso' AND status = 'done'", (telegram_id,)
    )
    yokoso_d = await yokoso_done.fetchone()

    sako_total = await db.execute(
        "SELECT COUNT(*) as cnt FROM promos WHERE user_id = ? AND category = 'sako'", (telegram_id,)
    )
    sako_t = await sako_total.fetchone()
    sako_done = await db.execute(
        "SELECT COUNT(*) as cnt FROM promos WHERE user_id = ? AND category = 'sako' AND status = 'done'", (telegram_id,)
    )
    sako_d = await sako_done.fetchone()

    return {
        **dict(profile),
        "promos_count": promo["cnt"],
        "done_count": done["cnt"],
        "yokoso_total": yokoso_t["cnt"],
        "yokoso_done": yokoso_d["cnt"],
        "sako_total": sako_t["cnt"],
        "sako_done": sako_d["cnt"],
        "is_admin": telegram_id in ADMIN_IDS,
    }


@app.get("/api/avatar/{user_id}")
async def get_avatar(user_id: int):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos?user_id={user_id}&limit=1")
            data = resp.json()
            if not data.get("ok") or not data["result"]["photos"]:
                raise HTTPException(404, "No avatar")
            file_id = data["result"]["photos"][0][-1]["file_id"]
            file_resp = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}")
            file_data = file_resp.json()
            if not file_data.get("ok"):
                raise HTTPException(404, "No avatar")
            file_path = file_data["result"]["file_path"]
            photo_resp = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
            return Response(content=photo_resp.content, media_type="image/jpeg")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(404, "No avatar")


# ── Advertisers ──

@app.get("/api/advertisers")
async def list_advertisers(user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    rows = await db.execute(
        "SELECT * FROM advertisers WHERE user_id = ? ORDER BY created_at DESC",
        (telegram_id,),
    )
    return [dict(r) for r in await rows.fetchall()]


@app.post("/api/advertisers")
async def create_advertiser(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "INSERT INTO advertisers (user_id, name, username, link, notes) VALUES (?, ?, ?, ?, ?)",
        (telegram_id, data["name"], data.get("username", ""), data.get("link", ""), data.get("notes", "")),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM advertisers WHERE id = last_insert_rowid()")
    return dict(await row.fetchone())


@app.put("/api/advertisers/{adv_id}")
async def update_advertiser(adv_id: int, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "UPDATE advertisers SET name=?, username=?, link=?, notes=? WHERE id=? AND user_id=?",
        (data["name"], data.get("username", ""), data.get("link", ""), data.get("notes", ""), adv_id, telegram_id),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM advertisers WHERE id = ?", (adv_id,))
    return dict(await row.fetchone())


@app.delete("/api/advertisers/{adv_id}")
async def delete_advertiser(adv_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    await db.execute("DELETE FROM promos WHERE advertiser_id = ? AND user_id = ?", (adv_id, telegram_id))
    await db.execute("DELETE FROM notes WHERE advertiser_id = ?", (adv_id,))
    await db.execute("DELETE FROM advertisers WHERE id = ? AND user_id = ?", (adv_id, telegram_id))
    await db.commit()
    return {"ok": True}


# ── Promos ──

@app.patch("/api/promos/bulk-status")
async def bulk_status(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    ids = data.get("ids", [])
    status = data.get("status", "")
    if not ids or status not in ("not_ready", "in_progress", "done"):
        raise HTTPException(400, "Invalid ids or status")
    telegram_id = user.get("id", 0)
    placeholders = ",".join("?" for _ in ids)
    await db.execute(
        f"UPDATE promos SET status = ? WHERE id IN ({placeholders}) AND user_id = ?",
        [status] + ids + [telegram_id],
    )
    await db.commit()
    return {"ok": True, "updated": len(ids)}


@app.get("/api/promos/export")
async def export_promos(user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    rows = await db.execute(
        "SELECT * FROM promos WHERE user_id = ? ORDER BY deadline ASC NULLS LAST, created_at DESC",
        (telegram_id,),
    )
    promos_list = [dict(r) for r in await rows.fetchall()]
    status_map = {"not_ready": "Не готово", "in_progress": "В процессе", "done": "Готово"}
    lines = [f"Промо ({len(promos_list)} шт.)", "=" * 30]
    for p in promos_list:
        lines.append(f"\n{p['name']}")
        if p.get("advertiser_name"):
            lines.append(f"  Рекламодатель: {p['advertiser_name']}")
        lines.append(f"  Статус: {status_map.get(p['status'], p['status'])}")
        if p.get("deadline"):
            lines.append(f"  Дедлайн: {p['deadline']}")
        if p.get("price_usdt"):
            lines.append(f"  Цена: ${p['price_usdt']} USDT")
        if p.get("link"):
            lines.append(f"  Ссылка: {p['link']}")
        if p.get("tags"):
            lines.append(f"  Тэги: {p['tags']}")
    return PlainTextResponse("\n".join(lines))


@app.get("/api/promos/archived")
async def list_archived(user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    rows = await db.execute("SELECT * FROM promos WHERE user_id = ? AND archived = 1 ORDER BY created_at DESC", (telegram_id,))
    return [dict(r) for r in await rows.fetchall()]


@app.get("/api/promos")
async def list_promos(
    category: str | None = None,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    telegram_id = user.get("id", 0)
    base = "SELECT * FROM promos WHERE user_id = ? AND archived = 0"
    params = [telegram_id]
    if category:
        base += " AND category = ?"
        params.append(category)
    base += " ORDER BY created_at DESC"
    rows = await db.execute(base, params)
    return [dict(r) for r in await rows.fetchall()]


@app.post("/api/promos")
async def create_promo(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "INSERT INTO promos (user_id, name, link, price_usdt, status, deadline, notes, category, advertiser_name, advertiser_id, tags, priority, payment_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
        (
            telegram_id,
            data["name"],
            data.get("link", ""),
            data.get("price_usdt"),
            data.get("status", "not_ready"),
            data.get("deadline"),
            data.get("notes", ""),
            data.get("category", "yokoso"),
            data.get("advertiser_name", ""),
            data.get("tags", ""),
            data.get("priority", "medium"),
            data.get("payment_status", "pending"),
        ),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM promos WHERE id = last_insert_rowid()")
    return dict(await row.fetchone())


@app.put("/api/promos/{promo_id}")
async def update_promo(promo_id: int, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "UPDATE promos SET name=?, link=?, price_usdt=?, status=?, deadline=?, notes=?, category=?, advertiser_name=?, tags=?, priority=?, payment_status=? WHERE id=? AND user_id=?",
        (
            data["name"],
            data.get("link", ""),
            data.get("price_usdt"),
            data.get("status", "not_ready"),
            data.get("deadline"),
            data.get("notes", ""),
            data.get("category", "yokoso"),
            data.get("advertiser_name", ""),
            data.get("tags", ""),
            data.get("priority", "medium"),
            data.get("payment_status", "pending"),
            promo_id,
            telegram_id,
        ),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM promos WHERE id = ?", (promo_id,))
    return dict(await row.fetchone())


@app.delete("/api/promos/{promo_id}")
async def delete_promo(promo_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    await db.execute("DELETE FROM notes WHERE promo_id = ?", (promo_id,))
    await db.execute("DELETE FROM reminders WHERE promo_id = ?", (promo_id,))
    await db.execute("DELETE FROM promos WHERE id = ? AND user_id = ?", (promo_id, telegram_id))
    await db.commit()
    return {"ok": True}


@app.patch("/api/promos/{promo_id}/status")
async def update_promo_status(promo_id: int, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    old_row = await db.execute("SELECT status FROM promos WHERE id = ? AND user_id = ?", (promo_id, telegram_id))
    old = await old_row.fetchone()
    old_status = dict(old)["status"] if old else None
    new_status = data["status"]
    await db.execute(
        "UPDATE promos SET status = ? WHERE id = ? AND user_id = ?",
        (new_status, promo_id, telegram_id),
    )
    await db.execute(
        "INSERT INTO promo_history (promo_id, user_id, old_status, new_status) VALUES (?, ?, ?, ?)",
        (promo_id, telegram_id, old_status, new_status),
    )
    await db.commit()
    return {"ok": True}


@app.patch("/api/promos/{promo_id}/archive")
async def archive_promo(promo_id: int, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    archived = 1 if data.get("archived", True) else 0
    await db.execute("UPDATE promos SET archived = ? WHERE id = ? AND user_id = ?", (archived, promo_id, telegram_id))
    await db.commit()
    return {"ok": True}


@app.get("/api/promos/{promo_id}/history")
async def promo_history(promo_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    rows = await db.execute("SELECT * FROM promo_history WHERE promo_id = ? ORDER BY created_at DESC", (promo_id,))
    return [dict(r) for r in await rows.fetchall()]


@app.get("/api/promos/{promo_id}/comments")
async def list_comments(promo_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    rows = await db.execute("SELECT * FROM promo_comments WHERE promo_id = ? ORDER BY created_at ASC", (promo_id,))
    return [dict(r) for r in await rows.fetchall()]


@app.post("/api/promos/{promo_id}/comments")
async def add_comment(promo_id: int, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "INSERT INTO promo_comments (promo_id, user_id, content) VALUES (?, ?, ?)",
        (promo_id, telegram_id, data["content"]),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM promo_comments WHERE id = last_insert_rowid()")
    return dict(await row.fetchone())


@app.delete("/api/comments/{comment_id}")
async def delete_comment(comment_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    await db.execute("DELETE FROM promo_comments WHERE id = ? AND user_id = ?", (comment_id, telegram_id))
    await db.commit()
    return {"ok": True}


@app.get("/api/stats")
async def get_stats(user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    total = await db.execute("SELECT COUNT(*) as c FROM promos WHERE user_id = ? AND archived = 0", (telegram_id,))
    total_count = dict(await total.fetchone())["c"]
    done = await db.execute("SELECT COUNT(*) as c FROM promos WHERE user_id = ? AND archived = 0 AND status = 'done'", (telegram_id,))
    done_count = dict(await done.fetchone())["c"]
    week = await db.execute("SELECT COUNT(*) as c FROM promos WHERE user_id = ? AND status = 'done' AND created_at >= datetime('now', '-7 days')", (telegram_id,))
    week_count = dict(await week.fetchone())["c"]
    month = await db.execute("SELECT COUNT(*) as c FROM promos WHERE user_id = ? AND status = 'done' AND created_at >= datetime('now', '-30 days')", (telegram_id,))
    month_count = dict(await month.fetchone())["c"]
    archived = await db.execute("SELECT COUNT(*) as c FROM promos WHERE user_id = ? AND archived = 1", (telegram_id,))
    archived_count = dict(await archived.fetchone())["c"]
    high = await db.execute("SELECT COUNT(*) as c FROM promos WHERE user_id = ? AND archived = 0 AND priority = 'high'", (telegram_id,))
    high_count = dict(await high.fetchone())["c"]
    # Financial stats
    income = await db.execute("SELECT COALESCE(SUM(price_usdt), 0) as s FROM promos WHERE user_id = ? AND archived = 0 AND payment_status = 'paid'", (telegram_id,))
    income_total = dict(await income.fetchone())["s"]
    income_month = await db.execute("SELECT COALESCE(SUM(price_usdt), 0) as s FROM promos WHERE user_id = ? AND payment_status = 'paid' AND created_at >= datetime('now', '-30 days')", (telegram_id,))
    income_month_val = dict(await income_month.fetchone())["s"]
    pending_pay = await db.execute("SELECT COALESCE(SUM(price_usdt), 0) as s FROM promos WHERE user_id = ? AND archived = 0 AND payment_status = 'pending' AND status = 'done'", (telegram_id,))
    pending_pay_val = dict(await pending_pay.fetchone())["s"]
    expenses_month = await db.execute("SELECT COALESCE(SUM(amount), 0) as s FROM expenses WHERE user_id = ? AND created_at >= datetime('now', '-30 days')", (telegram_id,))
    expenses_month_val = dict(await expenses_month.fetchone())["s"]
    return {
        "total": total_count, "done": done_count, "week_done": week_count,
        "month_done": month_count, "archived": archived_count, "high_priority": high_count,
        "income_total": income_total, "income_month": income_month_val,
        "pending_payment": pending_pay_val, "expenses_month": expenses_month_val,
        "net_profit_month": round(income_month_val - expenses_month_val, 2),
    }


# ── Notes ──

@app.get("/api/notes")
async def list_notes(
    promo_id: int | None = None,
    advertiser_id: int | None = None,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    telegram_id = user.get("id", 0)
    if promo_id:
        rows = await db.execute(
            "SELECT * FROM notes WHERE user_id = ? AND promo_id = ? ORDER BY created_at DESC",
            (telegram_id, promo_id),
        )
    elif advertiser_id:
        rows = await db.execute(
            "SELECT * FROM notes WHERE user_id = ? AND advertiser_id = ? ORDER BY created_at DESC",
            (telegram_id, advertiser_id),
        )
    else:
        rows = await db.execute(
            "SELECT * FROM notes WHERE user_id = ? ORDER BY created_at DESC",
            (telegram_id,),
        )
    return [dict(r) for r in await rows.fetchall()]


@app.post("/api/notes")
async def create_note(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "INSERT INTO notes (user_id, promo_id, advertiser_id, content) VALUES (?, ?, ?, ?)",
        (telegram_id, data.get("promo_id"), data.get("advertiser_id"), data["content"]),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM notes WHERE id = last_insert_rowid()")
    return dict(await row.fetchone())


@app.put("/api/notes/{note_id}")
async def update_note(note_id: int, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    if "created_at" in data:
        await db.execute(
            "UPDATE notes SET content = ?, created_at = ? WHERE id = ? AND user_id = ?",
            (data["content"], data["created_at"], note_id, telegram_id),
        )
    else:
        await db.execute(
            "UPDATE notes SET content = ? WHERE id = ? AND user_id = ?",
            (data["content"], note_id, telegram_id),
        )
    await db.commit()
    row = await db.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
    return dict(await row.fetchone())


@app.delete("/api/notes/{note_id}")
async def delete_note(note_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    await db.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, telegram_id))
    await db.commit()
    return {"ok": True}


# ── Reminders ──

@app.get("/api/reminders")
async def list_reminders(user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    rows = await db.execute(
        "SELECT r.*, p.name as promo_name FROM reminders r LEFT JOIN promos p ON r.promo_id = p.id WHERE r.user_id = ? AND r.sent = 0 ORDER BY r.remind_at ASC",
        (telegram_id,),
    )
    return [dict(r) for r in await rows.fetchall()]


@app.post("/api/reminders")
async def create_reminder(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "INSERT INTO reminders (user_id, promo_id, remind_at, message) VALUES (?, ?, ?, ?)",
        (telegram_id, data.get("promo_id"), data["remind_at"], data.get("message", "")),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM reminders WHERE id = last_insert_rowid()")
    return dict(await row.fetchone())


@app.put("/api/reminders/{reminder_id}")
async def update_reminder(reminder_id: int, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "UPDATE reminders SET remind_at=?, message=?, promo_id=? WHERE id=? AND user_id=?",
        (data["remind_at"], data.get("message", ""), data.get("promo_id"), reminder_id, telegram_id),
    )
    await db.commit()
    return {"ok": True}


@app.delete("/api/reminders/{reminder_id}")
async def delete_reminder(reminder_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    await db.execute("DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, telegram_id))
    await db.commit()
    return {"ok": True}


# ── Price Converter (Multi-currency) ──

RATES_CACHE = {"rates": {}, "timestamp": 0}

CURRENCY_IDS = {
    "USDT": "tether",
    "BTC": "bitcoin",
    "ETH": "ethereum",
}
FIAT_CURRENCIES = ["usd", "eur", "rub", "kzt", "uzs", "try", "gbp", "cny", "jpy", "aed"]


async def get_all_rates() -> dict:
    now = time.time()
    if RATES_CACHE["rates"] and now - RATES_CACHE["timestamp"] < 300:
        return RATES_CACHE["rates"]
    try:
        crypto_ids = ",".join(CURRENCY_IDS.values())
        fiat_list = ",".join(FIAT_CURRENCIES)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={crypto_ids}&vs_currencies={fiat_list}"
            )
            data = resp.json()
            rates = {}
            for symbol, cg_id in CURRENCY_IDS.items():
                if cg_id in data:
                    for fiat in FIAT_CURRENCIES:
                        if fiat in data[cg_id]:
                            rates[f"{symbol}_{fiat.upper()}"] = data[cg_id][fiat]
            RATES_CACHE["rates"] = rates
            RATES_CACHE["timestamp"] = now
            return rates
    except Exception:
        return RATES_CACHE.get("rates") or {"USDT_RUB": 92.0, "USDT_USD": 1.0}


async def get_usdt_rub_rate() -> float:
    rates = await get_all_rates()
    return rates.get("USDT_RUB", 92.0)


@app.get("/api/exchange-rate")
async def exchange_rate():
    rate = await get_usdt_rub_rate()
    return {"usdt_rub": rate}


@app.get("/api/rates")
async def all_rates():
    rates = await get_all_rates()
    return rates


@app.get("/api/convert")
async def convert_price(amount: float, from_cur: str = "USDT", to_cur: str = "RUB"):
    rates = await get_all_rates()
    from_cur = from_cur.upper()
    to_cur = to_cur.upper()
    key = f"{from_cur}_{to_cur}"
    reverse_key = f"{to_cur}_{from_cur}"
    if key in rates:
        result = amount * rates[key]
    elif reverse_key in rates:
        result = amount / rates[reverse_key]
    else:
        from_usd = rates.get(f"{from_cur}_USD", 1.0)
        to_usd = rates.get(f"{to_cur}_USD")
        if to_usd:
            result = amount * from_usd / to_usd
        else:
            return {"error": "Unsupported pair", "result": 0}
    return {"result": round(result, 4), "from": from_cur, "to": to_cur}


# ── Templates ──

@app.get("/api/templates")
async def list_templates(user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    rows = await db.execute(
        "SELECT * FROM promo_templates WHERE user_id = ? ORDER BY created_at DESC",
        (telegram_id,),
    )
    return [dict(r) for r in await rows.fetchall()]


@app.post("/api/templates")
async def create_template(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "INSERT INTO promo_templates (user_id, name, link, price_usdt, advertiser_name, tags, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (telegram_id, data["name"], data.get("link", ""), data.get("price_usdt"), data.get("advertiser_name", ""), data.get("tags", ""), data.get("notes", "")),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM promo_templates WHERE id = last_insert_rowid()")
    return dict(await row.fetchone())


@app.delete("/api/templates/{template_id}")
async def delete_template(template_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    await db.execute("DELETE FROM promo_templates WHERE id = ? AND user_id = ?", (template_id, telegram_id))
    await db.commit()
    return {"ok": True}


# ── Payment tracking ──

@app.patch("/api/promos/{promo_id}/payment")
async def update_payment(promo_id: int, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    payment_status = data.get("payment_status", "pending")
    paid_amount = data.get("paid_amount", 0)
    await db.execute(
        "UPDATE promos SET payment_status=?, paid_amount=? WHERE id=? AND user_id=?",
        (payment_status, paid_amount, promo_id, telegram_id),
    )
    await db.commit()
    return {"ok": True}


# ── Expenses ──

@app.get("/api/expenses")
async def list_expenses(user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    rows = await db.execute("SELECT * FROM expenses WHERE user_id = ? ORDER BY created_at DESC", (telegram_id,))
    return [dict(r) for r in await rows.fetchall()]


@app.post("/api/expenses")
async def create_expense(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "INSERT INTO expenses (user_id, amount, currency, description, category) VALUES (?, ?, ?, ?, ?)",
        (telegram_id, data["amount"], data.get("currency", "USDT"), data.get("description", ""), data.get("category", "other")),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM expenses WHERE id = last_insert_rowid()")
    return dict(await row.fetchone())


@app.delete("/api/expenses/{expense_id}")
async def delete_expense(expense_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    await db.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, telegram_id))
    await db.commit()
    return {"ok": True}


# ── Invoice ──

@app.get("/api/promos/{promo_id}/invoice")
async def generate_invoice(promo_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    row = await db.execute("SELECT * FROM promos WHERE id = ? AND user_id = ?", (promo_id, telegram_id))
    promo = await row.fetchone()
    if not promo:
        raise HTTPException(404, "Promo not found")
    p = dict(promo)
    rate = await get_usdt_rub_rate()
    now = datetime.now().strftime("%d.%m.%Y")
    rub_amount = round((p.get("price_usdt") or 0) * rate, 2)
    lines = [
        "═══════════════════════════",
        "         ИНВОЙС / СЧЁТ",
        "═══════════════════════════",
        f"Дата: {now}",
        f"Номер: INV-{p['id']:04d}",
        "",
        f"Кампания: {p['name']}",
    ]
    if p.get("advertiser_name"):
        lines.append(f"Рекламодатель: {p['advertiser_name']}")
    if p.get("link"):
        lines.append(f"Ссылка: {p['link']}")
    lines += [
        "",
        "───────────────────────────",
        f"Сумма: ${p.get('price_usdt', 0)} USDT",
        f"       ≈ {rub_amount} RUB (курс {rate:.2f})",
        "───────────────────────────",
        "",
    ]
    payment_labels = {"pending": "Ожидает оплаты", "partial": "Частично оплачен", "paid": "Оплачен"}
    lines.append(f"Статус: {payment_labels.get(p.get('payment_status', 'pending'), 'Ожидает')}")
    if p.get("paid_amount") and p.get("paid_amount") > 0:
        lines.append(f"Оплачено: ${p['paid_amount']} USDT")
        remaining = (p.get("price_usdt") or 0) - p["paid_amount"]
        if remaining > 0:
            lines.append(f"Остаток: ${remaining:.2f} USDT")
    lines += ["", "═══════════════════════════"]
    return PlainTextResponse("\n".join(lines))


# ── TikTok info ──

@app.post("/api/tiktok-sound")
async def tiktok_sound_info(request: Request):
    data = await request.json()
    url = data.get("url", "")
    if not url or "tiktok" not in url:
        raise HTTPException(400, "Invalid TikTok URL")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            # Follow redirects for short URLs (vm.tiktok.com)
            resp = await client.get(url, headers=headers)
            final_url = str(resp.url)
            html = resp.text
            name = ""
            author = ""

            # Method 1: Parse URL slug — most reliable
            # Pattern: /music/Track-Name-Artist-Name-1234567890
            slug_match = re.match(r'.*/music/(.+?)(-\d{10,})(?:\?.*)?$', final_url)
            if slug_match:
                raw = slug_match.group(1)
                if raw.lower() != "original-sound":
                    slug_name = raw.replace("-", " ")
                    name = slug_name

            # Method 2: Try JSON data in page
            if not name or name == "original sound":
                music_match = re.search(r'"musicName"\s*:\s*"([^"]+)"', html)
                if music_match and "original" not in music_match.group(1).lower():
                    name = music_match.group(1)
            author_match = re.search(r'"authorName"\s*:\s*"([^"]+)"', html)
            if author_match:
                author = author_match.group(1)

            # Method 3: Try canonical URL in page
            if not name or name == "original sound":
                canon = re.search(r'"canonical"\s*:\s*"[^"]*?/music/(.+?)(-\d{10,})"', html)
                if canon:
                    raw2 = canon.group(1).replace("\\u002F", "/").replace("-", " ")
                    if raw2.lower() != "original sound":
                        name = raw2

            # Method 4: og:title
            if not name or name == "original sound":
                og_match = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html, re.IGNORECASE)
                if og_match:
                    og = og_match.group(1).strip()
                    if "tiktok" not in og.lower() and "make your day" not in og.lower():
                        name = og

            # Clean up generic/placeholder names
            if name and ("make your day" in name.lower() or name.lower().startswith("tiktok")):
                name = ""

            return {"name": name, "author": author, "url": final_url}
    except Exception as e:
        return {"name": "", "author": "", "error": str(e)}


@app.post("/api/tiktok-user")
async def tiktok_user_search(request: Request):
    data = await request.json()
    query = data.get("username", "").strip().lstrip("@")
    if not query:
        raise HTTPException(400, "Username required")
    results = []
    headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            # Direct profile lookup
            resp = await client.get(f"https://www.tiktok.com/@{query}", headers=headers)
            html = resp.text
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else ""
            display_name = ""
            if title and "TikTok" not in title[:10]:
                parts = title.split("(")
                display_name = parts[0].strip()
            avatar = ""
            av_match = re.search(r'"avatarThumb":"([^"]+)"', html)
            if not av_match:
                av_match = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', html)
            if av_match:
                avatar = av_match.group(1).replace("\\u002F", "/")
            desc_match = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]+)"', html, re.IGNORECASE)
            bio = desc_match.group(1).strip() if desc_match else ""
            followers_match = re.search(r'"followerCount":(\d+)', html)
            followers = ""
            if followers_match:
                fc = int(followers_match.group(1))
                followers = f"{fc // 1000}K" if fc >= 1000 else str(fc)
            if display_name or "404" not in title:
                results.append({
                    "username": query,
                    "display_name": display_name or query,
                    "avatar": avatar,
                    "bio": bio[:100],
                    "followers": followers,
                })
            # Also try common variations
            for suffix in ["_official", "official", ".music", "_music"]:
                variant = query + suffix
                try:
                    resp2 = await client.get(f"https://www.tiktok.com/@{variant}", headers=headers)
                    h2 = resp2.text
                    t2 = re.search(r'<title[^>]*>([^<]+)</title>', h2, re.IGNORECASE)
                    t2_text = t2.group(1).strip() if t2 else ""
                    if t2_text and "404" not in t2_text and "TikTok" not in t2_text[:10]:
                        dn2 = t2_text.split("(")[0].strip()
                        av2 = re.search(r'"avatarThumb":"([^"]+)"', h2)
                        if not av2:
                            av2 = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', h2)
                        fc2 = re.search(r'"followerCount":(\d+)', h2)
                        fc2_str = ""
                        if fc2:
                            c = int(fc2.group(1))
                            fc2_str = f"{c // 1000}K" if c >= 1000 else str(c)
                        results.append({
                            "username": variant,
                            "display_name": dn2 or variant,
                            "avatar": av2.group(1).replace("\\u002F", "/") if av2 else "",
                            "bio": "",
                            "followers": fc2_str,
                        })
                except Exception:
                    pass
    except Exception as e:
        if not results:
            results.append({"username": query, "display_name": query, "avatar": "", "bio": "", "followers": "", "error": str(e)})
    return results


# ── Admin Panel ──

@app.get("/api/admin/users")
async def admin_list_users(user=Depends(require_admin), db=Depends(get_db)):
    rows = await db.execute(
        "SELECT u.*, "
        "(SELECT COUNT(*) FROM advertisers WHERE user_id = u.telegram_id) as advertisers_count, "
        "(SELECT COUNT(*) FROM promos WHERE user_id = u.telegram_id) as promos_count, "
        "(SELECT COUNT(*) FROM promos WHERE user_id = u.telegram_id AND status = 'done') as done_count "
        "FROM users u ORDER BY u.created_at DESC"
    )
    return [dict(r) for r in await rows.fetchall()]


@app.get("/api/admin/users/{telegram_id}/advertisers")
async def admin_user_advertisers(telegram_id: int, user=Depends(require_admin), db=Depends(get_db)):
    rows = await db.execute(
        "SELECT * FROM advertisers WHERE user_id = ? ORDER BY created_at DESC",
        (telegram_id,),
    )
    return [dict(r) for r in await rows.fetchall()]


@app.get("/api/admin/users/{telegram_id}/promos")
async def admin_user_promos(telegram_id: int, user=Depends(require_admin), db=Depends(get_db)):
    rows = await db.execute(
        "SELECT p.*, a.name as advertiser_name FROM promos p "
        "LEFT JOIN advertisers a ON p.advertiser_id = a.id "
        "WHERE p.user_id = ? ORDER BY p.created_at DESC",
        (telegram_id,),
    )
    return [dict(r) for r in await rows.fetchall()]


@app.delete("/api/admin/users/{telegram_id}")
async def admin_delete_user(telegram_id: int, user=Depends(require_admin), db=Depends(get_db)):
    await db.execute("DELETE FROM reminders WHERE user_id = ?", (telegram_id,))
    await db.execute("DELETE FROM notes WHERE user_id = ?", (telegram_id,))
    await db.execute("DELETE FROM promos WHERE user_id = ?", (telegram_id,))
    await db.execute("DELETE FROM advertisers WHERE user_id = ?", (telegram_id,))
    await db.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
    await db.commit()
    return {"ok": True}


@app.get("/api/admin/stats")
async def admin_stats(user=Depends(require_admin), db=Depends(get_db)):
    users = await (await db.execute("SELECT COUNT(*) as cnt FROM users")).fetchone()
    advertisers = await (await db.execute("SELECT COUNT(*) as cnt FROM advertisers")).fetchone()
    promos = await (await db.execute("SELECT COUNT(*) as cnt FROM promos")).fetchone()
    done = await (await db.execute("SELECT COUNT(*) as cnt FROM promos WHERE status = 'done'")).fetchone()
    in_progress = await (await db.execute("SELECT COUNT(*) as cnt FROM promos WHERE status = 'in_progress'")).fetchone()
    notes = await (await db.execute("SELECT COUNT(*) as cnt FROM notes")).fetchone()
    reminders = await (await db.execute("SELECT COUNT(*) as cnt FROM reminders")).fetchone()
    return {
        "total_users": users["cnt"],
        "total_advertisers": advertisers["cnt"],
        "total_promos": promos["cnt"],
        "done_promos": done["cnt"],
        "in_progress_promos": in_progress["cnt"],
        "total_notes": notes["cnt"],
        "total_reminders": reminders["cnt"],
    }
