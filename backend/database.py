import aiosqlite
import os

DB_PATH = os.getenv("DB_PATH", "data.db")


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language TEXT DEFAULT 'ru',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS advertisers (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                username TEXT,
                link TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS promos (
                id INTEGER PRIMARY KEY,
                advertiser_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                link TEXT,
                price_usdt REAL,
                status TEXT DEFAULT 'not_ready',
                deadline TIMESTAMP,
                notes TEXT,
                category TEXT DEFAULT 'yokoso',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (advertiser_id) REFERENCES advertisers(id),
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                promo_id INTEGER,
                advertiser_id INTEGER,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id),
                FOREIGN KEY (promo_id) REFERENCES promos(id),
                FOREIGN KEY (advertiser_id) REFERENCES advertisers(id)
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                promo_id INTEGER,
                remind_at TIMESTAMP NOT NULL,
                message TEXT,
                sent INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id),
                FOREIGN KEY (promo_id) REFERENCES promos(id)
            );
        """)
        # Migration: add category column if missing
        try:
            await db.execute("ALTER TABLE promos ADD COLUMN category TEXT DEFAULT 'yokoso'")
        except Exception:
            pass
        # Migration: add advertiser_name column if missing
        try:
            await db.execute("ALTER TABLE promos ADD COLUMN advertiser_name TEXT DEFAULT ''")
        except Exception:
            pass
        # Backfill advertiser_name from advertisers table
        try:
            await db.execute("UPDATE promos SET advertiser_name = (SELECT a.name FROM advertisers a WHERE a.id = promos.advertiser_id) WHERE advertiser_name = '' AND advertiser_id > 0")
        except Exception:
            pass
        # Migration: add tags column to promos
        try:
            await db.execute("ALTER TABLE promos ADD COLUMN tags TEXT DEFAULT ''")
        except Exception:
            pass
        # Templates table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_templates (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                link TEXT DEFAULT '',
                price_usdt REAL,
                advertiser_name TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )
        """)
        # Migration: add priority column to promos
        try:
            await db.execute("ALTER TABLE promos ADD COLUMN priority TEXT DEFAULT 'medium'")
        except Exception:
            pass
        # Migration: add archived column to promos
        try:
            await db.execute("ALTER TABLE promos ADD COLUMN archived INTEGER DEFAULT 0")
        except Exception:
            pass
        # Status change history
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_history (
                id INTEGER PRIMARY KEY,
                promo_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                old_status TEXT,
                new_status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (promo_id) REFERENCES promos(id),
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )
        """)
        # Comments on promos
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_comments (
                id INTEGER PRIMARY KEY,
                promo_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (promo_id) REFERENCES promos(id),
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )
        """)
        # Migration: add payment_status to promos
        try:
            await db.execute("ALTER TABLE promos ADD COLUMN payment_status TEXT DEFAULT 'pending'")
        except Exception:
            pass
        # Migration: add paid_amount to promos
        try:
            await db.execute("ALTER TABLE promos ADD COLUMN paid_amount REAL DEFAULT 0")
        except Exception:
            pass
        # Expenses table for net profit tracking
        await db.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'USDT',
                description TEXT,
                category TEXT DEFAULT 'other',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )
        """)
        await db.commit()
