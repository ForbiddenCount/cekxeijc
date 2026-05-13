import hashlib
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, unquote

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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

    return {
        **dict(profile),
        "advertisers_count": adv["cnt"],
        "promos_count": promo["cnt"],
        "done_count": done["cnt"],
    }


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

@app.get("/api/promos")
async def list_promos(
    advertiser_id: int | None = None,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    telegram_id = user.get("id", 0)
    if advertiser_id:
        rows = await db.execute(
            "SELECT p.*, a.name as advertiser_name FROM promos p LEFT JOIN advertisers a ON p.advertiser_id = a.id WHERE p.user_id = ? AND p.advertiser_id = ? ORDER BY p.deadline ASC NULLS LAST, p.created_at DESC",
            (telegram_id, advertiser_id),
        )
    else:
        rows = await db.execute(
            "SELECT p.*, a.name as advertiser_name FROM promos p LEFT JOIN advertisers a ON p.advertiser_id = a.id WHERE p.user_id = ? ORDER BY p.deadline ASC NULLS LAST, p.created_at DESC",
            (telegram_id,),
        )
    return [dict(r) for r in await rows.fetchall()]


@app.post("/api/promos")
async def create_promo(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    data = await request.json()
    telegram_id = user.get("id", 0)
    await db.execute(
        "INSERT INTO promos (advertiser_id, user_id, name, link, price_usdt, status, deadline, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data["advertiser_id"],
            telegram_id,
            data["name"],
            data.get("link", ""),
            data.get("price_usdt"),
            data.get("status", "not_ready"),
            data.get("deadline"),
            data.get("notes", ""),
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
        "UPDATE promos SET name=?, link=?, price_usdt=?, status=?, deadline=?, notes=?, advertiser_id=? WHERE id=? AND user_id=?",
        (
            data["name"],
            data.get("link", ""),
            data.get("price_usdt"),
            data.get("status", "not_ready"),
            data.get("deadline"),
            data.get("notes", ""),
            data.get("advertiser_id"),
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
    await db.execute(
        "UPDATE promos SET status = ? WHERE id = ? AND user_id = ?",
        (data["status"], promo_id, telegram_id),
    )
    await db.commit()
    return {"ok": True}


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


@app.delete("/api/reminders/{reminder_id}")
async def delete_reminder(reminder_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    telegram_id = user.get("id", 0)
    await db.execute("DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, telegram_id))
    await db.commit()
    return {"ok": True}


# ── Price Converter ──

EXCHANGE_RATE_CACHE = {"rate": None, "timestamp": 0}


async def get_usdt_rub_rate() -> float:
    now = time.time()
    if EXCHANGE_RATE_CACHE["rate"] and now - EXCHANGE_RATE_CACHE["timestamp"] < 300:
        return EXCHANGE_RATE_CACHE["rate"]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
            )
            data = resp.json()
            rate = data["tether"]["rub"]
            EXCHANGE_RATE_CACHE["rate"] = rate
            EXCHANGE_RATE_CACHE["timestamp"] = now
            return rate
    except Exception:
        return EXCHANGE_RATE_CACHE.get("rate") or 92.0


@app.get("/api/exchange-rate")
async def exchange_rate():
    rate = await get_usdt_rub_rate()
    return {"usdt_rub": rate}


@app.get("/api/convert")
async def convert_price(amount: float, direction: str = "usdt_to_rub"):
    rate = await get_usdt_rub_rate()
    if direction == "usdt_to_rub":
        return {"result": round(amount * rate, 2), "rate": rate, "currency": "RUB"}
    else:
        return {"result": round(amount / rate, 4), "rate": rate, "currency": "USDT"}


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
