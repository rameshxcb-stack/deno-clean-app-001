#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Advanced Telegram Cyber Cafe Service Bot
Single-file implementation: persistent SQLite orders, role-based admins, order tracking,
payment-proof review, optional local OCR (never automatic) checks, receipts, complaints,
ratings, loyalty, reports, reminders, audit logs, backups, Telegram-managed catalogue, inventory, expense ledger, P&L, CRM and SLA analytics.
Business records and settings are stored in Turso; no external application APIs except Telegram.

IMPORTANT DEPLOYMENT NOTE:
- This is a long-running polling bot. A scheduled GitHub Actions job is NOT a reliable
  always-on host. Use a supported always-on runtime for 24/7 availability, or use Actions
  only for scheduled maintenance/reporting.
- SQLite is suitable for a single process on persistent storage. Do not run multiple bot
  replicas against separate ephemeral files. For multi-replica production, use a shared DB.
- UPI QR generation does NOT verify payment. Screenshot OCR only extracts clues. An admin
  must verify the transaction with the bank/payment provider. Do not auto-approve from OCR.
- Add only services you are authorized to provide. Do not request/store customer OTPs,
  passwords, or unnecessary sensitive documents.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import io
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlsplit

import qrcode
from PIL import Image, ImageDraw, ImageFont
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    KeyboardButton, InputFile
)
from telegram.constants import ParseMode
from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

try:
    from dotenv import load_dotenv
    load_dotenv()  # Local environment file only; no network requests.
except ImportError:
    pass

try:
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    pytesseract = None
    OCR_AVAILABLE = False

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("cyber_cafe_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
UPI_ID = os.getenv("UPI_ID", "").strip()
PAYEE_NAME = os.getenv("PAYEE_NAME", "Digital Service Centre").strip()

# Universal payment adapter is opt-in. Never enable it until a real provider API is
# configured and tested against authoritative transaction records.
PAYMENT_AUTO_VERIFY_ENABLED = os.getenv("PAYMENT_AUTO_VERIFY_ENABLED", "0").strip() == "1"
PAYMENT_AUTO_VERIFY_TIMEOUT = min(20.0, max(2.0, float(os.getenv("PAYMENT_AUTO_VERIFY_TIMEOUT", "10"))))
PAYMENT_PROVIDER_ALLOWED_HOSTS = {
    h.strip().lower().rstrip(".") for h in os.getenv("PAYMENT_PROVIDER_ALLOWED_HOSTS", "").split(",")
    if h.strip()
}
DB_PATH = os.getenv("DB_PATH", "cyber_cafe.sqlite3")
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "backups"))
FONT_PATH = os.getenv("FONT_PATH", "NotoSansDevanagari-Bold.ttf")
ADMIN_USER_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",")
    if x.strip().isdigit()
}
OWNER_USER_IDS = {
    int(x.strip()) for x in os.getenv("OWNER_USER_IDS", "").split(",")
    if x.strip().isdigit()
}
# Backwards compatibility: ADMIN_CHAT_ID should be a Telegram USER ID for admin actions,
# not a group chat ID. ADMIN_CHAT_ID is included only as a legacy single-user fallback.
try:
    legacy_admin = int(os.getenv("ADMIN_CHAT_ID", "0"))
except ValueError:
    legacy_admin = 0
if legacy_admin:
    ADMIN_USER_IDS.add(legacy_admin)
    OWNER_USER_IDS.add(legacy_admin)

ADMIN_ALERT_CHAT_ID = int(os.getenv("ADMIN_ALERT_CHAT_ID", os.getenv("ADMIN_CHAT_ID", "0")) or "0")
URGENT_FEE = int(os.getenv("URGENT_FEE", "50"))
DEFAULT_SLA_HOURS = int(os.getenv("DEFAULT_SLA_HOURS", "24"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))
LOYALTY_POINTS_PER_100 = int(os.getenv("LOYALTY_POINTS_PER_100", "1"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing. Add it to environment variables / GitHub Secrets.")
if not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
    raise RuntimeError(
        "TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required. Configure them in GitHub Actions Secrets."
    )

# Replace or extend this catalogue with services you are legally authorized to provide.
# Avoid making unsupported government affiliation, guaranteed outcome, or refund claims.
CATEGORIES: dict[str, dict[str, Any]] = {
    "pan": {
        "name": "💳 पैन कार्ड सहायता",
        "desc": "पैन आवेदन/सुधार में सहायता",
        "services": [
            {"id": "pan_new", "name": "नया पैन आवेदन सहायता", "price": 200, "emoji": "💳",
             "docs": "आवश्यक दस्तावेज़ और प्रक्रिया की पुष्टि ऑपरेटर से करें।"},
            {"id": "pan_correction", "name": "पैन विवरण सुधार सहायता", "price": 250, "emoji": "✏️",
             "docs": "पैन कार्ड और संबंधित सही प्रमाण तैयार रखें।"},
            {"id": "pan_status", "name": "पैन आवेदन स्टेटस सहायता", "price": 50, "emoji": "🔎",
             "docs": "आवेदन संदर्भ संख्या स्वयं आधिकारिक पोर्टल पर दर्ज करें।"},
        ],
    },
    "aadhaar": {
        "name": "🆔 आधार संबंधी सामान्य सहायता",
        "desc": "आधार प्रक्रिया की जानकारी/सहायता",
        "services": [
            {"id": "aadhaar_info", "name": "आधार प्रक्रिया की जानकारी", "price": 50, "emoji": "🆔",
             "docs": "OTP/पासवर्ड कभी ऑपरेटर या बॉट को न भेजें।"},
            {"id": "aadhaar_docs", "name": "दस्तावेज़ चेकलिस्ट सहायता", "price": 50, "emoji": "📄",
             "docs": "सिर्फ आवश्यक दस्तावेज़ की चेकलिस्ट साझा करें।"},
        ],
    },
    "print": {
        "name": "🖨️ प्रिंट/स्कैन",
        "desc": "प्रिंट, स्कैन और फाइल तैयारी",
        "services": [
            {"id": "print_bw", "name": "ब्लैक एंड व्हाइट प्रिंट (प्रति पेज)", "price": 2, "emoji": "📄",
             "docs": "PDF/इमेज भेजें।"},
            {"id": "print_color", "name": "रंगीन प्रिंट (प्रति पेज)", "price": 10, "emoji": "🌈",
             "docs": "PDF/इमेज भेजें।"},
            {"id": "scan", "name": "स्कैनिंग (प्रति पेज)", "price": 5, "emoji": "📷",
             "docs": "कागज़ दुकान पर उपलब्ध कराएँ।"},
        ],
    },
    "other": {
        "name": "📝 अन्य डिजिटल सेवा",
        "desc": "अपनी आवश्यकता लिखें; ऑपरेटर पुष्टि करेगा",
        "services": [
            {"id": "custom_service", "name": "अन्य काम / कोटेशन", "price": 0, "emoji": "📝",
             "docs": "काम का विवरण भेजें। कीमत एडमिन की पुष्टि के बाद तय होगी।", "contact_admin": True},
        ],
    },
}

ORDER_STATUSES = {
    "REQUESTED": "📝 Request Received",
    "PAYMENT_PENDING": "💳 Payment Awaiting Verification",
    "PAYMENT_REVIEW": "🔎 Payment Proof Under Review",
    "PAID": "🟢 Payment Verified",
    "DOCS_PENDING": "📄 Documents Needed",
    "IN_PROGRESS": "🔵 Work In Progress",
    "WAITING_CUSTOMER": "⏳ Waiting for Customer",
    "COMPLETED": "✅ Completed",
    "REJECTED": "❌ Rejected",
    "REFUND_PENDING": "💰 Refund Pending",
    "REFUNDED": "↩️ Refunded",
    "CANCELLED": "🚫 Cancelled",
    "NEEDS_ADMIN": "⚠️ Needs Admin Attention",
}
VALID_TRANSITIONS = {
    "REQUESTED": {"PAYMENT_PENDING", "DOCS_PENDING", "IN_PROGRESS", "WAITING_CUSTOMER", "CANCELLED", "NEEDS_ADMIN"},
    "PAYMENT_PENDING": {"PAYMENT_REVIEW", "PAID", "REJECTED", "CANCELLED", "NEEDS_ADMIN"},
    "PAYMENT_REVIEW": {"PAID", "PAYMENT_PENDING", "REJECTED", "NEEDS_ADMIN"},
    "PAID": {"DOCS_PENDING", "IN_PROGRESS", "WAITING_CUSTOMER", "REFUND_PENDING", "CANCELLED", "NEEDS_ADMIN"},
    "DOCS_PENDING": {"IN_PROGRESS", "WAITING_CUSTOMER", "CANCELLED", "NEEDS_ADMIN"},
    "IN_PROGRESS": {"WAITING_CUSTOMER", "COMPLETED", "NEEDS_ADMIN", "REFUND_PENDING"},
    "WAITING_CUSTOMER": {"IN_PROGRESS", "DOCS_PENDING", "CANCELLED", "NEEDS_ADMIN"},
    "NEEDS_ADMIN": {"PAYMENT_REVIEW", "PAYMENT_PENDING", "PAID", "DOCS_PENDING", "IN_PROGRESS", "COMPLETED", "REFUND_PENDING", "CANCELLED"},
    "REFUND_PENDING": {"REFUNDED", "NEEDS_ADMIN"},
    "REJECTED": {"PAYMENT_REVIEW", "CANCELLED"},
    "COMPLETED": set(),
    "REFUNDED": set(),
    "CANCELLED": set(),
}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)

def short_id(prefix: str = "ORD") -> str:
    stamp = datetime.now().strftime("%y%m%d")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6].upper()}"

def money(value: Any) -> str:
    try:
        return f"₹{int(value):,}"
    except (ValueError, TypeError):
        return "₹0"

# ==========================================
# LIBSQL ROW_FACTORY FIX (Workaround)
# ==========================================
class DictCursorWrapper:
    """Adapt libsql-experimental cursor rows to sqlite3.Row-like named access."""
    def __init__(self, cursor):
        self._cursor = cursor
        self._description = None

    def execute(self, *args, **kwargs):
        self._cursor.execute(*args, **kwargs)
        self._description = self._cursor.description
        return self

    def _convert_row(self, row):
        if row is None:
            return None
        if self._description:
            columns = [col[0] for col in self._description]
            return dict(zip(columns, row))
        return row

    def fetchone(self):
        return self._convert_row(self._cursor.fetchone())

    def fetchall(self):
        rows = self._cursor.fetchall()
        if rows and self._description:
            columns = [col[0] for col in self._description]
            return [dict(zip(columns, row)) for row in rows]
        return rows

    def __iter__(self):
        for row in self._cursor:
            yield self._convert_row(row)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class DictConnectionWrapper:
    """Connection proxy that returns cursors with dictionary-style rows."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, *args, **kwargs):
        cursor = self._conn.cursor()
        return DictCursorWrapper(cursor).execute(*args, **kwargs)

    def cursor(self):
        return DictCursorWrapper(self._conn.cursor())

    def __getattr__(self, name):
        return getattr(self._conn, name)
# ==========================================


def _open_db_connection():
    """Open a Turso embedded replica. No silent fallback to a local-only database."""
    if not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
        raise RuntimeError(
            "TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required. Add both as GitHub Actions secrets."
        )
    try:
        import libsql_experimental as libsql
    except ImportError as exc:
        raise RuntimeError(
            "Missing libsql-experimental dependency; install requirements.txt."
        ) from exc

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = libsql.connect(
        DB_PATH,
        sync_url=TURSO_DATABASE_URL,
        auth_token=TURSO_AUTH_TOKEN,
    )
    conn.execute("PRAGMA foreign_keys=ON")
    # Pull remote changes before reading/writing. Embedded replica writes are local
    # until sync() succeeds, so every transaction syncs before the connection closes.
    conn.sync()
    # libsql-experimental may not implement sqlite3.Connection.row_factory.
    # Wrap the connection so SELECT rows support row["column_name"] access.
    return DictConnectionWrapper(conn)
@contextmanager
def db() -> Any:
    conn = _open_db_connection()
    try:
        yield conn
        conn.commit()
        # Persist changes to Turso after each transaction. If this fails, surface the
        # error instead of silently claiming the operation is safely stored remotely.
        conn.sync()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            log.exception("Database rollback failed")
        raise
    finally:
        conn.close()

def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        schema_sql = """
        CREATE TABLE IF NOT EXISTS customers(
            user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
            language TEXT DEFAULT 'hi', consent_at TEXT, created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL, loyalty_points INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_code TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL, service_id TEXT NOT NULL, service_name TEXT NOT NULL,
            category_id TEXT, amount INTEGER NOT NULL DEFAULT 0, urgent INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL, description TEXT DEFAULT '', due_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, assigned_admin INTEGER,
            customer_message_id INTEGER, last_notification TEXT,
            FOREIGN KEY(user_id) REFERENCES customers(user_id)
        );
        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, payment_ref TEXT UNIQUE NOT NULL,
            order_code TEXT NOT NULL, user_id INTEGER NOT NULL, expected_amount INTEGER NOT NULL,
            claimed_amount INTEGER, utr TEXT, proof_file_id TEXT, proof_kind TEXT,
            ocr_text TEXT, status TEXT NOT NULL DEFAULT 'PENDING',
            reviewed_by INTEGER, reviewed_at TEXT, created_at TEXT NOT NULL,
            payment_source TEXT, auto_verify_note TEXT, provider_ref TEXT,
            FOREIGN KEY(order_code) REFERENCES orders(order_code)
        );
        CREATE TABLE IF NOT EXISTS order_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_code TEXT NOT NULL, actor_id INTEGER,
            old_status TEXT, new_status TEXT, note TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY(order_code) REFERENCES orders(order_code)
        );
        CREATE TABLE IF NOT EXISTS documents(
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_code TEXT NOT NULL, user_id INTEGER NOT NULL,
            file_id TEXT NOT NULL, file_name TEXT, mime_type TEXT, file_size INTEGER,
            created_at TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(order_code) REFERENCES orders(order_code)
        );
        CREATE TABLE IF NOT EXISTS ratings(
            order_code TEXT PRIMARY KEY, user_id INTEGER NOT NULL, rating INTEGER NOT NULL,
            feedback TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS complaints(
            id INTEGER PRIMARY KEY AUTOINCREMENT, complaint_code TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL, order_code TEXT, text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS coupons(
            code TEXT PRIMARY KEY, discount_amount INTEGER NOT NULL, max_uses INTEGER NOT NULL DEFAULT 1,
            uses INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, expires_at TEXT
        );
        CREATE TABLE IF NOT EXISTS coupon_uses(
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, user_id INTEGER NOT NULL,
            order_code TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT NOT NULL,
            target TEXT, details TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notification_queue(
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, text TEXT NOT NULL,
            parse_mode TEXT, order_code TEXT, attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL, sent_at TEXT, last_error TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inventory_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            quantity REAL NOT NULL DEFAULT 0, unit TEXT NOT NULL DEFAULT 'pcs',
            low_stock_at REAL NOT NULL DEFAULT 5, cost_per_unit REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inventory_movements(
            id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL,
            movement_type TEXT NOT NULL, quantity REAL NOT NULL, note TEXT DEFAULT '',
            actor_id INTEGER, created_at TEXT NOT NULL,
            FOREIGN KEY(item_id) REFERENCES inventory_items(id)
        );
        CREATE TABLE IF NOT EXISTS expenses(
            id INTEGER PRIMARY KEY AUTOINCREMENT, amount INTEGER NOT NULL CHECK(amount > 0),
            category TEXT NOT NULL, note TEXT DEFAULT '', actor_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_expenses_created ON expenses(created_at);
        CREATE INDEX IF NOT EXISTS idx_inventory_movements_item ON inventory_movements(item_id, created_at);
        CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_code, created_at);
        CREATE INDEX IF NOT EXISTS idx_events_order ON order_events(order_code, created_at);
        CREATE INDEX IF NOT EXISTS idx_notif_due ON notification_queue(sent_at, next_attempt_at);
        """
        # Execute statements individually for compatibility with libSQL's SQLite API.
        for statement in schema_sql.split(";"):
            if statement.strip():
                c.execute(statement)
        # Safe, idempotent migrations for existing databases.
        payment_columns = {row["name"] for row in c.execute("PRAGMA table_info(payments)").fetchall()}
        for column, sql_type in (("payment_source", "TEXT"), ("auto_verify_note", "TEXT"), ("provider_ref", "TEXT")):
            if column not in payment_columns:
                c.execute(f"ALTER TABLE payments ADD COLUMN {column} {sql_type}")
        c.execute("""CREATE TABLE IF NOT EXISTS payment_providers(
            name TEXT PRIMARY KEY, config_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            priority INTEGER NOT NULL DEFAULT 100, updated_at TEXT NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_payment_provider_enabled ON payment_providers(enabled, priority)")
        c.execute("INSERT OR IGNORE INTO app_meta(key,value) VALUES('schema_version','2')")

def audit(actor_id: Optional[int], action: str, target: str = "", details: str = "") -> None:
    with db() as c:
        c.execute("INSERT INTO audit_logs(actor_id,action,target,details,created_at) VALUES(?,?,?,?,?)",
                  (actor_id, action, target, details[:1500], now_iso()))

def register_customer(user) -> None:
    if not user:
        return
    full_name = (user.full_name or user.first_name or "Customer")[:200]
    with db() as c:
        c.execute("""
          INSERT INTO customers(user_id,username,full_name,created_at,last_seen)
          VALUES(?,?,?,?,?)
          ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
          full_name=excluded.full_name,last_seen=excluded.last_seen
        """, (user.id, user.username, full_name, now_iso(), now_iso()))

def get_customer(user_id: int):
    with db() as c:
        return c.execute("SELECT * FROM customers WHERE user_id=?", (user_id,)).fetchone()

def get_service(service_id: str):
    for cat_id, cat in CATEGORIES.items():
        for svc in cat["services"]:
            if svc["id"] == service_id:
                return cat_id, svc
    return None, None

def all_services():
    for cat_id, cat in CATEGORIES.items():
        for svc in cat["services"]:
            yield cat_id, svc

def is_admin(user_id: Optional[int]) -> bool:
    # Owners inherit admin UI access even if they are listed only in OWNER_USER_IDS.
    return bool(user_id and (user_id in ADMIN_USER_IDS or user_id in OWNER_USER_IDS))

def is_owner(user_id: Optional[int]) -> bool:
    return bool(user_id and user_id in OWNER_USER_IDS)


def save_catalogue() -> None:
    """Persist the editable service catalogue in Turso app_meta; no extra file/table."""
    with db() as c:
        c.execute("INSERT INTO app_meta(key,value) VALUES('service_catalogue',?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (json.dumps(CATEGORIES, ensure_ascii=False),))


def load_runtime_settings() -> None:
    """Load the Telegram-managed catalogue/settings from Turso into the in-memory cache."""
    global CATEGORIES, URGENT_FEE, DEFAULT_SLA_HOURS, UPI_ID, PAYEE_NAME
    with db() as c:
        rows = c.execute("SELECT key,value FROM app_meta WHERE key IN "
                         "('service_catalogue','urgent_fee','default_sla_hours','upi_id','payee_name')").fetchall()
    settings = {row['key']: row['value'] for row in rows}
    if settings.get('service_catalogue'):
        try:
            loaded = json.loads(settings['service_catalogue'])
            if isinstance(loaded, dict) and loaded:
                CATEGORIES = loaded
        except (ValueError, TypeError):
            log.exception("Saved service catalogue is invalid; using built-in defaults")
            save_catalogue()
    else:
        save_catalogue()
    try:
        URGENT_FEE = max(0, int(settings.get('urgent_fee', URGENT_FEE)))
        DEFAULT_SLA_HOURS = max(1, int(settings.get('default_sla_hours', DEFAULT_SLA_HOURS)))
    except (TypeError, ValueError):
        pass
    UPI_ID = settings.get('upi_id', UPI_ID)
    PAYEE_NAME = settings.get('payee_name', PAYEE_NAME)


def set_runtime_setting(key: str, value: str) -> None:
    with db() as c:
        c.execute("INSERT INTO app_meta(key,value) VALUES(?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    load_runtime_settings()


def service_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:22]
    return slug or ("svc_" + uuid.uuid4().hex[:8])


def admin_manage_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("➕ नई सर्विस", callback_data="admin_add_service"),
         InlineKeyboardButton("🗂️ नई कैटेगरी", callback_data="admin_add_category")],
        [InlineKeyboardButton("💰 सर्विस फीस बदलें", callback_data="admin_fee_service"),
         InlineKeyboardButton("📄 दस्तावेज़ निर्देश बदलें", callback_data="admin_docs_text")],
        [InlineKeyboardButton("📎 सर्विस पर फ़ाइल जोड़ें", callback_data="admin_doc_file"),
         InlineKeyboardButton("✏️ सर्विस नाम बदलें", callback_data="admin_rename_service")],
        [InlineKeyboardButton("🟢 सर्विस चालू/बंद", callback_data="admin_toggle_service"),
         InlineKeyboardButton("🗑️ सर्विस फ़ाइलें हटाएँ", callback_data="admin_clear_files")],
        [InlineKeyboardButton("⚡ Urgent फीस", callback_data="admin_urgent_fee")],
        [InlineKeyboardButton("💳 UPI ID बदलें", callback_data="admin_set_upi"),
         InlineKeyboardButton("🏪 दुकान नाम बदलें", callback_data="admin_set_payee")],
        [InlineKeyboardButton("⏱️ समय सीमा बदलें", callback_data="admin_set_sla")],
        [InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")],
    ]
    return InlineKeyboardMarkup(rows)


def service_picker(prefix: str) -> InlineKeyboardMarkup:
    rows = []
    for cat_id, svc in all_services():
        rows.append([InlineKeyboardButton(f"{svc.get('emoji','🛠️')} {svc['name'][:35]} · {money(svc.get('price',0))}",
                                           callback_data=f"{prefix}:{svc['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Service Manager", callback_data="admin_manage_services")])
    return InlineKeyboardMarkup(rows)

async def safe_send(bot, chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except RetryAfter as e:
        await asyncio.sleep(min(int(e.retry_after) + 1, 30))
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception:
            log.exception("Telegram send retry failed chat=%s", chat_id)
    except (TimedOut, NetworkError, TelegramError):
        log.exception("Telegram send failed chat=%s", chat_id)
    return None

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    recipients = set(ADMIN_USER_IDS) | set(OWNER_USER_IDS)
    if ADMIN_ALERT_CHAT_ID:
        recipients.add(ADMIN_ALERT_CHAT_ID)
    for admin_id in recipients:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, parse_mode=ParseMode.HTML,
                                           reply_markup=reply_markup)
        except Exception:
            log.exception("Admin notification failed")

def ensure_font() -> None:
    """Use only a locally supplied font; never download anything from the internet."""
    if not os.path.exists(FONT_PATH):
        log.info("Local Hindi font not found; using Pillow default font (no download).")


def create_banner(title: str, subtitle: str = "Digital Services"):
    frames = []
    try:
        font_big = ImageFont.truetype(FONT_PATH, 46)
        font_small = ImageFont.truetype(FONT_PATH, 25)
    except Exception:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()
    for i, bg in enumerate([(10, 15, 30), (20, 25, 50), (30, 35, 70), (20, 25, 50)]):
        img = Image.new("RGB", (800, 320), color=bg)
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, 800, 8), fill=(255, 215, 0))
        draw.rectangle((0, 312, 800, 320), fill=(255, 215, 0))
        try:
            bbox = draw.textbbox((0, 0), title, font=font_big)
            draw.text(((800 - (bbox[2] - bbox[0])) / 2, 115), title, font=font_big, fill="white")
            bbox2 = draw.textbbox((0, 0), subtitle, font=font_small)
            draw.text(((800 - (bbox2[2] - bbox2[0])) / 2, 190), subtitle,
                      font=font_small, fill=(255, 215, 0))
        except Exception:
            draw.text((80, 120), title[:30], font=font_big, fill="white")
        frames.append(img)
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=500, loop=0)
    buf.seek(0)
    buf.name = "welcome.gif"
    return buf

def create_receipt(order, customer_name: str, payment_ref: str):
    # fpdf2 Unicode font support is best with a TTF font. Fall back to English-only if absent.
    try:
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        if os.path.exists(FONT_PATH):
            pdf.add_font("Noto", "", FONT_PATH)
            pdf.set_font("Noto", size=14)
            pdf.cell(0, 12, "सेवा रसीद", new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.set_font("Noto", size=10)
            lines = [
                f"Order ID: {order['order_code']}",
                f"Customer: {customer_name}",
                f"Service: {order['service_name']}",
                f"Amount: INR {order['amount']}",
                f"Payment Ref: {payment_ref}",
                f"Status: {ORDER_STATUSES.get(order['status'], order['status'])}",
                f"Date (UTC): {now_iso()}",
                "This receipt confirms the recorded order/payment review status only.",
            ]
            for line in lines:
                pdf.multi_cell(0, 8, line)
        else:
            pdf.set_font("Helvetica", size=16)
            pdf.cell(0, 12, "SERVICE RECEIPT", new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.set_font("Helvetica", size=10)
            for line in [
                f"Order ID: {order['order_code']}", f"Customer ID: {order['user_id']}",
                f"Service: {order['service_name']}", f"Amount: INR {order['amount']}",
                f"Payment Ref: {payment_ref}", f"Status: {order['status']}", f"Date (UTC): {now_iso()}",
            ]:
                pdf.multi_cell(0, 8, line)
        raw = pdf.output()
        if isinstance(raw, str):
            raw = raw.encode("latin-1")
        buf = io.BytesIO(raw)
        buf.name = f"{order['order_code']}_receipt.pdf"
        buf.seek(0)
        return buf
    except Exception:
        log.exception("Receipt generation failed")
        return None

def create_upi_qr(payment_ref: str, amount: int, order_code: str):
    if not UPI_ID:
        return None
    note = f"{order_code} {payment_ref}"
    uri = f"upi://pay?pa={quote(UPI_ID)}&pn={quote(PAYEE_NAME)}&am={amount:.2f}&cu=INR&tn={quote(note)}"
    qr = qrcode.QRCode(version=None, box_size=8, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "payment_qr.png"
    return buf

def create_order(user_id: int, service_id: str, description: str = "", urgent: bool = False):
    cat_id, svc = get_service(service_id)
    if not svc:
        raise ValueError("Unknown service")
    amount = int(svc["price"]) + (URGENT_FEE if urgent and int(svc["price"]) > 0 else 0)
    code = short_id()
    due = (datetime.now(timezone.utc) + timedelta(hours=DEFAULT_SLA_HOURS)).isoformat(timespec="seconds")
    status = "REQUESTED" if svc.get("contact_admin") or amount == 0 else "PAYMENT_PENDING"
    with db() as c:
        c.execute("""INSERT INTO orders(order_code,user_id,service_id,service_name,category_id,amount,
                   urgent,status,description,due_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (code, user_id, service_id, svc["name"], cat_id, amount, int(urgent), status,
                   description[:2000], due, now_iso(), now_iso()))
        c.execute("INSERT INTO order_events(order_code,actor_id,old_status,new_status,note,created_at) VALUES(?,?,?,?,?,?)",
                  (code, user_id, None, status, "Order created", now_iso()))
    audit(user_id, "ORDER_CREATED", code, f"service={service_id}; amount={amount}")
    return get_order(code)

def get_order(code: str):
    with db() as c:
        return c.execute("SELECT * FROM orders WHERE order_code=?", (code,)).fetchone()

def set_status(order_code: str, new_status: str, actor_id: Optional[int], note: str = ""):
    if new_status not in ORDER_STATUSES:
        raise ValueError("Invalid status")
    with db() as c:
        order = c.execute("SELECT * FROM orders WHERE order_code=?", (order_code,)).fetchone()
        if not order:
            raise ValueError("Order not found")
        old = order["status"]
        if old == new_status:
            return order
        if new_status not in VALID_TRANSITIONS.get(old, set()):
            raise ValueError(f"Invalid transition: {old} -> {new_status}")
        c.execute("UPDATE orders SET status=?,updated_at=?,assigned_admin=COALESCE(?,assigned_admin) WHERE order_code=?",
                  (new_status, now_iso(), actor_id if is_admin(actor_id) else None, order_code))
        c.execute("INSERT INTO order_events(order_code,actor_id,old_status,new_status,note,created_at) VALUES(?,?,?,?,?,?)",
                  (order_code, actor_id, old, new_status, note[:1000], now_iso()))
        updated = c.execute("SELECT * FROM orders WHERE order_code=?", (order_code,)).fetchone()
    audit(actor_id, "STATUS_CHANGE", order_code, f"{old}->{new_status}; {note}")
    return updated

def create_payment(order):
    ref = "PAY-" + uuid.uuid4().hex[:10].upper()
    with db() as c:
        c.execute("""INSERT INTO payments(payment_ref,order_code,user_id,expected_amount,status,created_at)
                     VALUES(?,?,?,?,?,?)""",
                  (ref, order["order_code"], order["user_id"], order["amount"], "PENDING", now_iso()))
    return ref

def get_payment(ref: str):
    with db() as c:
        return c.execute("SELECT * FROM payments WHERE payment_ref=?", (ref,)).fetchone()

def latest_payment(order_code: str):
    with db() as c:
        return c.execute("SELECT * FROM payments WHERE order_code=? ORDER BY id DESC LIMIT 1", (order_code,)).fetchone()

def add_proof(payment_ref: str, file_id: str, kind: str, ocr_text: str = "", claimed_amount: Optional[int] = None,
              utr: str = ""):
    # A UTR is a duplicate signal, not proof of settlement. Never auto-approve here.
    with db() as c:
        pay = c.execute("SELECT * FROM payments WHERE payment_ref=?", (payment_ref,)).fetchone()
        if not pay:
            raise ValueError("Payment reference not found")
        if utr:
            duplicate = c.execute("SELECT payment_ref FROM payments WHERE utr=? AND payment_ref<>? LIMIT 1",
                                  (utr, payment_ref)).fetchone()
            if duplicate:
                c.execute("UPDATE payments SET status='DUPLICATE_FLAG' WHERE payment_ref=?", (payment_ref,))
                audit(pay["user_id"], "DUPLICATE_UTR_FLAG", pay["order_code"], f"ref={payment_ref}")
                return "DUPLICATE"
        c.execute("""UPDATE payments SET proof_file_id=?,proof_kind=?,ocr_text=?,claimed_amount=?,utr=?,
                     status='PROOF_RECEIVED' WHERE payment_ref=?""",
                  (file_id, kind, ocr_text[:4000], claimed_amount, utr[:100], payment_ref))
    return "OK"

def extract_ocr(file_bytes: bytes, file_name: str = "") -> str:
    if not OCR_AVAILABLE:
        return ""
    try:
        image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        # OCR is only a helper; text can be forged and is never proof of payment.
        return pytesseract.image_to_string(image, lang=os.getenv("TESSERACT_LANG", "eng+hin"))[:4000]
    except Exception:
        log.info("OCR unavailable or unsupported file", exc_info=True)
        return ""

def parse_amount_from_text(text: str) -> Optional[int]:
    if not text:
        return None
    patterns = [r"(?:INR|Rs\.?|₹)\s*([0-9,]+)", r"([0-9,]+)\s*(?:INR|Rs\.?|₹)"]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None

def parse_utr_from_text(text: str) -> str:
    # Conservative candidate extraction; admin must verify against official transaction record.
    if not text:
        return ""
    m = re.search(r"\b(?:UTR|UPI\s*REF(?:ERENCE)?|TRANSACTION\s*ID|TXN\s*ID)\s*[:#-]?\s*([A-Z0-9]{8,24})\b",
                  text, re.I)
    return m.group(1).upper() if m else ""

# ================= Universal Payment Provider Adapter =================
def resolve_json_path(data: Any, path: str) -> Any:
    """Resolve simple paths such as data.items[0].status. Returns None on mismatch."""
    if not path or data is None:
        return None
    cur = data
    for part in path.split("."):
        if not part:
            return None
        m = re.fullmatch(r"([^\[\]]*)((?:\[\d+\])*)", part)
        if not m:
            return None
        key, indices = m.group(1), m.group(2)
        if key:
            if not isinstance(cur, dict) or key not in cur:
                return None
            cur = cur[key]
        for index_text in re.findall(r"\[(\d+)\]", indices):
            index = int(index_text)
            if not isinstance(cur, list) or index >= len(cur):
                return None
            cur = cur[index]
    return cur


def _replace_template(value: Any, fields: dict[str, str]) -> Any:
    """Recursively replace only named {placeholders}; does not format arbitrary JSON braces."""
    if isinstance(value, dict):
        return {str(k): _replace_template(v, fields) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_template(v, fields) for v in value]
    if isinstance(value, str):
        out = value
        for key, val in fields.items():
            out = out.replace("{" + key + "}", val)
        return out
    return value


def _env_secret(spec: Any) -> str:
    """Secrets must be referenced by environment variable; never store credentials in Turso."""
    if isinstance(spec, dict) and isinstance(spec.get("env"), str):
        env_name = spec["env"].strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", env_name):
            return ""
        return os.getenv(env_name, "").strip()
    return ""


def _provider_request_config(config: dict, fields: dict[str, str]) -> tuple[str, str, dict, Any]:
    lookup = config.get("lookup") or {}
    method = str(lookup.get("method", "GET")).upper()
    if method not in {"GET", "POST"}:
        raise ValueError("method_not_allowed")
    raw_url = str(lookup.get("url", ""))
    url_fields = {key: (quote(value, safe="") if key in {"utr", "payment_ref", "order_code"} else value)
                  for key, value in fields.items()}
    url = _replace_template(raw_url, url_fields)
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or not host or parts.username or parts.password or parts.fragment:
        raise ValueError("https_url_required")
    if parts.port not in (None, 443):
        raise ValueError("nonstandard_port_not_allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None  # A DNS name; exact allowlist check below is still mandatory.
    if ip is not None and not ip.is_global:
        raise ValueError("non_public_host")
    if not PAYMENT_PROVIDER_ALLOWED_HOSTS or host not in PAYMENT_PROVIDER_ALLOWED_HOSTS:
        raise ValueError("host_not_allowlisted")

    auth = config.get("auth") or {}
    headers = {"Accept": "application/json", "User-Agent": "CyberCafePaymentVerifier/1.0"}
    auth_type = str(auth.get("type", "none")).lower()
    if auth_type == "basic":
        import base64
        user = _env_secret(auth.get("username"))
        password = _env_secret(auth.get("password"))
        if not user or not password:
            raise ValueError("auth_env_missing")
        token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        headers["Authorization"] = "Basic " + token
    elif auth_type == "bearer":
        token = _env_secret(auth.get("token"))
        if not token:
            raise ValueError("auth_env_missing")
        headers["Authorization"] = "Bearer " + token
    elif auth_type == "header":
        header_name = str(auth.get("name", "X-API-Key"))
        if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", header_name):
            raise ValueError("invalid_auth_header")
        token = _env_secret(auth.get("value"))
        if not token:
            raise ValueError("auth_env_missing")
        headers[header_name] = token
    elif auth_type != "none":
        raise ValueError("unsupported_auth_type")

    for key, spec in (config.get("headers") or {}).items():
        if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", str(key)):
            raise ValueError("invalid_header_name")
        if isinstance(spec, dict):
            val = _env_secret(spec)
            if not val:
                raise ValueError("header_env_missing")
        else:
            val = str(spec)
        if "\r" in val or "\n" in val:
            raise ValueError("invalid_header_value")
        headers[str(key)] = val

    body = _replace_template(lookup.get("body_template"), fields) if method == "POST" else None
    if body is not None:
        headers.setdefault("Content-Type", "application/json")
    return method, url, headers, body


async def _call_provider(name: str, config: dict, payment_ref: str, order, utr: str) -> dict:
    """Verify against an authoritative API record. Fail closed on every ambiguity."""
    if not utr or len(utr.strip()) < 6:
        return {"verified": False, "provider_ref": "", "note": "utr_missing"}
    try:
        import httpx
        fields = {
            "utr": utr.strip(),
            "amount": str(int(order["amount"])),
            "payment_ref": payment_ref,
            "order_code": str(order["order_code"]),
        }
        method, url, headers, body = _provider_request_config(config, fields)
        timeout = min(20.0, max(2.0, float(config.get("timeout", PAYMENT_AUTO_VERIFY_TIMEOUT))))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            if method == "GET":
                response = await client.get(url, headers=headers)
            else:
                response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                return {"verified": False, "provider_ref": "", "note": "response_too_large"}
            data = response.json()
        if not isinstance(data, (dict, list)):
            return {"verified": False, "provider_ref": "", "note": "invalid_json_shape"}

        verify = config.get("verify") or {}
        amount_cfg = config.get("amount") or {}
        match_cfg = config.get("match") or {}
        currency_cfg = config.get("currency") or {}
        # Mandatory fields prevent the dangerous status-only / amount-only approvals.
        required = [verify.get("path"), amount_cfg.get("path"), match_cfg.get("path"), currency_cfg.get("path")]
        if not all(isinstance(x, str) and x for x in required) or "value" not in verify:
            return {"verified": False, "provider_ref": "", "note": "strict_config_fields_missing"}
        if str(currency_cfg.get("value", "INR")).upper() != "INR":
            return {"verified": False, "provider_ref": "", "note": "only_inr_orders_supported"}
        if str(match_cfg.get("source", "utr")) != "utr":
            return {"verified": False, "provider_ref": "", "note": "match_must_use_utr"}

        records_path = str((config.get("lookup") or {}).get("records_path", "") or "")
        records = resolve_json_path(data, records_path) if records_path else data
        if isinstance(records, dict):
            candidates = [records]
        elif isinstance(records, list):
            candidates = [item for item in records if isinstance(item, dict)]
        else:
            return {"verified": False, "provider_ref": "", "note": "records_not_found"}

        # First select exact UTR match. Never trust items[0] from a recent-payment list.
        matched = []
        for item in candidates:
            actual_utr = resolve_json_path(item, match_cfg["path"])
            if actual_utr is not None and str(actual_utr).strip().casefold() == utr.strip().casefold():
                matched.append(item)
        if len(matched) != 1:
            return {"verified": False, "provider_ref": "", "note": "utr_match_not_unique"}
        record = matched[0]

        actual_status = resolve_json_path(record, verify["path"])
        expected_status = verify.get("value")
        if actual_status != expected_status:
            return {"verified": False, "provider_ref": "", "note": "provider_status_not_paid"}
        actual_currency = resolve_json_path(record, currency_cfg["path"])
        expected_currency = str(currency_cfg.get("value", "INR")).upper()
        if str(actual_currency or "").upper() != expected_currency:
            return {"verified": False, "provider_ref": "", "note": "currency_mismatch"}
        raw_amount = resolve_json_path(record, amount_cfg["path"])
        try:
            from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
            multiplier = Decimal(str(amount_cfg.get("multiplier", 1)))
            got_amount = (Decimal(str(raw_amount)) * multiplier).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
            expected_amount = Decimal(str(int(order["amount"])))
            tolerance = Decimal(str(amount_cfg.get("tolerance", 0)))
            if multiplier <= 0 or multiplier > Decimal("1000") or tolerance < 0 or tolerance > Decimal("1") or abs(got_amount - expected_amount) > tolerance:
                return {"verified": False, "provider_ref": "", "note": "amount_mismatch"}
        except Exception:
            return {"verified": False, "provider_ref": "", "note": "amount_unreadable"}
        id_path = str((config.get("id") or {}).get("path", "") or "")
        provider_ref = resolve_json_path(record, id_path) if id_path else ""
        return {"verified": True, "provider_ref": str(provider_ref or "")[:160], "note": "exact_utr_status_amount_currency_match"}
    except Exception as exc:
        # Deliberately avoid logging URLs, headers, credentials, UTRs or response bodies.
        log.warning("Payment provider %s check failed (%s)", name, type(exc).__name__)
        return {"verified": False, "provider_ref": "", "note": f"provider_error:{type(exc).__name__}"}


async def universal_try_verify(payment_ref: str, order, utr: str) -> dict:
    """Try configured providers in priority order; manual review is always the fallback."""
    if not PAYMENT_AUTO_VERIFY_ENABLED:
        return {"verified": False, "provider": "", "provider_ref": "", "note": "auto_verify_disabled"}
    if not utr:
        return {"verified": False, "provider": "", "provider_ref": "", "note": "utr_missing"}
    with db() as c:
        providers = c.execute(
            "SELECT name,config_json FROM payment_providers WHERE enabled=1 ORDER BY priority ASC,name ASC LIMIT 10"
        ).fetchall()
    for provider in providers:
        name = str(provider["name"])
        try:
            config = json.loads(provider["config_json"])
            if not isinstance(config, dict):
                continue
        except Exception:
            log.warning("Payment provider %s has invalid stored JSON", name)
            continue
        result = await _call_provider(name, config, payment_ref, order, utr)
        if result.get("verified"):
            return {"verified": True, "provider": name, "provider_ref": result.get("provider_ref", ""),
                    "note": result.get("note", "")}
    return {"verified": False, "provider": "", "provider_ref": "", "note": "no_authoritative_match"}


def apply_auto_verified_payment(payment_ref: str, provider: str, provider_ref: str, note: str) -> bool:
    """Atomically mark payment + order paid, only from a reviewable payment state."""
    with db() as c:
        pay = c.execute("SELECT * FROM payments WHERE payment_ref=?", (payment_ref,)).fetchone()
        if not pay or pay["status"] != "PROOF_RECEIVED" or not pay["utr"]:
            return False
        order = c.execute("SELECT * FROM orders WHERE order_code=?", (pay["order_code"],)).fetchone()
        if not order or order["status"] not in {"PAYMENT_REVIEW", "PAYMENT_PENDING"}:
            return False
        now = now_iso()
        cur = c.execute("""UPDATE payments SET status='AUTO_VERIFIED', payment_source=?,
                         auto_verify_note=?, provider_ref=?, reviewed_by=0, reviewed_at=?
                         WHERE payment_ref=? AND status='PROOF_RECEIVED'""",
                        (provider, note[:500], provider_ref[:160], now, payment_ref))
        if cur.rowcount != 1:
            return False
        cur = c.execute("UPDATE orders SET status='PAID',updated_at=? WHERE order_code=? AND status IN ('PAYMENT_REVIEW','PAYMENT_PENDING')",
                        (now, order["order_code"]))
        if cur.rowcount != 1:
            raise RuntimeError("order_state_changed_during_auto_verification")
        c.execute("INSERT INTO order_events(order_code,actor_id,old_status,new_status,note,created_at) VALUES(?,?,?,?,?,?)",
                  (order["order_code"], 0, order["status"], "PAID",
                   f"Payment auto-verified by {provider}; provider_ref={provider_ref[:100]}", now))
    audit(0, "PAYMENT_AUTO_VERIFIED", pay["order_code"], f"ref={payment_ref}; provider={provider}")
    return True


def apply_manual_payment_decision(payment_ref: str, actor_id: int, approve: bool) -> Optional[dict[str, Any]]:
    """Atomically update payment and order so one side cannot be committed alone."""
    target_payment = "VERIFIED_BY_ADMIN" if approve else "REJECTED_BY_ADMIN"
    target_order = "PAID" if approve else "PAYMENT_PENDING"
    with db() as c:
        pay = c.execute("SELECT * FROM payments WHERE payment_ref=?", (payment_ref,)).fetchone()
        if not pay or pay["status"] in {"AUTO_VERIFIED", "VERIFIED_BY_ADMIN", "REJECTED_BY_ADMIN", "REVERSED_BY_ADMIN"}:
            return None
        order = c.execute("SELECT * FROM orders WHERE order_code=?", (pay["order_code"],)).fetchone()
        if not order or order["status"] not in {"PAYMENT_REVIEW", "PAYMENT_PENDING", "NEEDS_ADMIN"}:
            return None
        old_status = order["status"]
        if target_order != old_status and target_order not in VALID_TRANSITIONS.get(old_status, set()):
            return None
        now = now_iso()
        cur = c.execute("UPDATE payments SET status=?,payment_source=COALESCE(payment_source,'manual'),reviewed_by=?,reviewed_at=? WHERE payment_ref=? AND status NOT IN ('AUTO_VERIFIED','VERIFIED_BY_ADMIN','REJECTED_BY_ADMIN','REVERSED_BY_ADMIN')",
                        (target_payment, actor_id, now, payment_ref))
        if cur.rowcount != 1:
            return None
        if target_order != old_status:
            c.execute("UPDATE orders SET status=?,updated_at=?,assigned_admin=? WHERE order_code=?",
                      (target_order, now, actor_id, order["order_code"]))
            c.execute("INSERT INTO order_events(order_code,actor_id,old_status,new_status,note,created_at) VALUES(?,?,?,?,?,?)",
                      (order["order_code"], actor_id, old_status, target_order,
                       f"Payment {'verified' if approve else 'rejected'} manually; ref={payment_ref}", now))
        result = dict(pay)
        result["status"] = target_payment
        result["payment_source"] = pay["payment_source"] or "manual"
    audit(actor_id, "PAYMENT_APPROVED" if approve else "PAYMENT_REJECTED", result["order_code"], payment_ref)
    return result


def reverse_auto_verified_payment(payment_ref: str, actor_id: int) -> Optional[dict[str, Any]]:
    """Atomically reverse an automatic decision and send the order to NEEDS_ADMIN."""
    with db() as c:
        pay = c.execute("SELECT * FROM payments WHERE payment_ref=? AND status='AUTO_VERIFIED'", (payment_ref,)).fetchone()
        if not pay:
            return None
        order = c.execute("SELECT * FROM orders WHERE order_code=?", (pay["order_code"],)).fetchone()
        if not order or order["status"] != "PAID":
            return None
        now = now_iso()
        cur = c.execute("UPDATE payments SET status='REVERSED_BY_ADMIN',reviewed_by=?,reviewed_at=? WHERE payment_ref=? AND status='AUTO_VERIFIED'",
                        (actor_id, now, payment_ref))
        if cur.rowcount != 1:
            return None
        c.execute("UPDATE orders SET status='NEEDS_ADMIN',updated_at=?,assigned_admin=? WHERE order_code=? AND status='PAID'",
                  (now, actor_id, order["order_code"]))
        c.execute("INSERT INTO order_events(order_code,actor_id,old_status,new_status,note,created_at) VALUES(?,?,?,?,?,?)",
                  (order["order_code"], actor_id, "PAID", "NEEDS_ADMIN", f"Auto verification reversed; ref={payment_ref}", now))
        result = dict(pay)
    audit(actor_id, "PAYMENT_AUTO_VERIFICATION_REVERSED", result["order_code"], payment_ref)
    return result


# Built-in payment gateway directory. This is an onboarding directory, not a claim that
# every listed provider is already wired to the current UPI-QR payment flow.
PAYMENT_GATEWAY_DIRECTORY = {
    "manual": {
        "name": "UPI QR / Bank transfer (manual review)",
        "mode": "No gateway API required",
        "docs": "",
        "status": "READY",
        "details": "Customer pays to your own UPI/bank account. Admin checks the actual bank/UPI transaction and approves manually. QR/screenshot/OCR is never proof by itself.",
        "steps": "1) /setup में अपनी UPI ID सेट करें।\n2) Test order बनाएं।\n3) अपने बैंक/UPI ऐप में वास्तविक transaction देखकर ही approve करें।",
    },
    "razorpay": {
        "name": "Razorpay",
        "mode": "Order/Payment API + optional webhook",
        "docs": "https://razorpay.com/docs/api/",
        "status": "GUIDED — not plug-and-play in this build",
        "details": "Razorpay API credentials and an order/payment-link flow are required. A payment made directly to a personal UPI QR is not automatically visible in a Razorpay merchant account. Webhook requires a public HTTPS endpoint.",
        "steps": "1) Razorpay merchant account में API credentials लें।\n2) Test mode में order/payment link बनाना और status fetch करना सेट करें।\n3) इस bot का मौजूदा QR flow सीधे Razorpay order नहीं बनाता; इसलिए केवल credentials डालने से integration चालू नहीं होगी।\n4) Webhook के लिए public HTTPS receiver चाहिए; GitHub Actions polling job receiver नहीं है।",
    },
    "cashfree": {
        "name": "Cashfree Payments",
        "mode": "Order Payments API + webhook",
        "docs": "https://docs.cashfree.com/",
        "status": "GUIDED — not plug-and-play in this build",
        "details": "Cashfree payment status is tied to a Cashfree order/payment identifier. Direct UPI QR transfers outside Cashfree cannot be looked up in Cashfree. Webhook requires a public HTTPS endpoint.",
        "steps": "1) Cashfree merchant account और API credentials लें।\n2) Bot से Cashfree order/session create करने और उसी order का payment status fetch करने वाला adapter चाहिए।\n3) मौजूदा UPI QR अकेले यह order नहीं बनाता।\n4) Webhook receiver अलग सार्वजनिक HTTPS endpoint पर चलना चाहिए।",
    },
    "phonepe": {
        "name": "PhonePe Payment Gateway",
        "mode": "Merchant order/status API + webhook/callback",
        "docs": "https://developer.phonepe.com/",
        "status": "GUIDED — merchant integration required",
        "details": "PhonePe PG status checks use merchant-side order/transaction identifiers and the applicable API authentication/signature rules. Do not assume any UTR-search endpoint exists for every PhonePe product/account.",
        "steps": "1) PhonePe PG merchant onboarding और credentials लें।\n2) Merchant order ID को bot order से सुरक्षित रूप से map करना होगा।\n3) Status API/signature rules product/version के अनुसार implement और test करने होंगे।\n4) Callback/webhook के लिए public HTTPS receiver चाहिए।",
    },
    "paytm": {
        "name": "Paytm Payment Gateway",
        "mode": "Transaction Status API + callback/webhook",
        "docs": "https://business.paytm.com/docs/",
        "status": "GUIDED — merchant integration required",
        "details": "Paytm transaction status uses merchant/order identifiers and Paytm-specific checksum/signature validation. A callback/webhook payload must not be trusted without verifying the signature/checksum.",
        "steps": "1) Paytm merchant account/MID और API credentials लें।\n2) Order creation और Transaction Status API को bot order से map करना होगा।\n3) Paytm checksum/signature validation जरूरी है।\n4) Webhook/callback के लिए public HTTPS receiver चाहिए।",
    },
    "custom": {
        "name": "Other gateway / Custom API",
        "mode": "Generic REST pull adapter, where compatible",
        "docs": "",
        "status": "ADVANCED — API details needed",
        "details": "The existing generic adapter can query a compatible HTTPS JSON API when the owner configures exact host, auth, response paths, UTR, paid status, amount, and INR currency. It does not discover API schemas automatically and it does not receive webhooks.",
        "steps": "1) Provider की official API docs से status endpoint और response schema लेना होगा।\n2) Current generic adapter में केवल pull-based compatible lookup संभव है; create-order/signature-specific flows may need a dedicated adapter.\n3) API secret GitHub Secrets में रखें, Telegram या JSON config में नहीं।\n4) Unknown/mismatched result हमेशा manual review में रहेगा।",
    },
}

async def paymentsetup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user.id if user else None):
        await update.effective_message.reply_text("Payment integration setup केवल Owner कर सकता है।")
        return
    buttons = [
        [InlineKeyboardButton("✅ UPI QR / Manual review", callback_data="paygw:manual")],
        [InlineKeyboardButton("Razorpay", callback_data="paygw:razorpay"), InlineKeyboardButton("Cashfree", callback_data="paygw:cashfree")],
        [InlineKeyboardButton("PhonePe PG", callback_data="paygw:phonepe"), InlineKeyboardButton("Paytm PG", callback_data="paygw:paytm")],
        [InlineKeyboardButton("🌐 Other / Custom API", callback_data="paygw:custom")],
        [InlineKeyboardButton("Configured providers", callback_data="paygw:list")],
    ]
    await update.effective_message.reply_text(
        "💳 <b>Payment Integration Centre</b>\n\n"
        "Gateway चुनें। यह wizard आसान भाषा में आवश्यकताएँ बताएगा।\n\n"
        "⚠️ Gateway चुनने से integration अपने-आप चालू नहीं होती। इस build का मौजूदा customer payment flow UPI QR है; gateway-specific order creation/status/signature support अलग से आवश्यक हो सकता है।\n"
        "Webhook-only gateways के लिए public HTTPS receiver चाहिए, जो GitHub Actions polling job नहीं है।",
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))

async def payment_gateway_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_owner(q.from_user.id):
        await q.answer("केवल Owner देख सकता है", show_alert=True)
        return
    await q.answer()
    key = q.data.split(":", 1)[1]
    if key == "list":
        with db() as c:
            rows = c.execute("SELECT name,enabled,priority,updated_at FROM payment_providers ORDER BY priority,name").fetchall()
        if not rows:
            body = "अभी कोई generic API provider configured नहीं है।"
        else:
            body = "\n".join(f"• <code>{esc(r['name'])}</code> — {'ON' if r['enabled'] else 'OFF'}" for r in rows)
        await q.edit_message_text("💳 <b>Configured API providers</b>\n\n" + body + "\n\nAuto-verification default से OFF रहती है।",
                                  parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Gateway menu", callback_data="paygw:menu")]]))
        return
    if key == "menu":
        # Reuse the public command's menu without needing the user to type a JSON config.
        buttons = [
            [InlineKeyboardButton("✅ UPI QR / Manual review", callback_data="paygw:manual")],
            [InlineKeyboardButton("Razorpay", callback_data="paygw:razorpay"), InlineKeyboardButton("Cashfree", callback_data="paygw:cashfree")],
            [InlineKeyboardButton("PhonePe PG", callback_data="paygw:phonepe"), InlineKeyboardButton("Paytm PG", callback_data="paygw:paytm")],
            [InlineKeyboardButton("🌐 Other / Custom API", callback_data="paygw:custom")],
            [InlineKeyboardButton("Configured providers", callback_data="paygw:list")],
        ]
        await q.edit_message_text("💳 <b>Payment Integration Centre</b>\nGateway चुनें। किसी provider को live करने से पहले sandbox test आवश्यक है।",
                                  parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
        return
    info = PAYMENT_GATEWAY_DIRECTORY.get(key)
    if not info:
        await q.edit_message_text("Gateway entry नहीं मिली। /paymentsetup फिर चलाएँ।")
        return
    docs = f"\n\n📚 Official docs: <a href=\"{info['docs']}\">यहाँ खोलें</a>" if info.get("docs") else ""
    text = (f"💳 <b>{esc(info['name'])}</b>\n"
            f"स्थिति: <b>{esc(info['status'])}</b>\n"
            f"Integration प्रकार: {esc(info['mode'])}\n\n"
            f"{esc(info['details'])}\n\n"
            f"<b>आसान अगले कदम</b>\n{esc(info['steps'])}{docs}\n\n"
            "🔐 सुरक्षा: API secret केवल GitHub Actions Secrets में रखें। UTR/amount/status/currency/order mapping verify किए बिना payment auto-approve न करें।")
    await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Gateway menu", callback_data="paygw:menu")],
        [InlineKeyboardButton("Configured providers", callback_data="paygw:list")],
    ]), disable_web_page_preview=True)

async def providers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    if not is_owner(uid):
        await update.effective_message.reply_text("केवल Owner provider settings बदल सकता है।")
        return
    with db() as c:
        rows = c.execute("SELECT name,enabled,priority,updated_at FROM payment_providers ORDER BY priority,name").fetchall()
    if not rows:
        text = ("अभी कोई generic API provider configured नहीं है।\n"
                "आसान भाषा में provider की जरूरत और सीमाएँ देखने के लिए /paymentsetup चलाएँ।\n"
                "Advanced setup में API docs के अनुसार config और exact host allowlist चाहिए।\n"
                "Auto verification default से OFF है; पहले test bot पर जाँचें।")
    else:
        lines = ["💳 <b>Payment Providers</b>"]
        lines.extend(f"• <code>{esc(r['name'])}</code> — {'ON' if r['enabled'] else 'OFF'} · priority {r['priority']}" for r in rows)
        text = "\n".join(lines)
    text += "\n\n/paymentsetup — आसान gateway guide\n/providers · /addprovider name JSON · /toggleprovider name · /delprovider name · /testprovider name UTR"
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 आसान Payment Setup", callback_data="paygw:menu")]]))


async def addprovider_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    if not is_owner(uid):
        await update.effective_message.reply_text("केवल Owner provider settings बदल सकता है।")
        return
    if len(context.args) < 2:
        await update.effective_message.reply_text('Format: /addprovider name {"enabled":true,"priority":10,...}')
        return
    name = context.args[0].strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{2,32}", name):
        await update.effective_message.reply_text("Name 2–32 lowercase letters/digits/underscore का होना चाहिए।")
        return
    raw = " ".join(context.args[1:])
    if len(raw) > 12000:
        await update.effective_message.reply_text("Config बहुत बड़ा है; अधिकतम 12,000 characters।")
        return
    try:
        config = json.loads(raw)
        if not isinstance(config, dict):
            raise ValueError("JSON object required")
        enabled = 1 if config.get("enabled", True) else 0
        priority = int(config.get("priority", 100))
        if priority < 0 or priority > 10000:
            raise ValueError("priority 0–10000 होना चाहिए")
        # Fail closed unless all strict verification fields are configured.
        if enabled:
            lookup = config.get("lookup") or {}
            if not isinstance(lookup, dict) or not lookup.get("url"):
                raise ValueError("lookup.url required")
            verify_cfg = config.get("verify") or {}
            if not verify_cfg.get("path") or "value" not in verify_cfg:
                raise ValueError("verify.path and verify.value required")
            if not all((config.get("amount") or {}).get(k) for k in ("path",)):
                raise ValueError("amount.path required")
            if not all((config.get("match") or {}).get(k) for k in ("path",)):
                raise ValueError("match.path required")
            currency_cfg = config.get("currency") or {}
            if not currency_cfg.get("path") or str(currency_cfg.get("value", "INR")).upper() != "INR":
                raise ValueError("currency.path required and currency.value must be INR")
            amount_cfg = config.get("amount") or {}
            try:
                tolerance = float(amount_cfg.get("tolerance", 0))
                multiplier = float(amount_cfg.get("multiplier", 1))
            except (TypeError, ValueError):
                raise ValueError("amount multiplier/tolerance invalid")
            if multiplier <= 0 or multiplier > 1000 or tolerance < 0 or tolerance > 1:
                raise ValueError("amount multiplier must be >0 and <=1000; tolerance must be 0–1 INR")
            if str((config.get("match") or {}).get("source", "utr")) != "utr":
                raise ValueError("match.source must be utr")
        with db() as c:
            c.execute("""INSERT INTO payment_providers(name,config_json,enabled,priority,updated_at)
                         VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET config_json=excluded.config_json,
                         enabled=excluded.enabled,priority=excluded.priority,updated_at=excluded.updated_at""",
                      (name, json.dumps(config, separators=(",", ":")), enabled, priority, now_iso()))
        audit(uid, "PROVIDER_UPSERTED", name, f"enabled={enabled}; priority={priority}")
        await update.effective_message.reply_text(
            f"✅ Provider <code>{esc(name)}</code> save हुआ।\nEnabled={bool(enabled)}, priority={priority}.\n"
            "Credentials केवल GitHub Secrets/Variables के environment references से दें; JSON में API secret न डालें।\n"
            "यह config अपने-आप provider की compatibility प्रमाणित नहीं करता। /testprovider से जाँचें।",
            parse_mode=ParseMode.HTML)
    except Exception as exc:
        await update.effective_message.reply_text(f"Config save नहीं हुआ: {esc(str(exc)[:250])}", parse_mode=ParseMode.HTML)


async def delprovider_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    if not is_owner(uid):
        await update.effective_message.reply_text("केवल Owner provider settings बदल सकता है।")
        return
    if not context.args:
        await update.effective_message.reply_text("Format: /delprovider name")
        return
    name = context.args[0].strip().lower()
    with db() as c:
        cur = c.execute("DELETE FROM payment_providers WHERE name=?", (name,))
    audit(uid, "PROVIDER_DELETED", name, f"rows={cur.rowcount}")
    await update.effective_message.reply_text("✅ Deleted" if cur.rowcount else "Provider नहीं मिला।")


async def toggleprovider_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    if not is_owner(uid):
        await update.effective_message.reply_text("केवल Owner provider settings बदल सकता है।")
        return
    if not context.args:
        await update.effective_message.reply_text("Format: /toggleprovider name")
        return
    name = context.args[0].strip().lower()
    with db() as c:
        row = c.execute("SELECT enabled FROM payment_providers WHERE name=?", (name,)).fetchone()
        if not row:
            await update.effective_message.reply_text("Provider नहीं मिला।")
            return
        new_state = 0 if row["enabled"] else 1
        c.execute("UPDATE payment_providers SET enabled=?,updated_at=? WHERE name=?", (new_state, now_iso(), name))
    audit(uid, "PROVIDER_TOGGLED", name, str(new_state))
    await update.effective_message.reply_text(f"{'✅ Enabled' if new_state else '⏸️ Disabled'}: {esc(name)}")


async def testprovider_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    if not is_owner(uid):
        await update.effective_message.reply_text("केवल Owner provider test कर सकता है।")
        return
    if len(context.args) < 3:
        await update.effective_message.reply_text("Format: /testprovider name REAL_UTR ORDER_CODE\nयह केवल lookup करेगा, कोई payment/order status नहीं बदलेगा।")
        return
    name, utr, order_code = context.args[0].strip().lower(), context.args[1].strip(), context.args[2].strip().upper()
    with db() as c:
        row = c.execute("SELECT config_json FROM payment_providers WHERE name=?", (name,)).fetchone()
    if not row:
        await update.effective_message.reply_text("Provider नहीं मिला।")
        return
    try:
        config = json.loads(row["config_json"])
        test_order = get_order(order_code)
        if not test_order:
            await update.effective_message.reply_text("Order code नहीं मिला।")
            return
        # This performs a read-only API lookup only; it never updates payment/order state.
        result = await _call_provider(name, config, "TEST-ONLY", test_order, utr)
        await update.effective_message.reply_text(
            f"<b>Provider test: {esc(name)}</b>\nOrder: <code>{esc(order_code)}</code>\n"
            f"Match: {bool(result.get('verified'))}\nResult: <code>{esc(result.get('note',''))}</code>\n"
            "यह test किसी payment/order को approve नहीं करता।",
            parse_mode=ParseMode.HTML)
    except Exception as exc:
        await update.effective_message.reply_text(f"Test failed: {esc(type(exc).__name__)}", parse_mode=ParseMode.HTML)

# ========================================================================

def _button_label(text: str, limit: int = 60) -> str:
    """Telegram inline button text is limited; keep labels readable on narrow phones."""
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit - 1].rstrip() + "…"


def main_keyboard():
    # One full-width button per row: two-column buttons clipped important Hindi text
    # on narrow Android screens. Telegram bots cannot force device landscape mode.
    rows = []
    for cat_id, cat in CATEGORIES.items():
        if not any(svc.get("active", True) for svc in cat.get("services", [])):
            continue
        label = _button_label(f"{cat.get('emoji', '📁')} {cat.get('name', cat_id)}")
        rows.append([InlineKeyboardButton(label, callback_data=f"cat_{cat_id}")])
    rows.extend([
        [InlineKeyboardButton("📦 मेरे ऑर्डर", callback_data="my_orders")],
        [InlineKeyboardButton("🆘 सहायता और संपर्क", callback_data="help_menu")],
        [InlineKeyboardButton("🔐 डेटा और प्राइवेसी", callback_data="privacy_info")],
    ])
    return InlineKeyboardMarkup(rows)


def reply_keyboard():
    # Keep text labels short so they fit on small screens; full descriptions are in chat.
    return ReplyKeyboardMarkup([
        [KeyboardButton("🛍️ सर्विस मेनू")],
        [KeyboardButton("📦 मेरे ऑर्डर"), KeyboardButton("🆘 मदद")],
        [KeyboardButton("📞 संपर्क"), KeyboardButton("❌ रद्द करें")],
    ], resize_keyboard=True, is_persistent=True, input_field_placeholder="अपना काम लिखें या मेनू चुनें…")


def category_keyboard(cat_id: str):
    cat = CATEGORIES.get(cat_id)
    if not cat:
        return main_keyboard()
    rows = []
    for svc in cat["services"]:
        if not svc.get("active", True):
            continue
        # Full service names are also printed in the category message. Buttons use
        # Telegram's 64-character limit and occupy a whole row for better visibility.
        label = _button_label(f"{svc.get('emoji', '🛠️')} {svc['name']}")
        rows.append([InlineKeyboardButton(label, callback_data=f"service:{svc['id']}")])
    rows.append([InlineKeyboardButton("⬅️ मुख्य मेनू", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_customer(user)
    context.user_data.clear()
    text = (
        f"🙏 <b>नमस्ते {esc(user.first_name)}!</b>\n\n"
        f"🏪 <b>{esc(PAYEE_NAME)}</b> में स्वागत है।\n"
        "अपनी सर्विस चुनें या सामान्य भाषा में अपना काम लिखें।\n\n"
        "🔒 कृपया OTP, पासवर्ड या बैंक PIN कभी न भेजें।\n"
        "भुगतान की अंतिम पुष्टि आधिकारिक ट्रांजैक्शन रिकॉर्ड से होती है।"
    )
    try:
        banner = create_banner(PAYEE_NAME, "Digital Services")
        await update.effective_message.reply_animation(animation=banner, caption=text,
            parse_mode=ParseMode.HTML)
    except Exception:
        log.info("Welcome animation unavailable; continuing with text menu")
    # Keep inline buttons on a normal text message so edit_message_text callbacks work reliably.
    await update.effective_message.reply_text("👇 <b>सर्विस चुनें:</b>", parse_mode=ParseMode.HTML,
                                              reply_markup=main_keyboard())
    await update.effective_message.reply_text("नीचे के मेनू से भी विकल्प चुन सकते हैं।", reply_markup=reply_keyboard())

async def show_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cat_id = q.data.removeprefix("cat_")
    cat = CATEGORIES.get(cat_id)
    if not cat:
        await q.edit_message_text("यह कैटेगरी उपलब्ध नहीं है।")
        return
    active_services = [svc for svc in cat.get("services", []) if svc.get("active", True)]
    # Show complete names and prices in the message itself, so no information depends
    # on button width. Keep message within Telegram's 4096-character limit.
    service_lines = []
    for index, svc in enumerate(active_services, 1):
        price = "एडमिन से कीमत पूछें" if svc.get("contact_admin") else f"₹{money(svc.get('price', 0))}"
        service_lines.append(f"{index}. {esc(svc.get('emoji', '🛠️'))} <b>{esc(svc.get('name', 'सर्विस'))}</b> — {esc(price)}")
    body = (f"<b>{esc(cat['name'])}</b>\n{esc(cat.get('desc', ''))}\n\n"
            "<b>उपलब्ध सर्विस और पूरी जानकारी:</b>\n" + "\n".join(service_lines) +
            "\n\n👇 अपनी सर्विस चुनें:")
    if len(body) > 3900:
        body = body[:3850] + "\n…अधिक विवरण के लिए सर्विस चुनें।"
    await q.edit_message_text(body, parse_mode=ParseMode.HTML,
                              reply_markup=category_keyboard(cat_id))

async def show_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    service_id = q.data.split(":", 1)[1]
    cat_id, svc = get_service(service_id)
    if not svc:
        await q.edit_message_text("सर्विस नहीं मिली। /start दबाएँ।")
        return
    context.user_data["service_id"] = service_id
    context.user_data["urgent"] = False
    if svc.get("contact_admin"):
        context.user_data["awaiting_custom_request"] = True
        await q.edit_message_text(
            f"<b>{esc(svc['name'])}</b>\n{esc(svc['docs'])}\n\nअपना काम विवरण लिखकर भेजें। एडमिन कीमत की पुष्टि करेगा।",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ वापस", callback_data=f"cat_{cat_id}")]]))
        return
    amount = int(svc["price"])
    kb = [
        [InlineKeyboardButton("⚡ Urgent (+₹%s)" % URGENT_FEE, callback_data=f"urgent:{service_id}")],
        [InlineKeyboardButton("🧾 ऑर्डर बनाएं", callback_data=f"order:{service_id}")],
        [InlineKeyboardButton("⬅️ वापस", callback_data=f"cat_{cat_id}")],
    ]
    await q.edit_message_text(
        f"<b>{esc(svc['name'])}</b>\n━━━━━━━━━━━━\n"
        f"फीस: <b>{money(amount)}</b>\n📄 {esc(svc.get('docs','दस्तावेज़ निर्देश उपलब्ध नहीं हैं।'))}\n\n"
        "ऑर्डर बनने के बाद भुगतान QR/निर्देश दिखेंगे।",
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
    for attached in svc.get("files", [])[:3]:
        try:
            if attached.get("kind") == "photo":
                await context.bot.send_photo(q.message.chat_id, attached["file_id"],
                    caption=esc(attached.get("name", "सर्विस दस्तावेज़"))[:900])
            else:
                await context.bot.send_document(q.message.chat_id, attached["file_id"],
                    caption=esc(attached.get("name", "सर्विस दस्तावेज़"))[:900])
        except TelegramError:
            log.warning("Could not send attached service file: %s", service_id)

async def toggle_urgent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    service_id = q.data.split(":", 1)[1]
    context.user_data["urgent"] = not context.user_data.get("urgent", False)
    _, svc = get_service(service_id)
    if not svc:
        await q.edit_message_text("सर्विस नहीं मिली।")
        return
    amount = int(svc["price"]) + (URGENT_FEE if context.user_data["urgent"] else 0)
    label = "हटाएँ" if context.user_data["urgent"] else "जोड़ें"
    kb = [
        [InlineKeyboardButton(f"⚡ Urgent {label} (+₹{URGENT_FEE})", callback_data=f"urgent:{service_id}")],
        [InlineKeyboardButton("🧾 ऑर्डर बनाएं", callback_data=f"order:{service_id}")],
        [InlineKeyboardButton("⬅️ वापस", callback_data=f"service:{service_id}")],
    ]
    await q.edit_message_text(
        f"<b>{esc(svc['name'])}</b>\nफीस: <b>{money(amount)}</b>\nUrgent: {'हाँ' if context.user_data['urgent'] else 'नहीं'}",
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

async def create_order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    service_id = q.data.split(":", 1)[1]
    _, svc = get_service(service_id)
    if not svc:
        await q.edit_message_text("सर्विस नहीं मिली।")
        return
    order = create_order(q.from_user.id, service_id, urgent=context.user_data.get("urgent", False))
    context.user_data["current_order"] = order["order_code"]
    payment = None
    if order["amount"] > 0:
        payment = create_payment(order)
    await q.edit_message_text(
        f"✅ <b>ऑर्डर बन गया!</b>\n\n🆔 Order ID: <code>{order['order_code']}</code>\n"
        f"🛠️ सर्विस: {esc(order['service_name'])}\n💰 राशि: <b>{money(order['amount'])}</b>\n"
        f"📌 स्थिति: {esc(ORDER_STATUSES[order['status']])}\n\n"
        + (f"💳 Payment Reference: <code>{payment}</code>\nQR स्कैन करें और भुगतान प्रमाण इसी चैट में भेजें।\n"
           if payment else "एडमिन जल्द ही कीमत और अगले चरण की पुष्टि करेगा।\n")
        + "\n/myorders से ऑर्डर ट्रैक करें।",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 मेरे ऑर्डर", callback_data="my_orders"),
                                            InlineKeyboardButton("🏠 मुख्य मेनू", callback_data="back_main")]]))
    if payment:
        qr = create_upi_qr(payment, order["amount"], order["order_code"])
        if qr:
            await context.bot.send_photo(chat_id=q.message.chat_id, photo=qr,
                caption=f"💳 Order: {order['order_code']}\nReference: {payment}\nAmount: {money(order['amount'])}\n"
                        "भुगतान के बाद स्क्रीनशॉट भेजें। यह QR अपने आप भुगतान सत्यापित नहीं करता।")
    await notify_admins(context,
        f"🆕 <b>नया ऑर्डर</b>\nID: <code>{order['order_code']}</code>\n"
        f"ग्राहक: {esc(q.from_user.full_name)} (<code>{q.from_user.id}</code>)\n"
        f"सर्विस: {esc(order['service_name'])}\nराशि: {money(order['amount'])}\n"
        f"स्थिति: {esc(ORDER_STATUSES[order['status']])}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔎 ऑर्डर खोलें", callback_data=f"admin_order:{order['order_code']}")]]))

async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: Optional[int] = None):
    uid = user_id or update.effective_user.id
    with db() as c:
        rows = c.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
    if not rows:
        text = "अभी कोई ऑर्डर नहीं है।"
        kb = main_keyboard()
    else:
        lines = ["<b>📦 आपके हाल के ऑर्डर</b>"]
        buttons = []
        for row in rows:
            lines.append(f"\n<code>{row['order_code']}</code> — {esc(row['service_name'])}\n"
                         f"{esc(ORDER_STATUSES.get(row['status'], row['status']))} · {money(row['amount'])}")
            buttons.append([InlineKeyboardButton(f"🔎 {row['order_code']}", callback_data=f"order_detail:{row['order_code']}")])
        buttons.append([InlineKeyboardButton("🏠 मुख्य मेनू", callback_data="back_main")])
        text, kb = "\n".join(lines), InlineKeyboardMarkup(buttons)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    code = q.data.split(":", 1)[1]
    order = get_order(code)
    if not order or (order["user_id"] != q.from_user.id and not is_admin(q.from_user.id)):
        await q.edit_message_text("ऑर्डर नहीं मिला या आपको अनुमति नहीं है।")
        return
    with db() as c:
        events = c.execute("SELECT * FROM order_events WHERE order_code=? ORDER BY id DESC LIMIT 8", (code,)).fetchall()
        pay = c.execute("SELECT * FROM payments WHERE order_code=? ORDER BY id DESC LIMIT 1", (code,)).fetchone()
    lines = [
        f"<b>ऑर्डर {esc(code)}</b>", f"सर्विस: {esc(order['service_name'])}",
        f"राशि: {money(order['amount'])}", f"स्थिति: {esc(ORDER_STATUSES.get(order['status'], order['status']))}",
        f"बनाया गया: {esc(order['created_at'])}", f"Due (UTC): {esc(order['due_at'] or 'N/A')}",
    ]
    if pay:
        lines.append(f"Payment Ref: <code>{esc(pay['payment_ref'])}</code> · {esc(pay['status'])}")
    if events:
        lines.append("\n<b>इतिहास</b>")
        for ev in events:
            lines.append(f"• {esc(ev['created_at'])}: {esc(ev['new_status'] or '')} — {esc(ev['note'] or '')}")
    buttons = [[InlineKeyboardButton("⬅️ मेरे ऑर्डर", callback_data="my_orders")]]
    if order["user_id"] == q.from_user.id and order["status"] not in {"COMPLETED", "CANCELLED", "REFUNDED"}:
        buttons.append([InlineKeyboardButton("📄 दस्तावेज़ भेजें", callback_data=f"upload_docs:{code}")])
    if is_admin(q.from_user.id):
        buttons.append([InlineKeyboardButton("🛠️ एडमिन कार्य", callback_data=f"admin_order:{code}")])
    await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML,
                              reply_markup=InlineKeyboardMarkup(buttons))

async def upload_docs_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    code = q.data.split(":", 1)[1]
    order = get_order(code)
    if not order or order["user_id"] != q.from_user.id:
        await q.edit_message_text("ऑर्डर नहीं मिला।")
        return
    context.user_data["upload_order_code"] = code
    context.user_data["awaiting_document"] = True
    await q.edit_message_text(
        f"📄 ऑर्डर <code>{esc(code)}</code> के लिए दस्तावेज़ भेजें।\n"
        f"अधिकतम फ़ाइल आकार: {MAX_UPLOAD_MB} MB.\nOTP, PIN या पासवर्ड न भेजें।\n"
        "अपलोड रोकने के लिए /cancel दबाएँ।",
        parse_mode=ParseMode.HTML)

async def payment_proof_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await handle_admin_file_upload(update, context):
        return
    register_customer(user)
    if context.user_data.get("awaiting_document"):
        await document_handler(update, context)
        return
    photo = update.message.photo[-1] if update.message.photo else None
    document = update.message.document
    if not photo and not document:
        return
    file_id = photo.file_id if photo else document.file_id
    file_size = photo.file_size if photo else document.file_size
    file_name = document.file_name if document else "payment-proof.jpg"
    mime = document.mime_type if document else "image/jpeg"
    if file_size and file_size > MAX_UPLOAD_MB * 1024 * 1024:
        await update.message.reply_text(f"फ़ाइल बहुत बड़ी है। अधिकतम {MAX_UPLOAD_MB} MB भेजें।")
        return
    with db() as c:
        pays = c.execute("""SELECT p.*,o.status AS order_status FROM payments p
            JOIN orders o ON o.order_code=p.order_code
            WHERE p.user_id=? AND p.status IN ('PENDING','PROOF_RECEIVED','DUPLICATE_FLAG')
            ORDER BY p.id DESC LIMIT 10""", (user.id,)).fetchall()
    if not pays:
        await update.message.reply_text("आपके लिए कोई लंबित Payment Reference नहीं मिला। /myorders देखें।")
        return
    if len(pays) > 1:
        buttons = [[InlineKeyboardButton(f"{p['payment_ref']} · {p['order_code']}", callback_data=f"attach_proof:{p['payment_ref']}")]
                   for p in pays[:8]]
        # Store the file ID server-side; Telegram callback_data has a strict 64-byte limit.
        context.user_data["pending_proof_file"] = file_id
        await update.message.reply_text("यह प्रमाण किस भुगतान के लिए है? सही Reference चुनें:",
                                        reply_markup=InlineKeyboardMarkup(buttons))
        return
    await attach_proof_to_payment(update, context, pays[0]["payment_ref"], file_id, mime, file_name)

async def attach_proof_to_payment(update, context, payment_ref: str, file_id: str, mime: str, file_name: str = ""):
    pay = get_payment(payment_ref)
    if not pay or pay["user_id"] != update.effective_user.id:
        await update.effective_message.reply_text("Payment Reference नहीं मिला।")
        return
    if pay["status"] in {"VERIFIED_BY_ADMIN", "AUTO_VERIFIED", "REJECTED_BY_ADMIN", "REVERSED_BY_ADMIN"}:
        await update.effective_message.reply_text("इस Payment Reference पर पहले ही निर्णय हो चुका है। नया भुगतान हो तो /myorders से नया reference लें।")
        return
    ocr_text = ""
    claimed_amount = None
    utr = ""
    if OCR_AVAILABLE and mime and mime.startswith("image/"):
        try:
            tgfile = await context.bot.get_file(file_id)
            raw = await tgfile.download_as_bytearray()
            ocr_text = extract_ocr(bytes(raw), file_name)
            claimed_amount = parse_amount_from_text(ocr_text)
            utr = parse_utr_from_text(ocr_text)
        except Exception:
            log.info("Payment proof OCR failed", exc_info=True)
    result = add_proof(payment_ref, file_id, mime, ocr_text, claimed_amount, utr)
    order = get_order(pay["order_code"])
    try:
        set_status(order["order_code"], "PAYMENT_REVIEW", update.effective_user.id, "Payment proof submitted")
    except ValueError:
        pass

    auto_result = {"verified": False, "provider": "", "provider_ref": "", "note": "manual_review"}
    if result == "OK" and utr and PAYMENT_AUTO_VERIFY_ENABLED:
        try:
            auto_result = await universal_try_verify(payment_ref, order, utr)
        except Exception as exc:
            log.warning("Universal payment verification failed (%s)", type(exc).__name__)
        if auto_result.get("verified"):
            try:
                applied = apply_auto_verified_payment(payment_ref, auto_result["provider"],
                                                      auto_result.get("provider_ref", ""), auto_result.get("note", ""))
            except Exception:
                log.exception("Atomic auto-verification update failed; leave for manual review")
                applied = False
            if not applied:
                auto_result["verified"] = False

    # Customer sees a generic receipt acknowledgment; OCR is never shown as proof.
    await update.effective_message.reply_text(
        f"✅ प्रमाण मिल गया। Reference: {payment_ref}\n⏳ भुगतान की स्थिति जल्द अपडेट होगी।")
    if result == "DUPLICATE":
        summary = (f"⚠️ <b>Duplicate UTR flag</b>\nOrder: <code>{esc(pay['order_code'])}</code>\n"
                   f"Payment Ref: <code>{esc(payment_ref)}</code>\nUTR candidate: <code>{esc(utr)}</code>\n"
                   "इस payment को auto-verify नहीं किया गया। वास्तविक bank/provider record जाँचें।")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📦 ऑर्डर खोलें", callback_data=f"admin_order:{pay['order_code']}")]])
    elif auto_result.get("verified"):
        summary = (f"🤖 <b>Payment auto-verified</b>\nProvider: <code>{esc(auto_result['provider'])}</code>\n"
                   f"Provider ref: <code>{esc(auto_result.get('provider_ref') or 'N/A')}</code>\n"
                   f"Order: <code>{esc(pay['order_code'])}</code> · Payment: <code>{esc(payment_ref)}</code>\n"
                   "सत्यापन provider API के exact UTR + paid status + amount + currency match से हुआ।")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚠️ Reverse auto-verification", callback_data=f"payunverify:{payment_ref}")],
            [InlineKeyboardButton("📦 ऑर्डर खोलें", callback_data=f"admin_order:{pay['order_code']}")],
        ])
    else:
        summary = (f"💳 <b>Payment Proof Review</b>\nOrder: <code>{esc(pay['order_code'])}</code>\n"
                   f"Payment Ref: <code>{esc(payment_ref)}</code>\nExpected: {money(pay['expected_amount'])}\n"
                   f"OCR amount (unverified): {money(claimed_amount) if claimed_amount is not None else 'Not detected'}\n"
                   f"OCR UTR candidate: <code>{esc(utr or 'Not detected')}</code>\n"
                   f"Auto-check: <code>{esc(auto_result.get('note') or 'manual_review')}</code>\n"
                   "⚠️ OCR/screenshot is not proof of settlement. Verify using official bank/provider records.")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ भुगतान सत्यापित", callback_data=f"payapprove:{payment_ref}"),
             InlineKeyboardButton("❌ अस्वीकृत", callback_data=f"payreject:{payment_ref}")],
            [InlineKeyboardButton("🟡 और प्रमाण माँगें", callback_data=f"paymore:{payment_ref}")],
            [InlineKeyboardButton("📦 ऑर्डर खोलें", callback_data=f"admin_order:{pay['order_code']}")],
        ])
    await notify_admins(context, summary, reply_markup=kb)
    if ADMIN_ALERT_CHAT_ID:
        try:
            if mime.startswith("image/"):
                await context.bot.send_photo(ADMIN_ALERT_CHAT_ID, file_id, caption=f"Proof for {pay['order_code']} / {payment_ref}")
            else:
                await context.bot.send_document(ADMIN_ALERT_CHAT_ID, file_id, caption=f"Proof for {pay['order_code']} / {payment_ref}")
        except Exception:
            log.exception("Could not forward payment proof")
    if auto_result.get("verified"):
        try:
            updated_order = get_order(pay["order_code"])
            customer = get_customer(pay["user_id"])
            receipt = create_receipt(updated_order, customer["full_name"] if customer else "Customer", payment_ref)
            if receipt:
                await context.bot.send_document(pay["user_id"], receipt, caption="🧾 भुगतान रिकॉर्ड रसीद")
        except Exception:
            log.exception("Auto-verify receipt failed")

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    code = context.user_data.get("upload_order_code")
    order = get_order(code) if code else None
    if not order or order["user_id"] != user.id:
        context.user_data.pop("awaiting_document", None)
        context.user_data.pop("upload_order_code", None)
        await msg.reply_text("कृपया पहले /myorders से ऑर्डर चुनें और दस्तावेज़ अपलोड करें।")
        return
    file_obj = msg.document or (msg.photo[-1] if msg.photo else None)
    if not file_obj:
        await msg.reply_text("कृपया PDF या इमेज फ़ाइल भेजें।")
        return
    size = getattr(file_obj, "file_size", None)
    if size and size > MAX_UPLOAD_MB * 1024 * 1024:
        await msg.reply_text(f"फ़ाइल अधिक बड़ी है। अधिकतम {MAX_UPLOAD_MB} MB.")
        return
    file_name = getattr(msg.document, "file_name", None) or "uploaded-image"
    mime = getattr(msg.document, "mime_type", None) or "image/jpeg"
    with db() as c:
        c.execute("""INSERT INTO documents(order_code,user_id,file_id,file_name,mime_type,file_size,created_at)
                     VALUES(?,?,?,?,?,?,?)""",
                  (code, user.id, file_obj.file_id, file_name[:250], mime, size, now_iso()))
    context.user_data.pop("awaiting_document", None)
    context.user_data.pop("upload_order_code", None)
    await msg.reply_text(f"✅ दस्तावेज़ ऑर्डर <code>{esc(code)}</code> से जोड़ दिया गया।",
                         parse_mode=ParseMode.HTML)
    await notify_admins(context,
        f"📄 <b>नया दस्तावेज़</b>\nOrder: <code>{esc(code)}</code>\n"
        f"ग्राहक: <code>{user.id}</code>\nफ़ाइल: {esc(file_name)}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 ऑर्डर खोलें", callback_data=f"admin_order:{code}")]]))
    if ADMIN_ALERT_CHAT_ID:
        try:
            if msg.photo:
                await context.bot.send_photo(ADMIN_ALERT_CHAT_ID, file_obj.file_id, caption=f"Document for {code}")
            elif msg.document:
                await context.bot.send_document(ADMIN_ALERT_CHAT_ID, file_obj.file_id, caption=f"Document for {code}")
        except Exception:
            log.exception("Document forwarding failed")

async def attach_proof_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":", 1)
    payment_ref = parts[1]
    file_id = context.user_data.get("pending_proof_file")
    pay = get_payment(payment_ref)
    if not pay or pay["user_id"] != q.from_user.id or not file_id:
        await q.edit_message_text("Payment Reference या फ़ाइल नहीं मिली।")
        return
    context.user_data.pop("pending_proof_file", None)
    # Callback only has Telegram file id; mime is inferred conservatively.
    await q.edit_message_text(f"प्रमाण {payment_ref} से जोड़ा जा रहा है…")
    class DummyMessage:
        effective_user = q.from_user
        effective_message = q.message
    # Do not fake Update internals; perform the safe DB operation and admin alert directly.
    ocr_text = ""
    claimed = None
    utr = ""
    result = add_proof(payment_ref, file_id, "image/unknown", ocr_text, claimed, utr)
    try:
        set_status(pay["order_code"], "PAYMENT_REVIEW", q.from_user.id, "Payment proof submitted")
    except ValueError:
        pass
    await safe_send(context.bot, q.from_user.id,
        f"प्रमाण मिल गया। Reference {payment_ref}. एडमिन वास्तविक भुगतान जाँचेगा।")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ भुगतान सत्यापित", callback_data=f"payapprove:{payment_ref}"),
         InlineKeyboardButton("❌ अस्वीकृत", callback_data=f"payreject:{payment_ref}")],
    ])
    await notify_admins(context,
        f"💳 Proof Review\nOrder: <code>{esc(pay['order_code'])}</code>\nPayment Ref: <code>{esc(payment_ref)}</code>\n"
        "⚠️ आधिकारिक बैंक/प्रदाता रिकॉर्ड से जाँचें।", reply_markup=kb)
    if ADMIN_ALERT_CHAT_ID:
        try:
            await context.bot.send_document(ADMIN_ALERT_CHAT_ID, file_id, caption=f"Proof for {pay['order_code']}")
        except Exception:
            pass

async def admin_order_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True)
        return
    await q.answer()
    code = q.data.split(":", 1)[1]
    order = get_order(code)
    if not order:
        await q.edit_message_text("ऑर्डर नहीं मिला।")
        return
    with db() as c:
        pays = c.execute("SELECT * FROM payments WHERE order_code=? ORDER BY id DESC LIMIT 3", (code,)).fetchall()
        docs = c.execute("SELECT * FROM documents WHERE order_code=? ORDER BY id DESC LIMIT 5", (code,)).fetchall()
    lines = [f"<b>🛠️ Admin Order</b> <code>{esc(code)}</code>",
             f"ग्राहक: <code>{order['user_id']}</code>",
             f"सर्विस: {esc(order['service_name'])}", f"राशि: {money(order['amount'])}",
             f"स्थिति: {esc(ORDER_STATUSES.get(order['status'], order['status']))}",
             f"विवरण: {esc(order['description'])}", f"Due: {esc(order['due_at'] or 'N/A')}"]
    for p in pays:
        lines.append(f"Payment: <code>{esc(p['payment_ref'])}</code> — {esc(p['status'])} — UTR {esc(p['utr'] or 'N/A')}")
    lines.append(f"दस्तावेज़: {len(docs)}")
    buttons = []
    # Payment approval is handled only by the payment-review controls, not a generic status button.
    if order["status"] in {"PAYMENT_PENDING", "PAYMENT_REVIEW"}:
        buttons.append([InlineKeyboardButton("💳 Review Payment", callback_data=f"admin_payment:{code}")])
    if order["status"] == "REQUESTED":
        buttons.append([InlineKeyboardButton("🔵 Start Manual Work", callback_data=f"status:{code}:IN_PROGRESS"),
                        InlineKeyboardButton("📄 Docs Needed", callback_data=f"status:{code}:DOCS_PENDING")])
    if order["status"] in {"PAID", "DOCS_PENDING", "WAITING_CUSTOMER", "NEEDS_ADMIN"}:
        buttons.append([InlineKeyboardButton("🔵 Start Work", callback_data=f"status:{code}:IN_PROGRESS"),
                        InlineKeyboardButton("📄 Docs Needed", callback_data=f"status:{code}:DOCS_PENDING")])
    if order["status"] in {"IN_PROGRESS", "WAITING_CUSTOMER", "NEEDS_ADMIN"}:
        buttons.append([InlineKeyboardButton("⏳ Wait Customer", callback_data=f"status:{code}:WAITING_CUSTOMER"),
                        InlineKeyboardButton("✅ Complete", callback_data=f"status:{code}:COMPLETED")])
    if order["status"] in {"PAID", "IN_PROGRESS", "NEEDS_ADMIN"}:
        buttons.append([InlineKeyboardButton("💰 Refund Pending", callback_data=f"status:{code}:REFUND_PENDING"),
                        InlineKeyboardButton("⚠️ Admin Attention", callback_data=f"status:{code}:NEEDS_ADMIN")])
    if order["status"] == "REFUND_PENDING":
        buttons.append([InlineKeyboardButton("↩️ Mark Refunded", callback_data=f"status:{code}:REFUNDED")])
    buttons.append([InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")])
    await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML,
                              reply_markup=InlineKeyboardMarkup(buttons))

async def admin_payment_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True)
        return
    await q.answer()
    code = q.data.split(":", 1)[1]
    with db() as c:
        pays = c.execute("SELECT * FROM payments WHERE order_code=? ORDER BY id DESC LIMIT 5", (code,)).fetchall()
    if not pays:
        await q.edit_message_text("इस ऑर्डर के लिए भुगतान रिकॉर्ड नहीं मिला।")
        return
    buttons = []
    for pay in pays:
        buttons.append([InlineKeyboardButton(
            f"{pay['payment_ref']} · {pay['status']}",
            callback_data=f"paydetails:{pay['payment_ref']}")])
    buttons.append([InlineKeyboardButton("⬅️ ऑर्डर खोलें", callback_data=f"admin_order:{code}")])
    await q.edit_message_text(f"<b>Payment records — {esc(code)}</b>", parse_mode=ParseMode.HTML,
                              reply_markup=InlineKeyboardMarkup(buttons))

async def payment_details_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True)
        return
    await q.answer()
    ref = q.data.split(":", 1)[1]
    pay = get_payment(ref)
    if not pay:
        await q.edit_message_text("Payment record नहीं मिला।")
        return
    if pay["status"] == "AUTO_VERIFIED":
        rows = [[InlineKeyboardButton("⚠️ Reverse auto-verification", callback_data=f"payunverify:{ref}")]]
    elif pay["status"] in {"VERIFIED_BY_ADMIN", "REJECTED_BY_ADMIN", "REVERSED_BY_ADMIN"}:
        rows = []
    else:
        rows = [
            [InlineKeyboardButton("✅ भुगतान सत्यापित", callback_data=f"payapprove:{ref}"),
             InlineKeyboardButton("❌ अस्वीकृत", callback_data=f"payreject:{ref}")],
            [InlineKeyboardButton("🟡 और प्रमाण माँगें", callback_data=f"paymore:{ref}")],
        ]
    rows.append([InlineKeyboardButton("⬅️ ऑर्डर खोलें", callback_data=f"admin_order:{pay['order_code']}")])
    kb = InlineKeyboardMarkup(rows)
    await q.edit_message_text(
        f"<b>Payment Review</b>\nOrder: <code>{esc(pay['order_code'])}</code>\n"
        f"Reference: <code>{esc(ref)}</code>\nExpected: {money(pay['expected_amount'])}\n"
        f"Claimed amount (OCR, unverified): {money(pay['claimed_amount']) if pay['claimed_amount'] is not None else 'Not detected'}\n"
        f"UTR candidate: <code>{esc(pay['utr'] or 'Not detected')}</code>\nStatus: {esc(pay['status'])}\n"
        f"Source: <code>{esc(pay['payment_source'] or 'manual/not recorded')}</code>\n"
        f"Provider ref: <code>{esc(pay['provider_ref'] or 'N/A')}</code>\n"
        f"Verification note: <code>{esc(pay['auto_verify_note'] or 'N/A')}</code>\n\n"
        "⚠️ वास्तविक बैंक/प्रदाता रिकॉर्ड से जाँचें; स्क्रीनशॉट/OCR अपने आप प्रमाण नहीं है।",
        parse_mode=ParseMode.HTML, reply_markup=kb)

async def change_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True)
        return
    await q.answer()
    _, code, status = q.data.split(":", 2)
    try:
        order = set_status(code, status, q.from_user.id, "Admin status change")
    except ValueError as e:
        await q.answer(str(e)[:180], show_alert=True)
        return
    await q.edit_message_text(
        f"✅ स्थिति अपडेट हुई\nOrder: <code>{esc(code)}</code>\n"
        f"नई स्थिति: {esc(ORDER_STATUSES[status])}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ ऑर्डर खोलें", callback_data=f"admin_order:{code}")]]))
    await safe_send(context.bot, order["user_id"],
        f"📦 आपके ऑर्डर <code>{esc(code)}</code> की स्थिति अपडेट हुई:\n<b>{esc(ORDER_STATUSES[status])}</b>",
        parse_mode=ParseMode.HTML)
    if status == "COMPLETED":
        # Award loyalty points once per order, based on recorded order value.
        marker = f"loyalty_awarded:{code}"
        with db() as c:
            already = c.execute("SELECT value FROM app_meta WHERE key=?", (marker,)).fetchone()
            if not already:
                points = max(0, (int(order["amount"]) // 100) * LOYALTY_POINTS_PER_100)
                if points:
                    c.execute("UPDATE customers SET loyalty_points=loyalty_points+? WHERE user_id=?",
                              (points, order["user_id"]))
                c.execute("INSERT OR IGNORE INTO app_meta(key,value) VALUES(?,?)", (marker, str(points)))
            else:
                points = int(already["value"])
        await safe_send(context.bot, order["user_id"],
            f"🎉 आपका काम पूरा हुआ। इस ऑर्डर से {points} लॉयल्टी पॉइंट मिले।\n"
            "रेटिंग देने के लिए नीचे विकल्प चुनें:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⭐1", callback_data=f"rate:{code}:1"),
                InlineKeyboardButton("⭐2", callback_data=f"rate:{code}:2"),
                InlineKeyboardButton("⭐3", callback_data=f"rate:{code}:3"),
                InlineKeyboardButton("⭐4", callback_data=f"rate:{code}:4"),
                InlineKeyboardButton("⭐5", callback_data=f"rate:{code}:5"),
            ]]))

async def payment_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True)
        return
    await q.answer()
    action, ref = q.data.split(":", 1)
    pay = get_payment(ref)
    if not pay:
        await q.edit_message_text("Payment Reference नहीं मिला।")
        return
    if action != "payunverify" and pay["status"] in {"AUTO_VERIFIED", "VERIFIED_BY_ADMIN", "REJECTED_BY_ADMIN", "REVERSED_BY_ADMIN"}:
        await q.edit_message_text("इस payment पर पहले ही निर्णय हो चुका है। जरूरत हो तो Owner/Admin से संपर्क करें।")
        return
    if action == "payunverify":
        if pay["status"] != "AUTO_VERIFIED":
            await q.edit_message_text("यह payment auto-verified स्थिति में नहीं है।")
            return
        reversed_pay = reverse_auto_verified_payment(ref, q.from_user.id)
        if not reversed_pay:
            await q.edit_message_text("यह auto-verification अब reverse नहीं हो सका; order/payment status जाँचें।")
            return
        await safe_send(context.bot, pay["user_id"],
            f"⚠️ आपके Order <code>{esc(pay['order_code'])}</code> के भुगतान की अतिरिक्त जाँच की जा रही है। कृपया एडमिन से संपर्क करें।",
            parse_mode=ParseMode.HTML)
        audit(q.from_user.id, "PAYMENT_AUTO_VERIFICATION_REVERSED", pay["order_code"], ref)
        await q.edit_message_text(f"⚠️ Auto-verification reverse किया गया: <code>{esc(ref)}</code>", parse_mode=ParseMode.HTML)
    elif action == "payapprove":
        # Explicit admin action is recorded. It must follow actual bank/provider verification.
        order = get_order(pay["order_code"])
        if order["status"] not in {"PAYMENT_REVIEW", "PAYMENT_PENDING", "NEEDS_ADMIN"}:
            await q.edit_message_text("यह ऑर्डर इस स्थिति में भुगतान सत्यापन के लिए उपलब्ध नहीं है।")
            return
        decided = apply_manual_payment_decision(ref, q.from_user.id, approve=True)
        if not decided:
            await q.edit_message_text("Payment/order status बदल चुका है या यह निर्णय उपलब्ध नहीं है।")
            return
        order = get_order(pay["order_code"])
        customer = get_customer(pay["user_id"])
        receipt = create_receipt(order, customer["full_name"] if customer else "Customer", ref)
        await safe_send(context.bot, pay["user_id"],
            f"🟢 भुगतान एडमिन द्वारा सत्यापित किया गया।\nOrder: <code>{esc(pay['order_code'])}</code>",
            parse_mode=ParseMode.HTML)
        if receipt:
            try:
                await context.bot.send_document(pay["user_id"], receipt, caption="🧾 ऑर्डर रसीद")
            except Exception:
                log.exception("Receipt send failed")
        audit(q.from_user.id, "PAYMENT_APPROVED", pay["order_code"], ref)
        await q.edit_message_text(f"🟢 भुगतान सत्यापित दर्ज किया गया: <code>{esc(ref)}</code>",
                                  parse_mode=ParseMode.HTML)
    elif action == "payreject":
        decided = apply_manual_payment_decision(ref, q.from_user.id, approve=False)
        if not decided:
            await q.edit_message_text("Payment/order status बदल चुका है या यह निर्णय उपलब्ध नहीं है।")
            return
        order = get_order(pay["order_code"])
        await safe_send(context.bot, pay["user_id"],
            f"❌ भुगतान प्रमाण स्वीकार नहीं हुआ। Order: <code>{esc(pay['order_code'])}</code>\n"
            "कृपया एडमिन से संपर्क करें; वास्तविक भुगतान हुआ हो तो नया प्रमाण दें।",
            parse_mode=ParseMode.HTML)
        audit(q.from_user.id, "PAYMENT_REJECTED", pay["order_code"], ref)
        await q.edit_message_text(f"❌ प्रमाण अस्वीकृत दर्ज हुआ: <code>{esc(ref)}</code>", parse_mode=ParseMode.HTML)
    else:
        await safe_send(context.bot, pay["user_id"],
            f"🟡 Order <code>{esc(pay['order_code'])}</code> के लिए अतिरिक्त भुगतान प्रमाण चाहिए।",
            parse_mode=ParseMode.HTML)
        await q.edit_message_text("ग्राहक से अतिरिक्त प्रमाण माँगा गया।")

def _parse_pipe_args(raw: str, expected: int):
    parts = [part.strip() for part in (raw or "").split("|")]
    if len(parts) != expected or any(not part for part in parts):
        raise ValueError(f"कृपया {expected} भाग `|` से अलग करके भेजें।")
    return parts


def _period_start(period: str) -> str:
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "30d":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=7)
    return start.isoformat(timespec="seconds")


def business_pnl(period: str = "today") -> dict[str, Any]:
    period = period if period in {"today", "7d", "30d"} else "today"
    since = _period_start(period)
    with db() as c:
        # Sum each order only once, even if a customer generated multiple payment references.
        revenue = c.execute("""SELECT COALESCE(SUM(o.amount),0) total FROM orders o
            JOIN (SELECT order_code, MAX(reviewed_at) reviewed_at FROM payments
                  WHERE status IN ('VERIFIED_BY_ADMIN','AUTO_VERIFIED') AND reviewed_at IS NOT NULL GROUP BY order_code) p
              ON p.order_code=o.order_code WHERE p.reviewed_at>=?""", (since,)).fetchone()["total"]
        expenses = c.execute("SELECT COALESCE(SUM(amount),0) total FROM expenses WHERE created_at>=?", (since,)).fetchone()["total"]
        orders = c.execute("SELECT COUNT(*) n FROM orders WHERE created_at>=?", (since,)).fetchone()["n"]
        completed = c.execute("SELECT COUNT(*) n FROM orders WHERE created_at>=? AND status='COMPLETED'", (since,)).fetchone()["n"]
        pending = c.execute("""SELECT COUNT(*) n FROM orders WHERE status NOT IN
            ('COMPLETED','CANCELLED','REFUNDED','REJECTED')""").fetchone()["n"]
        exp_rows = c.execute("SELECT category, SUM(amount) total FROM expenses WHERE created_at>=? GROUP BY category ORDER BY total DESC LIMIT 5", (since,)).fetchall()
    return {"period": period, "since": since, "revenue": int(revenue or 0), "expenses": int(expenses or 0),
            "net": int(revenue or 0)-int(expenses or 0), "orders": int(orders or 0),
            "completed": int(completed or 0), "pending": int(pending or 0), "expense_categories": exp_rows}


async def business_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True)
        return
    await q.answer()
    text = (
        "🏪 <b>Business OS — बिना किसी बाहरी API के</b>\n\n"
        "📦 <code>/stock</code> — स्टॉक सूची और कम स्टॉक अलर्ट\n"
        "➕ <code>/stockadd नाम|मात्रा|यूनिट|लो-स्टॉक-सीमा|प्रति-यूनिट-लागत</code>\n"
        "➖ <code>/stockuse नाम|मात्रा|कारण</code> — स्टॉक घटाएँ\n"
        "💸 <code>/expense राशि|कैटेगरी|विवरण</code> — खर्च दर्ज करें\n"
        "🧾 <code>/expenses</code> या <code>/expenses 7d</code> — खर्च इतिहास\n"
        "📊 <code>/pnl today</code>, <code>/pnl 7d</code>, <code>/pnl 30d</code>\n"
        "👥 <code>/crm</code> — ग्राहक और repeat-order insights\n"
        "⏱️ <code>/sla</code> — overdue और turnaround insights\n\n"
        "नोट: P&L में केवल एडमिन द्वारा सत्यापित भुगतान revenue माना जाता है। यह accounting summary है, audited financial statement नहीं।"
    )
    await q.edit_message_text(text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")]]))


async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("केवल अधिकृत एडमिन।"); return
    with db() as c:
        rows = c.execute("SELECT * FROM inventory_items ORDER BY (quantity<=low_stock_at) DESC, name COLLATE NOCASE LIMIT 60").fetchall()
        stock_value = c.execute("SELECT COALESCE(SUM(quantity*cost_per_unit),0) total FROM inventory_items").fetchone()["total"]
    if not rows:
        await update.effective_message.reply_text("अभी स्टॉक सूची खाली है। पहले /stockadd का उपयोग करें।"); return
    lines = [f"📦 <b>Inventory</b> · अनुमानित स्टॉक लागत {money(stock_value)}"]
    for r in rows:
        flag = " ⚠️ LOW" if float(r["quantity"]) <= float(r["low_stock_at"]) else ""
        lines.append(f"• <b>{esc(r['name'])}</b>: {r['quantity']:g} {esc(r['unit'])}{flag} · सीमा {r['low_stock_at']:g}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def stockadd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.effective_message.reply_text("केवल अधिकृत एडमिन।"); return
    try:
        name, qty_raw, unit, low_raw, cost_raw = _parse_pipe_args(" ".join(context.args), 5)
        qty, low, cost = float(qty_raw), float(low_raw), float(cost_raw)
        if not name or len(name) > 100 or qty < 0 or low < 0 or cost < 0 or max(qty, low, cost) > 1_000_000_000:
            raise ValueError("मात्रा, सीमा और लागत non-negative तथा उचित सीमा में हों।")
    except ValueError as e:
        await update.effective_message.reply_text(f"फॉर्मेट: /stockadd नाम|मात्रा|यूनिट|लो-स्टॉक-सीमा|प्रति-यूनिट-लागत\nउदाहरण: /stockadd A4 Paper|10|ream|2|250\n{esc(e)}", parse_mode=ParseMode.HTML); return
    with db() as c:
        old = c.execute("SELECT * FROM inventory_items WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if old:
            c.execute("UPDATE inventory_items SET quantity=quantity+?,unit=?,low_stock_at=?,cost_per_unit=?,updated_at=? WHERE id=?",
                      (qty, unit[:20], low, cost, now_iso(), old["id"]))
            item_id = old["id"]
        else:
            c.execute("INSERT INTO inventory_items(name,quantity,unit,low_stock_at,cost_per_unit,updated_at) VALUES(?,?,?,?,?,?)",
                      (name, qty, unit[:20], low, cost, now_iso()))
            item_id = c.execute("SELECT id FROM inventory_items WHERE name=? COLLATE NOCASE", (name,)).fetchone()["id"]
        c.execute("INSERT INTO inventory_movements(item_id,movement_type,quantity,note,actor_id,created_at) VALUES(?,?,?,?,?,?)",
                  (item_id, "ADD", qty, "Stock received/adjusted", user.id, now_iso()))
        current = c.execute("SELECT quantity,low_stock_at,unit FROM inventory_items WHERE id=?", (item_id,)).fetchone()
    audit(user.id, "INVENTORY_STOCK_ADDED", name, f"qty={qty}; current={current['quantity']}")
    await update.effective_message.reply_text(f"✅ {esc(name)} अपडेट हुआ। कुल स्टॉक: {current['quantity']:g} {esc(current['unit'])}", parse_mode=ParseMode.HTML)
    if float(current["quantity"]) <= float(current["low_stock_at"]):
        await notify_admins(context, f"⚠️ <b>Low Stock Alert</b>\n{esc(name)}: {current['quantity']:g} {esc(current['unit'])} (सीमा {current['low_stock_at']:g})")


async def stockuse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.effective_message.reply_text("केवल अधिकृत एडमिन।"); return
    try:
        name, qty_raw, note = _parse_pipe_args(" ".join(context.args), 3)
        qty = float(qty_raw)
        if qty <= 0 or qty > 1_000_000_000: raise ValueError("मात्रा शून्य से बड़ी होनी चाहिए।")
    except ValueError as e:
        await update.effective_message.reply_text(f"फॉर्मेट: /stockuse नाम|मात्रा|कारण\nउदाहरण: /stockuse A4 Paper|1|Print orders\n{esc(e)}", parse_mode=ParseMode.HTML); return
    with db() as c:
        item = c.execute("SELECT * FROM inventory_items WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if not item:
            await update.effective_message.reply_text("यह स्टॉक आइटम नहीं मिला। /stock देखें।"); return
        if float(item["quantity"]) < qty:
            await update.effective_message.reply_text(f"स्टॉक पर्याप्त नहीं। उपलब्ध: {item['quantity']:g} {esc(item['unit'])}", parse_mode=ParseMode.HTML); return
        c.execute("UPDATE inventory_items SET quantity=quantity-?,updated_at=? WHERE id=?", (qty, now_iso(), item["id"]))
        c.execute("INSERT INTO inventory_movements(item_id,movement_type,quantity,note,actor_id,created_at) VALUES(?,?,?,?,?,?)",
                  (item["id"], "USE", qty, note[:250], user.id, now_iso()))
        current = c.execute("SELECT quantity,low_stock_at,unit FROM inventory_items WHERE id=?", (item["id"],)).fetchone()
    audit(user.id, "INVENTORY_STOCK_USED", name, f"qty={qty}; note={note[:100]}; remaining={current['quantity']}")
    await update.effective_message.reply_text(f"✅ {esc(name)} से {qty:g} {esc(current['unit'])} घटाया। शेष: {current['quantity']:g}", parse_mode=ParseMode.HTML)
    if float(current["quantity"]) <= float(current["low_stock_at"]):
        await notify_admins(context, f"⚠️ <b>Low Stock Alert</b>\n{esc(name)}: {current['quantity']:g} {esc(current['unit'])} (सीमा {current['low_stock_at']:g})")


async def expense_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.effective_message.reply_text("केवल अधिकृत एडमिन।"); return
    try:
        amount_raw, category, note = _parse_pipe_args(" ".join(context.args), 3)
        amount = int(amount_raw.replace(",", ""))
        if amount <= 0 or amount > 100_000_000 or len(category) > 80: raise ValueError("राशि 1 से 100000000 रुपये के बीच होनी चाहिए।")
    except ValueError as e:
        await update.effective_message.reply_text(f"फॉर्मेट: /expense राशि|कैटेगरी|विवरण\nउदाहरण: /expense 350|Paper|A4 paper purchase\n{esc(e)}", parse_mode=ParseMode.HTML); return
    with db() as c:
        cur = c.execute("INSERT INTO expenses(amount,category,note,actor_id,created_at) VALUES(?,?,?,?,?)",
                        (amount, category[:80], note[:500], user.id, now_iso()))
        expense_id = cur.lastrowid
    audit(user.id, "EXPENSE_RECORDED", str(expense_id), f"amount={amount}; category={category[:80]}")
    await update.effective_message.reply_text(f"✅ खर्च दर्ज हुआ: {money(amount)} · {esc(category)}", parse_mode=ParseMode.HTML)


async def expenses_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("केवल अधिकृत एडमिन।"); return
    days = 7 if context.args and context.args[0] == "7d" else 30
    since = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat(timespec="seconds")
    with db() as c:
        rows = c.execute("SELECT * FROM expenses WHERE created_at>=? ORDER BY id DESC LIMIT 15", (since,)).fetchall()
        total = c.execute("SELECT COALESCE(SUM(amount),0) total FROM expenses WHERE created_at>=?", (since,)).fetchone()["total"]
    lines = [f"🧾 <b>खर्च इतिहास ({days} दिन)</b> · कुल {money(total)}"]
    for r in rows:
        lines.append(f"• {esc(r['created_at'][:16])} · {money(r['amount'])} · {esc(r['category'])}\n  {esc(r['note'])}")
    await update.effective_message.reply_text("\n".join(lines) if rows else "इस अवधि में खर्च दर्ज नहीं है।", parse_mode=ParseMode.HTML)


async def pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("केवल अधिकृत एडमिन।"); return
    period = context.args[0].lower() if context.args else "today"
    if period not in {"today", "7d", "30d"}:
        await update.effective_message.reply_text("उपयोग: /pnl today या /pnl 7d या /pnl 30d"); return
    data = business_pnl(period)
    label = {"today":"आज (UTC)","7d":"पिछले 7 दिन","30d":"पिछले 30 दिन"}[period]
    lines = [f"📊 <b>Business P&L · {label}</b>",
             f"सत्यापित भुगतान: <b>{money(data['revenue'])}</b>",
             f"दर्ज खर्च: <b>{money(data['expenses'])}</b>",
             f"ऑपरेटिंग अंतर (साधारण): <b>{money(data['net'])}</b>",
             f"नए ऑर्डर: {data['orders']} · पूरे: {data['completed']} · अभी लंबित: {data['pending']}",
             "\n<i>इसमें दर्ज न किए गए खर्च, टैक्स, रिफंड/chargeback और अन्य accounting adjustments शामिल नहीं हैं।</i>"]
    if data["expense_categories"]:
        lines.append("\n<b>खर्च की प्रमुख कैटेगरी</b>")
        lines.extend(f"• {esc(r['category'])}: {money(r['total'])}" for r in data["expense_categories"])
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def crm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("केवल अधिकृत एडमिन।"); return
    since30 = (datetime.now(timezone.utc)-timedelta(days=30)).isoformat(timespec="seconds")
    since90 = (datetime.now(timezone.utc)-timedelta(days=90)).isoformat(timespec="seconds")
    with db() as c:
        customers = c.execute("SELECT COUNT(*) n FROM customers").fetchone()["n"]
        new30 = c.execute("SELECT COUNT(*) n FROM customers WHERE created_at>=?", (since30,)).fetchone()["n"]
        repeat = c.execute("SELECT COUNT(*) n FROM (SELECT user_id FROM orders GROUP BY user_id HAVING COUNT(*)>=2)").fetchone()["n"]
        dormant = c.execute("SELECT COUNT(*) n FROM customers cu WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id=cu.user_id AND o.created_at>=?)", (since30,)).fetchone()["n"]
        top = c.execute("SELECT cu.user_id,cu.full_name,COUNT(o.id) order_count,COALESCE(SUM(CASE WHEN o.status='COMPLETED' THEN o.amount ELSE 0 END),0) completed_value FROM customers cu JOIN orders o ON o.user_id=cu.user_id WHERE o.created_at>=? GROUP BY cu.user_id,cu.full_name ORDER BY order_count DESC,completed_value DESC LIMIT 5", (since90,)).fetchall()
    lines = ["👥 <b>Customer CRM Insights</b>", f"कुल ग्राहक: {customers}", f"पिछले 30 दिन में नए ग्राहक: {new30}", f"Repeat-order ग्राहक: {repeat}", f"30 दिन से कोई ऑर्डर नहीं: {dormant}", "\n<b>पिछले 90 दिन के सक्रिय ग्राहक</b>"]
    lines.extend(f"• {esc(r['full_name'])} · ID <code>{r['user_id']}</code> · {r['order_count']} ऑर्डर · पूरे काम की सूचीबद्ध राशि {money(r['completed_value'])}" for r in top)
    if not top: lines.append("अभी पर्याप्त ऑर्डर डेटा नहीं है।")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def sla_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("केवल अधिकृत एडमिन।"); return
    now = now_iso()
    with db() as c:
        overdue = c.execute("SELECT COUNT(*) n FROM orders WHERE due_at IS NOT NULL AND due_at<? AND status NOT IN ('COMPLETED','CANCELLED','REFUNDED','REJECTED')", (now,)).fetchone()["n"]
        open_orders = c.execute("SELECT COUNT(*) n FROM orders WHERE status NOT IN ('COMPLETED','CANCELLED','REFUNDED','REJECTED')").fetchone()["n"]
        completed = c.execute("""SELECT COUNT(*) n, AVG((julianday(e.created_at)-julianday(o.created_at))*24.0) avg_hours
            FROM orders o JOIN order_events e ON e.order_code=o.order_code AND e.new_status='COMPLETED'
            WHERE e.created_at>=?""", ((datetime.now(timezone.utc)-timedelta(days=30)).isoformat(timespec="seconds"),)).fetchone()
        rows = c.execute("SELECT order_code,service_name,status,due_at FROM orders WHERE due_at IS NOT NULL AND due_at<? AND status NOT IN ('COMPLETED','CANCELLED','REFUNDED','REJECTED') ORDER BY due_at LIMIT 8", (now,)).fetchall()
    avg = completed["avg_hours"]
    lines = ["⏱️ <b>SLA & Turnaround</b>", f"खुले ऑर्डर: {open_orders}", f"Overdue: {overdue}", f"पिछले 30 दिन में पूरे हुए: {completed['n']}", f"औसत turnaround: {f'{avg:.1f} घंटे' if avg is not None else 'अभी डेटा नहीं'}", "\n<b>सबसे पुराने overdue</b>"]
    lines.extend(f"• <code>{esc(r['order_code'])}</code> · {esc(r['service_name'])}\n  {esc(ORDER_STATUSES.get(r['status'],r['status']))} · Due {esc((r['due_at'] or '')[:16])}" for r in rows)
    if not rows: lines.append("कोई overdue ऑर्डर नहीं।")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    await update.effective_message.reply_text(
        f"आपका Telegram numeric user ID: <code>{user.id}</code>\n\n"
        "इसे GitHub Secrets में OWNER_USER_IDS और ADMIN_USER_IDS के लिए इस्तेमाल करें। "
        "इसे सार्वजनिक पोस्ट में साझा न करें; यह पासवर्ड नहीं है, लेकिन access setup में काम आता है।",
        parse_mode=ParseMode.HTML)

async def setup_checklist_text() -> str:
    active_services = [(cat_id, svc) for cat_id, svc in all_services() if svc.get("active", True)]
    checks = [
        (bool(PAYEE_NAME and PAYEE_NAME != "Digital Service Centre"), "दुकान का नाम", " /setup से सेट करें"),
        (bool(UPI_ID), "UPI ID", " /setup से सेट करें; UPI नहीं लेते तो भुगतान निर्देश स्पष्ट करें"),
        (bool(active_services), "कम-से-कम एक चालू सर्विस", " /admin → Service Manager से जोड़ें/चालू करें"),
        (bool(OWNER_USER_IDS), "Owner Telegram ID", " GitHub Secrets में OWNER_USER_IDS सेट करें"),
        (bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN), "Turso database connection", " GitHub Secrets में URL और token सेट करें"),
    ]
    lines = ["🧭 <b>दुकान शुरू करने की चेकलिस्ट</b>", "हर काम के लिए नीचे आसान निर्देश हैं:"]
    for ok, label, hint in checks:
        lines.append(("✅ " + label) if ok else ("⬜ " + label + " —" + hint))
    lines += ["", f"चालू सर्विस: {len(active_services)}", f"दुकान का नाम: {esc(PAYEE_NAME)}",
              f"UPI: {esc(UPI_ID or 'सेट नहीं')}", "",
              "पहले /setup चलाएँ, फिर /admin में फीस और दस्तावेज़ जाँचें। ग्राहक ऑर्डर करने से पहले एक टेस्ट ऑर्डर ज़रूर करें।"]
    return "\n".join(lines)

async def setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.effective_message.reply_text("यह सेटअप सिर्फ अधिकृत Owner/Admin कर सकते हैं। पहले GitHub Secrets में OWNER_USER_IDS या ADMIN_USER_IDS सेट होना चाहिए।")
        return
    context.user_data["admin_flow"] = "setup_shop_name"
    context.user_data.pop("admin_setting_key", None)
    await update.effective_message.reply_text("🧭 <b>पहली बार दुकान सेटअप — 1/4</b>\n\nमैं आपसे एक-एक करके 4 आसान बातें पूछूँगा। कोड लिखने की जरूरत नहीं।\n<b>1. दुकान का नाम क्या है?</b>\nउदाहरण: Rakesh Digital Seva Kendra\n\nबीच में रोकना हो तो /cancel लिखें।", parse_mode=ParseMode.HTML)

async def checksetup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("यह चेकलिस्ट सिर्फ अधिकृत दुकान Owner/Admin के लिए है।")
        return
    await update.effective_message.reply_text(await setup_checklist_text(), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧭 सेटअप शुरू करें", callback_data="setup_wizard")],
                                           [InlineKeyboardButton("🧰 दुकान/फीस सेटिंग", callback_data="admin_manage_services")]]))

async def setup_wizard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    context.user_data["admin_flow"] = "setup_shop_name"
    context.user_data.pop("admin_setting_key", None)
    await q.edit_message_text("🧭 <b>पहली बार दुकान सेटअप — 1/4</b>\n\nदुकान का नाम भेजें।\nउदाहरण: Rakesh Digital Seva Kendra\nबीच में रोकने के लिए /cancel लिखें।", parse_mode=ParseMode.HTML)

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        if update.callback_query:
            await update.callback_query.answer("अनुमति नहीं है", show_alert=True)
        else:
            await update.effective_message.reply_text("यह कमांड केवल अधिकृत एडमिन के लिए है।")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧰 सर्विस/फीस/दस्तावेज़ मैनेज करें", callback_data="admin_manage_services")],
        [InlineKeyboardButton("📦 Pending Orders", callback_data="admin_list:PENDING"),
         InlineKeyboardButton("📊 आज की रिपोर्ट", callback_data="admin_report:today")],
        [InlineKeyboardButton("⏰ Overdue", callback_data="admin_list:OVERDUE"),
         InlineKeyboardButton("📈 7 दिन की रिपोर्ट", callback_data="admin_report:7d")],
        [InlineKeyboardButton("🧾 हाल के ऑर्डर", callback_data="admin_list:RECENT"),
         InlineKeyboardButton("🛡️ Security Log", callback_data="admin_security")],
        [InlineKeyboardButton("🏪 Business OS: Stock · Expense · P&L · CRM · SLA", callback_data="admin_biz_menu")],
        [InlineKeyboardButton("🧭 पहली बार दुकान सेटअप / चेकलिस्ट", callback_data="setup_wizard")],
    ])
    text = "🛠️ <b>Admin Control Centre</b>\nसर्विस, फीस, दस्तावेज़ और सेटिंग Telegram से बदलें—कोड लिखने की जरूरत नहीं।"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def admin_manage_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    await q.edit_message_text(
        "🧰 <b>Service Manager</b>\nयहाँ से सर्विस, कैटेगरी, फीस, आवश्यक दस्तावेज़, PDF/फोटो और दुकान सेटिंग बदलें।\n"
        f"Urgent फीस: {money(URGENT_FEE)}\nसमय सीमा: {DEFAULT_SLA_HOURS} घंटे\nUPI: {esc(UPI_ID or 'सेट नहीं')}",
        parse_mode=ParseMode.HTML, reply_markup=admin_manage_keyboard())

async def admin_add_service_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    rows = [[InlineKeyboardButton(str(cat.get("name", cat_id))[:40], callback_data=f"admin_svc_cat:{cat_id}")]
            for cat_id, cat in CATEGORIES.items()]
    rows.append([InlineKeyboardButton("➕ पहले नई कैटेगरी बनाएँ", callback_data="admin_add_category")])
    rows.append([InlineKeyboardButton("⬅️ वापस", callback_data="admin_manage_services")])
    await q.edit_message_text("नई सर्विस किस कैटेगरी में जोड़नी है?", reply_markup=InlineKeyboardMarkup(rows))

async def admin_add_category_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    context.user_data["admin_flow"] = "new_category_name"
    await q.edit_message_text("नई कैटेगरी का नाम भेजें (उदाहरण: 🧾 सरकारी फॉर्म सहायता)। /cancel से रद्द करें।")

async def admin_service_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    cat_id = q.data.split(":", 1)[1]
    if cat_id not in CATEGORIES:
        await q.answer("कैटेगरी नहीं मिली", show_alert=True); return
    await q.answer()
    context.user_data["admin_new_service_cat"] = cat_id
    context.user_data["admin_flow"] = "new_service_name"
    await q.edit_message_text("नई सर्विस का नाम भेजें।")

async def admin_fee_service_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    await q.edit_message_text("जिस सर्विस की फीस बदलनी है उसे चुनें:", reply_markup=service_picker("admin_fee_pick"))

async def admin_docs_text_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    await q.edit_message_text("जिस सर्विस के दस्तावेज़/निर्देश बदलने हैं उसे चुनें:", reply_markup=service_picker("admin_docs_pick"))

async def admin_doc_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    await q.edit_message_text("जिस सर्विस पर PDF/फोटो जोड़नी है उसे चुनें:", reply_markup=service_picker("admin_file_pick"))

async def admin_select_service_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    action, service_id = q.data.split(":", 1)
    cat_id, svc = get_service(service_id)
    if not svc:
        await q.edit_message_text("सर्विस नहीं मिली।"); return
    context.user_data["admin_target_service"] = service_id
    if action == "admin_fee_pick":
        context.user_data["admin_flow"] = "edit_service_fee"
        await q.edit_message_text(f"{esc(svc['name'])} की नई फीस रुपये में भेजें (0 भी मान्य है)। वर्तमान फीस: {money(svc['price'])}", parse_mode=ParseMode.HTML)
    elif action == "admin_docs_pick":
        context.user_data["admin_flow"] = "edit_service_docs"
        await q.edit_message_text(f"{esc(svc['name'])} के लिए नए आवश्यक दस्तावेज़/निर्देश भेजें।", parse_mode=ParseMode.HTML)
    else:
        context.user_data["admin_flow"] = "service_file"
        await q.edit_message_text(f"{esc(svc['name'])} के लिए PDF या फोटो अभी भेजें। अधिकतम 3 फाइलें रखी जाएँगी।", parse_mode=ParseMode.HTML)

async def admin_rename_service_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    await q.edit_message_text("जिस सर्विस का नाम बदलना है उसे चुनें:", reply_markup=service_picker("admin_rename_pick"))

async def admin_toggle_service_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    await q.edit_message_text("जिस सर्विस को चालू/बंद करना है उसे चुनें:", reply_markup=service_picker("admin_toggle_pick"))

async def admin_clear_files_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    await q.edit_message_text("जिस सर्विस की सभी संलग्न फाइलें हटानी हैं उसे चुनें:", reply_markup=service_picker("admin_clearfiles_pick"))

async def admin_service_extra_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    action, service_id = q.data.split(":", 1)
    _, svc = get_service(service_id)
    if not svc:
        await q.edit_message_text("सर्विस नहीं मिली।"); return
    if action == "admin_toggle_pick":
        svc["active"] = not svc.get("active", True)
        save_catalogue(); audit(q.from_user.id, "SERVICE_TOGGLED", service_id, str(svc["active"]))
        status = "चालू" if svc["active"] else "बंद"
        await q.edit_message_text(f"✅ {esc(svc['name'])} अब {status} है।", parse_mode=ParseMode.HTML,
                                  reply_markup=admin_manage_keyboard())
    elif action == "admin_clearfiles_pick":
        old_count = len(svc.get("files", []))
        svc["files"] = []
        save_catalogue(); audit(q.from_user.id, "SERVICE_FILES_CLEARED", service_id, str(old_count))
        await q.edit_message_text(f"✅ {esc(svc['name'])} से {old_count} संलग्न फ़ाइलें हटा दी गईं।", parse_mode=ParseMode.HTML,
                                  reply_markup=admin_manage_keyboard())
    else:
        context.user_data["admin_target_service"] = service_id
        context.user_data["admin_flow"] = "rename_service"
        await q.edit_message_text(f"{esc(svc['name'])} का नया नाम भेजें।", parse_mode=ParseMode.HTML)

async def admin_setting_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    key = {"admin_urgent_fee":"urgent_fee", "admin_set_upi":"upi_id", "admin_set_payee":"payee_name", "admin_set_sla":"default_sla_hours"}.get(q.data)
    if not key:
        await q.edit_message_text("सेटिंग नहीं मिली।"); return
    context.user_data["admin_setting_key"] = key
    context.user_data["admin_flow"] = "edit_setting"
    prompts = {
        "urgent_fee": f"नई Urgent फीस रुपये में भेजें। वर्तमान: {money(URGENT_FEE)}",
        "upi_id": f"नया UPI ID भेजें। वर्तमान: {esc(UPI_ID or 'सेट नहीं')}",
        "payee_name": f"दुकान/पेयी नाम भेजें। वर्तमान: {esc(PAYEE_NAME)}",
        "default_sla_hours": f"डिफॉल्ट पूरा करने का समय घंटे में भेजें। वर्तमान: {DEFAULT_SLA_HOURS}",
    }
    await q.edit_message_text(prompts[key], parse_mode=ParseMode.HTML)

async def handle_admin_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not is_admin(user.id) or context.user_data.get("admin_flow") != "service_file":
        return False
    msg = update.effective_message
    obj = msg.document or (msg.photo[-1] if msg.photo else None)
    if not obj:
        await msg.reply_text("PDF या फोटो भेजें।"); return True
    if getattr(obj, "file_size", 0) and obj.file_size > MAX_UPLOAD_MB * 1024 * 1024:
        await msg.reply_text(f"फ़ाइल बड़ी है; अधिकतम {MAX_UPLOAD_MB} MB।"); return True
    service_id = context.user_data.get("admin_target_service")
    cat_id, svc = get_service(service_id or "")
    if not svc:
        context.user_data.pop("admin_flow", None)
        await msg.reply_text("सर्विस नहीं मिली; प्रक्रिया रद्द हुई।"); return True
    files = list(svc.get("files", []))
    if len(files) >= 3:
        await msg.reply_text("इस सर्विस पर पहले से 3 फाइलें हैं। पहले हटाने की सुविधा अभी उपलब्ध नहीं है।"); return True
    files.append({"file_id": obj.file_id, "kind": "photo" if msg.photo else "document",
                  "name": (getattr(msg.document, "file_name", None) or "Service guide")[:200]})
    svc["files"] = files
    save_catalogue()
    context.user_data.pop("admin_flow", None)
    context.user_data.pop("admin_target_service", None)
    audit(user.id, "SERVICE_FILE_ADDED", service_id, files[-1]["name"])
    await msg.reply_text(f"✅ फ़ाइल {esc(svc['name'])} से जोड़ दी गई। ग्राहक सर्विस खोलेंगे तो यह फ़ाइल भी भेजी जाएगी।", parse_mode=ParseMode.HTML,
                         reply_markup=admin_manage_keyboard())
    return True

async def admin_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True)
        return
    await q.answer()
    mode = q.data.split(":", 1)[1]
    with db() as c:
        if mode == "PENDING":
            rows = c.execute("""SELECT * FROM orders WHERE status IN
              ('PAYMENT_PENDING','PAYMENT_REVIEW','DOCS_PENDING','NEEDS_ADMIN','WAITING_CUSTOMER')
              ORDER BY updated_at LIMIT 20""").fetchall()
        elif mode == "OVERDUE":
            rows = c.execute("""SELECT * FROM orders WHERE due_at < ? AND status NOT IN
              ('COMPLETED','CANCELLED','REFUNDED','REJECTED') ORDER BY due_at LIMIT 20""", (now_iso(),)).fetchall()
        else:
            rows = c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 20").fetchall()
    if not rows:
        await q.edit_message_text("कोई रिकॉर्ड नहीं मिला।", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")]]))
        return
    lines = [f"<b>📋 {esc(mode)} — {len(rows)} तक</b>"]
    buttons = []
    for row in rows:
        lines.append(f"\n<code>{esc(row['order_code'])}</code> · {esc(row['service_name'])}\n"
                     f"{esc(ORDER_STATUSES.get(row['status'], row['status']))} · {money(row['amount'])}")
        buttons.append([InlineKeyboardButton(row["order_code"], callback_data=f"admin_order:{row['order_code']}")])
    buttons.append([InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")])
    await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))

async def admin_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True)
        return
    await q.answer()
    period = q.data.split(":", 1)[1]
    since = (datetime.now(timezone.utc) - timedelta(days=7 if period == "7d" else 1)).isoformat()
    with db() as c:
        total = c.execute("SELECT COUNT(*) n FROM orders WHERE created_at>=?", (since,)).fetchone()["n"]
        completed = c.execute("SELECT COUNT(*) n FROM orders WHERE created_at>=? AND status='COMPLETED'", (since,)).fetchone()["n"]
        pending = c.execute("""SELECT COUNT(*) n FROM orders WHERE status NOT IN
           ('COMPLETED','CANCELLED','REFUNDED','REJECTED')""").fetchone()["n"]
        verified = c.execute("""SELECT COALESCE(SUM(o.amount),0) total FROM orders o
           JOIN (SELECT order_code, MAX(reviewed_at) reviewed_at FROM payments
                 WHERE status IN ('VERIFIED_BY_ADMIN','AUTO_VERIFIED') AND reviewed_at IS NOT NULL GROUP BY order_code) p
             ON p.order_code=o.order_code WHERE p.reviewed_at>=?""",
           (since,)).fetchone()["total"]
        by_service = c.execute("""SELECT service_name,COUNT(*) n FROM orders WHERE created_at>=?
           GROUP BY service_name ORDER BY n DESC LIMIT 5""", (since,)).fetchall()
        avg_rating = c.execute("""SELECT AVG(rating) r FROM ratings WHERE created_at>=?""", (since,)).fetchone()["r"]
    lines = [f"<b>📊 रिपोर्ट ({'7 दिन' if period == '7d' else 'आज/हालिया'})</b>",
             f"नए ऑर्डर: <b>{total}</b>", f"पूरे हुए: <b>{completed}</b>",
             f"अभी लंबित: <b>{pending}</b>", f"सत्यापित भुगतान राशि: <b>{money(verified)}</b>",
             f"औसत रेटिंग: <b>{f'{avg_rating:.2f}/5' if avg_rating else 'N/A'}</b>",
             "\n<b>टॉप सर्विसेज</b>"]
    lines += [f"• {esc(r['service_name'])}: {r['n']}" for r in by_service] or ["कोई डेटा नहीं"]
    await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")]]))

async def admin_security_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_owner(q.from_user.id):
        await q.answer("केवल Owner को अनुमति है", show_alert=True)
        return
    await q.answer()
    with db() as c:
        rows = c.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 12").fetchall()
    lines = ["<b>🛡️ हाल के Audit Logs</b>"]
    for r in rows:
        lines.append(f"\n{esc(r['created_at'])}\n{esc(r['action'])} · actor <code>{esc(r['actor_id'])}</code>\n"
                     f"{esc(r['target'])} — {esc(r['details'])}")
    await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")]]))

async def rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, code, raw_rating = q.data.split(":", 2)
    rating = int(raw_rating)
    order = get_order(code)
    if not order or order["user_id"] != q.from_user.id or order["status"] != "COMPLETED" or not 1 <= rating <= 5:
        await q.edit_message_text("यह रेटिंग इस ऑर्डर के लिए उपलब्ध नहीं है।")
        return
    with db() as c:
        c.execute("INSERT INTO ratings(order_code,user_id,rating,created_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(order_code) DO UPDATE SET rating=excluded.rating,created_at=excluded.created_at",
                  (code, q.from_user.id, rating, now_iso()))
    audit(q.from_user.id, "RATING_SUBMITTED", code, str(rating))
    await q.edit_message_text(f"धन्यवाद! आपकी रेटिंग: {'⭐' * rating}")
    await notify_admins(context, f"⭐ नई रेटिंग: <code>{esc(code)}</code> — {'⭐' * rating}")

async def complaint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        context.user_data["awaiting_complaint"] = True
        await update.effective_message.reply_text("अपनी शिकायत लिखकर भेजें। /cancel से रोक सकते हैं।")
        return
    complaint_text = " ".join(context.args)[:2000]
    code = short_id("CMP")
    with db() as c:
        c.execute("INSERT INTO complaints(complaint_code,user_id,text,created_at,updated_at) VALUES(?,?,?,?,?)",
                  (code, user.id, complaint_text, now_iso(), now_iso()))
    await update.effective_message.reply_text(f"शिकायत दर्ज हुई: {code}")
    await notify_admins(context, f"🆘 <b>नई शिकायत</b>\nID: <code>{code}</code>\nग्राहक: <code>{user.id}</code>\n{esc(complaint_text)}")
    audit(user.id, "COMPLAINT_CREATED", code, complaint_text[:300])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not msg.text:
        return
    register_customer(user)
    text = msg.text.strip()
    flow = context.user_data.get("admin_flow")
    if flow and is_admin(user.id):
        if flow == "setup_shop_name":
            value = text.strip()[:120]
            if len(value) < 2:
                await msg.reply_text("दुकान का नाम कम-से-कम 2 अक्षरों का होना चाहिए। फिर से भेजें।"); return
            set_runtime_setting("payee_name", value)
            audit(user.id, "GUIDED_SETUP", "payee_name", value[:100])
            context.user_data["admin_flow"] = "setup_upi"
            await msg.reply_text("✅ दुकान का नाम सेव हो गया।\n\n<b>2/4 — UPI ID</b>\nअपनी दुकान की UPI ID भेजें (उदाहरण: shopname@bank)।\nअगर अभी UPI नहीं लेना है या बाद में सेट करेंगे, तो <code>-</code> भेजें।", parse_mode=ParseMode.HTML); return
        if flow == "setup_upi":
            value = text.strip()
            if value == "-":
                value = UPI_ID
            elif not re.match(r"^[A-Za-z0-9._-]{2,100}@[A-Za-z0-9.-]{2,100}$", value):
                await msg.reply_text("UPI ID का फॉर्मेट सही नहीं लग रहा। उदाहरण: shopname@bank — या छोड़ने के लिए - भेजें।"); return
            if value:
                set_runtime_setting("upi_id", value)
            context.user_data["admin_flow"] = "setup_urgent_fee"
            await msg.reply_text("✅ UPI सेटिंग सेव/स्किप हुई।\n\n<b>3/4 — Urgent फीस</b>\nजल्दी काम की अतिरिक्त फीस रुपये में भेजें। केवल सामान्य काम के लिए 0 भेजें।", parse_mode=ParseMode.HTML); return
        if flow == "setup_urgent_fee":
            try:
                number = int(text.replace(",", ""))
                if number < 0 or number > 1000000: raise ValueError
            except ValueError:
                await msg.reply_text("0 से 1000000 तक रुपये का पूरा नंबर भेजें। उदाहरण: 50"); return
            set_runtime_setting("urgent_fee", str(number))
            context.user_data["admin_flow"] = "setup_sla"
            await msg.reply_text("✅ Urgent फीस सेव हो गई।\n\n<b>4/4 — काम पूरा करने का लक्ष्य</b>\nसामान्यतः काम कितने घंटे में पूरा करने का लक्ष्य रखें? उदाहरण: 24", parse_mode=ParseMode.HTML); return
        if flow == "setup_sla":
            try:
                number = int(text)
                if number < 1 or number > 720: raise ValueError
            except ValueError:
                await msg.reply_text("1 से 720 घंटे के बीच पूरा नंबर भेजें। उदाहरण: 24"); return
            set_runtime_setting("default_sla_hours", str(number))
            audit(user.id, "GUIDED_SETUP_COMPLETED", "shop", PAYEE_NAME[:100])
            context.user_data.pop("admin_flow", None)
            await msg.reply_text("🎉 <b>बुनियादी सेटअप पूरा!</b>\n\n" + await setup_checklist_text() + "\n\nअगला कदम: /admin खोलें → Service Manager → अपनी सर्विस, फीस और जरूरी दस्तावेज़ जाँचें।", parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧰 सर्विस/फीस सेट करें", callback_data="admin_manage_services")],
                                                   [InlineKeyboardButton("📊 Admin Menu", callback_data="admin_menu")]])); return
        if flow == "new_category_name":
            name = text[:60].strip()
            if not name:
                await msg.reply_text("कैटेगरी का नाम खाली नहीं हो सकता।"); return
            cat_id = service_slug(name)
            suffix = 2
            base_id = cat_id
            while cat_id in CATEGORIES:
                cat_id = f"{base_id[:18]}_{suffix}"; suffix += 1
            CATEGORIES[cat_id] = {"name": name, "desc": "सेवा और सहायता", "services": []}
            save_catalogue(); context.user_data.pop("admin_flow", None)
            audit(user.id, "CATEGORY_CREATED", cat_id, name)
            await msg.reply_text(f"✅ कैटेगरी जोड़ दी: {esc(name)}", parse_mode=ParseMode.HTML,
                                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ इस कैटेगरी में सर्विस जोड़ें", callback_data=f"admin_svc_cat:{cat_id}")],
                                                                   [InlineKeyboardButton("Service Manager", callback_data="admin_manage_services")]]))
            return
        if flow == "new_service_name":
            name = text[:80].strip()
            if not name:
                await msg.reply_text("सर्विस नाम खाली नहीं हो सकता।"); return
            context.user_data["admin_new_service_name"] = name
            context.user_data["admin_flow"] = "new_service_fee"
            await msg.reply_text("इस सर्विस की फीस रुपये में भेजें (0 = एडमिन से कीमत तय होगी)।")
            return
        if flow == "new_service_fee":
            try:
                fee = int(text.replace(",", ""))
                if fee < 0 or fee > 10000000: raise ValueError
            except ValueError:
                await msg.reply_text("कृपया 0 से 10000000 के बीच पूरा रुपये का नंबर भेजें।"); return
            context.user_data["admin_new_service_fee"] = fee
            context.user_data["admin_flow"] = "new_service_docs"
            await msg.reply_text("आवश्यक दस्तावेज़/ग्राहक निर्देश भेजें। न हों तो '-' भेजें।")
            return
        if flow == "new_service_docs":
            cat_id = context.user_data.get("admin_new_service_cat")
            if cat_id not in CATEGORIES:
                context.user_data.pop("admin_flow", None); await msg.reply_text("कैटेगरी नहीं मिली; फिर से शुरू करें।"); return
            name = context.user_data.get("admin_new_service_name", "नई सर्विस")
            service_id = service_slug(name)
            used = {svc["id"] for _, svc in all_services()}
            base_id = service_id; suffix = 2
            while service_id in used:
                service_id = f"{base_id[:18]}_{suffix}"; suffix += 1
            CATEGORIES[cat_id]["services"].append({"id": service_id, "name": name,
                "price": int(context.user_data.get("admin_new_service_fee", 0)), "emoji": "🛠️",
                "docs": "दस्तावेज़ निर्देश उपलब्ध नहीं हैं।" if text == "-" else text[:1000],
                "active": True, "files": [], "contact_admin": int(context.user_data.get("admin_new_service_fee", 0)) == 0})
            save_catalogue(); audit(user.id, "SERVICE_CREATED", service_id, name)
            for k in ("admin_flow", "admin_new_service_cat", "admin_new_service_name", "admin_new_service_fee"):
                context.user_data.pop(k, None)
            await msg.reply_text(f"✅ नई सर्विस जोड़ दी गई।\nनाम: {esc(name)}\nफीस: {money(CATEGORIES[cat_id]['services'][-1]['price'])}",
                                 parse_mode=ParseMode.HTML, reply_markup=admin_manage_keyboard())
            return
        if flow == "rename_service":
            service_id = context.user_data.get("admin_target_service")
            _, svc = get_service(service_id or "")
            if not svc: await msg.reply_text("सर्विस नहीं मिली।"); return
            new_name = text[:80].strip()
            if not new_name: await msg.reply_text("नाम खाली नहीं हो सकता।"); return
            old_name = svc["name"]
            svc["name"] = new_name
            save_catalogue(); audit(user.id, "SERVICE_RENAMED", service_id, f"{old_name} -> {new_name}")
            context.user_data.pop("admin_flow", None); context.user_data.pop("admin_target_service", None)
            await msg.reply_text(f"✅ सर्विस नाम अपडेट हुआ: {esc(new_name)}", parse_mode=ParseMode.HTML,
                                 reply_markup=admin_manage_keyboard()); return
        if flow == "edit_service_fee":
            try:
                fee = int(text.replace(",", ""))
                if fee < 0 or fee > 10000000: raise ValueError
            except ValueError:
                await msg.reply_text("कृपया 0 से 10000000 के बीच पूरा रुपये का नंबर भेजें।"); return
            service_id = context.user_data.get("admin_target_service")
            _, svc = get_service(service_id or "")
            if not svc: await msg.reply_text("सर्विस नहीं मिली।"); return
            svc["price"] = fee
            svc["contact_admin"] = (fee == 0)
            save_catalogue(); audit(user.id, "SERVICE_FEE_CHANGED", service_id, str(fee))
            context.user_data.pop("admin_flow", None); context.user_data.pop("admin_target_service", None)
            await msg.reply_text(f"✅ {esc(svc['name'])} की नई फीस {money(fee)} सेव हो गई।", parse_mode=ParseMode.HTML,
                                 reply_markup=admin_manage_keyboard()); return
        if flow == "edit_service_docs":
            service_id = context.user_data.get("admin_target_service")
            _, svc = get_service(service_id or "")
            if not svc: await msg.reply_text("सर्विस नहीं मिली।"); return
            svc["docs"] = text[:1000]
            save_catalogue(); audit(user.id, "SERVICE_DOCS_CHANGED", service_id, text[:200])
            context.user_data.pop("admin_flow", None); context.user_data.pop("admin_target_service", None)
            await msg.reply_text(f"✅ {esc(svc['name'])} के दस्तावेज़ निर्देश अपडेट हुए।", parse_mode=ParseMode.HTML,
                                 reply_markup=admin_manage_keyboard()); return
        if flow == "edit_setting":
            key = context.user_data.get("admin_setting_key")
            if key in {"urgent_fee", "default_sla_hours"}:
                try:
                    number = int(text)
                    if number < (1 if key == "default_sla_hours" else 0) or number > 1000000: raise ValueError
                except ValueError:
                    await msg.reply_text("कृपया वैध पूरा नंबर भेजें।"); return
                value = str(number)
            else:
                value = text[:120].strip()
                if key == "upi_id" and value and not re.match(r"^[A-Za-z0-9._-]{2,100}@[A-Za-z0-9.-]{2,100}$", value):
                    await msg.reply_text("UPI ID का फॉर्मेट सही नहीं लग रहा। उदाहरण: name@bank"); return
                if not value:
                    await msg.reply_text("यह मान खाली नहीं हो सकता।"); return
            set_runtime_setting(key, value)
            audit(user.id, "SETTING_CHANGED", key, value[:100])
            context.user_data.pop("admin_flow", None); context.user_data.pop("admin_setting_key", None)
            await msg.reply_text("✅ सेटिंग Turso में सेव हो गई।", reply_markup=admin_manage_keyboard()); return
    if context.user_data.get("awaiting_complaint"):
        context.user_data.pop("awaiting_complaint", None)
        code = short_id("CMP")
        with db() as c:
            c.execute("INSERT INTO complaints(complaint_code,user_id,text,created_at,updated_at) VALUES(?,?,?,?,?)",
                      (code, user.id, text[:2000], now_iso(), now_iso()))
        await msg.reply_text(f"🆘 शिकायत दर्ज हुई: <code>{code}</code>", parse_mode=ParseMode.HTML)
        await notify_admins(context, f"🆘 <b>नई शिकायत</b>\nID: <code>{code}</code>\nग्राहक: <code>{user.id}</code>\n{esc(text[:1000])}")
        return
    if context.user_data.get("awaiting_custom_request"):
        context.user_data.pop("awaiting_custom_request", None)
        order = create_order(user.id, "custom_service", text, urgent=False)
        await msg.reply_text(f"✅ अनुरोध दर्ज हुआ। Order ID: <code>{order['order_code']}</code>\nएडमिन कीमत की पुष्टि करेगा।",
                             parse_mode=ParseMode.HTML)
        await notify_admins(context, f"📝 <b>कस्टम अनुरोध</b>\nOrder: <code>{order['order_code']}</code>\n"
                                      f"ग्राहक: <code>{user.id}</code>\nविवरण: {esc(text[:1000])}",
                             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ऑर्डर खोलें",
                                                         callback_data=f"admin_order:{order['order_code']}")]]))
        return
    lower = text.lower()
    if text in {"🛍️ सर्विस मेनू", "/menu"}:
        await msg.reply_text("👇 सर्विस चुनें:", reply_markup=main_keyboard())
    elif text in {"📦 मेरे ऑर्डर", "/myorders"}:
        await my_orders(update, context)
    elif text in {"🆘 मदद", "/help"}:
        await help_command(update, context)
    elif text in {"📞 संपर्क", "📞 संपर्क करें", "/contact"}:
        await msg.reply_text(f"📞 संपर्क: {esc(PAYEE_NAME)}\nUPI: <code>{esc(UPI_ID or 'अभी कॉन्फ़िगर नहीं')}</code>",
                             parse_mode=ParseMode.HTML)
    elif text in {"❌ रद्द करें", "/cancel"}:
        context.user_data.clear()
        await msg.reply_text("अस्थायी प्रक्रिया रद्द की गई। पहले से बने ऑर्डर रद्द नहीं हुए।", reply_markup=reply_keyboard())
    elif any(k in lower for k in ["पैन", "pan card", "pan card", "aadhaar", "आधार", "प्रिंट", "print", "स्कैन", "scan"]):
        # Rule-based assistant: no external AI dependency required.
        cat_id = "pan" if ("पैन" in lower or "pan" in lower) else "aadhaar" if ("आधार" in lower or "aadhaar" in lower) else "print"
        await msg.reply_text(f"आपके लिए यह कैटेगरी सही हो सकती है: {CATEGORIES[cat_id]['name']}",
                             reply_markup=category_keyboard(cat_id))
    elif lower in {"privacy", "privacy policy", "डेटा", "प्राइवेसी"}:
        await msg.reply_text("डेटा केवल ऑर्डर/सपोर्ट के लिए उपयोग करें। OTP, PIN या पासवर्ड न भेजें। /cancel से मौजूदा इनपुट प्रक्रिया रोक सकते हैं।")
    else:
        answer = await ai_faq_answer(text)
        await msg.reply_text(answer, reply_markup=main_keyboard())

async def ai_faq_answer(text: str) -> str:
    """Deterministic offline FAQ fallback; no AI or non-Telegram network calls."""
    lower = (text or "").strip().lower()
    if any(k in lower for k in ("price", "rate", "कीमत", "रेट", "दाम")):
        return ("💰 कीमत देखने के लिए 🛍️ सर्विस मेनू चुनें। कस्टम काम की कीमत एडमिन पुष्टि करेगा।\n"
                "भुगतान की पुष्टि बैंक/UPI ऐप में खुद जाँचें।")
    if any(k in lower for k in ("payment", "upi", "पेमेंट", "भुगतान", "पैसा")):
        return ("💳 भुगतान निर्देश ऑर्डर के दौरान मिलेंगे। स्क्रीनशॉट अपने आप भुगतान प्रमाण नहीं है; "
                "एडमिन वास्तविक ट्रांज़ैक्शन की जाँच करेगा।")
    if any(k in lower for k in ("status", "order", "स्टेटस", "ऑर्डर")):
        return "📦 अपना ऑर्डर देखने के लिए /myorders लिखें।"
    if any(k in lower for k in ("complaint", "शिकायत", "problem", "समस्या")):
        return "🆘 शिकायत दर्ज करने के लिए /complaint लिखें।"
    return ("मैं नियम-आधारित ऑफलाइन सहायता दे सकता हूँ। नीचे से सर्विस चुनें या /myorders से ऑर्डर देखें।\n"
            "अलग काम के लिए '📝 अन्य सेवा' चुनें। सुरक्षा के लिए OTP, PIN या पासवर्ड कभी न भेजें।")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>🆘 सहायता</b>\n/start — मुख्य मेनू\n/myorders — ऑर्डर ट्रैक करें\n"
        "/complaint — शिकायत दर्ज करें\n/admin — दुकान का कंट्रोल पैनल (अधिकृत एडमिन)\n"
        "/myid — अपना Telegram numeric ID देखें (access setup के लिए)\n"
        "/setup — पहली बार दुकान सेटअप, एक-एक सवाल के साथ\n/checksetup — क्या-क्या सेट करना बाकी है\n"
        "/guide — शुरुआत करने की आसान गाइड\n/paymentsetup — आसान payment gateway guide (Owner)\n/gatewaylist — configured API providers\n/cancel — चल रही प्रक्रिया रोकें\n"
        "/stock, /expense, /pnl, /crm, /sla — दुकान के कामकाज के टूल\n\n"
        "पेमेंट स्क्रीनशॉट अकेले भुगतान की पुष्टि नहीं है। OTP/PIN/पासवर्ड कभी न भेजें।"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())

async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🪜 <b>नई दुकान के लिए आसान शुरुआत</b>\n\n"
        "<b>पहला काम — मालिक की पहुँच</b>\n"
        "1. Telegram में @BotFather खोलकर नया bot बनाएँ और token लें।\n"
        "2. Turso में database बनाएँ और उसका URL + auth token रखें। Token किसी चैट/कोड में सार्वजनिक न करें।\n"
        "3. GitHub Secrets में पहले BOT_TOKEN, TURSO_DATABASE_URL और TURSO_AUTH_TOKEN जोड़ें; Actions टैब में Cyber Cafe Telegram Bot → Run workflow चलाएँ।\n"
        "4. Telegram में अपने bot को खोलकर /myid भेजें। मिले numeric ID को GitHub Secrets में OWNER_USER_IDS और ADMIN_USER_IDS के रूप में जोड़ें; फिर workflow दोबारा चलाएँ।\n\n"
        "<b>दूसरा काम — Telegram में दुकान तैयार करें</b>\n"
        "5. अपने bot को खोलकर /setup चलाएँ और चार सवालों के जवाब दें।\n"
        "6. /admin → Service Manager में सर्विस का नाम, फीस, जरूरी दस्तावेज़ और गाइड फाइल सेट करें। गलत/अनुपलब्ध सर्विस बंद रखें।\n"
        "7. /checksetup से बाकी काम देखें। दूसरे Telegram account से एक test order बनाकर पूरा flow जाँचें।\n\n"
        "<b>ज़रूरी सच:</b> GitHub Actions bot को 24 घंटे लगातार चालू रखने की गारंटी नहीं देता; scheduled run में gap हो सकता है। Payment auto-verification डिफ़ॉल्ट रूप से बंद है। UPI screenshot देखकर कभी अपने-आप paid न मानें। यह गाइड deployment को आसान करती है, लेकिन शुरुआती GitHub/Turso setup अभी भी एक बार करना पड़ेगा।"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧭 दुकान सेटअप शुरू करें", callback_data="setup_wizard")],
                                           [InlineKeyboardButton("✅ सेटअप चेकलिस्ट", callback_data="setup_checklist")],
                                           [InlineKeyboardButton("🛠️ Admin Menu", callback_data="admin_menu")]]))

async def setup_checklist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("अनुमति नहीं है", show_alert=True); return
    await q.answer()
    await q.edit_message_text(await setup_checklist_text(), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧭 सेटअप शुरू करें", callback_data="setup_wizard")],
                                           [InlineKeyboardButton("🧰 Service Manager", callback_data="admin_manage_services")],
                                           [InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")]]))

async def privacy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🔐 <b>डेटा और सुरक्षा</b>\n"
        "• डेटा का उपयोग ऑर्डर और ग्राहक सहायता के लिए किया जाता है।\n"
        "• OTP, PIN, पासवर्ड या बैंक लॉगिन विवरण न भेजें।\n"
        "• केवल जरूरी दस्तावेज़ भेजें।\n"
        "• निजी दस्तावेज़ों को सार्वजनिक GitHub रिपॉजिटरी में न रखें।\n"
        "• डेटा हटाने/सुधारने के अनुरोध के लिए एडमिन से संपर्क करें।",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 मुख्य मेनू", callback_data="back_main")]]))

async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(f"🏪 <b>{esc(PAYEE_NAME)}</b>\nसर्विस चुनें:", parse_mode=ParseMode.HTML,
                              reply_markup=main_keyboard())

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text("अस्थायी प्रक्रिया रद्द हुई। पहले से बने ऑर्डर नहीं हटे।",
                                               reply_markup=main_keyboard())

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_menu(update, context)

async def admin_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.effective_message.reply_text("केवल अधिकृत एडमिन।")
        return
    if len(context.args) < 2:
        await update.effective_message.reply_text("उपयोग: /setstatus ORDER-ID STATUS\nउदाहरण: /setstatus ORD-... IN_PROGRESS")
        return
    code, status = context.args[0].upper(), context.args[1].upper()
    try:
        order = set_status(code, status, user.id, "Admin command")
        await update.effective_message.reply_text(f"{code}: {ORDER_STATUSES[order['status']]}")
        await safe_send(context.bot, order["user_id"],
                        f"आपके ऑर्डर {code} की स्थिति: {ORDER_STATUSES[order['status']]}")
    except ValueError as e:
        await update.effective_message.reply_text(f"नहीं हुआ: {e}")

async def loyalty_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_customer(user)
    customer = get_customer(user.id)
    points = int(customer["loyalty_points"]) if customer else 0
    with db() as c:
        count = c.execute("SELECT COUNT(*) n FROM orders WHERE user_id=? AND status='COMPLETED'",
                          (user.id,)).fetchone()["n"]
    await update.effective_message.reply_text(
        f"⭐ <b>आपके लॉयल्टी पॉइंट</b>\nपॉइंट: <b>{points}</b>\nपूरे हुए ऑर्डर: <b>{count}</b>\n"
        "पॉइंट का कोई नकद मूल्य नहीं है; उपयोग/रिडेम्प्शन नीति एडमिन द्वारा घोषित होने पर लागू होगी।",
        parse_mode=ParseMode.HTML)

async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.effective_message.reply_text("केवल Owner के लिए।")
        return
    with db() as c:
        customers = c.execute("SELECT COUNT(*) n FROM customers").fetchone()["n"]
        orders = c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
        pending = c.execute("SELECT COUNT(*) n FROM notification_queue WHERE sent_at IS NULL").fetchone()["n"]
    await update.effective_message.reply_text(
        f"🟢 Bot process responding\nDB: Turso\nCustomers: {customers}\nOrders: {orders}\n"
        f"Queued notifications: {pending}\nLocal OCR installed: {OCR_AVAILABLE}\nExternal AI/API: disabled (Telegram only)")

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.effective_message.reply_text("केवल Owner के लिए।")
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"cyber_cafe_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.sqlite3"
    try:
        # Opening db() first syncs the embedded replica with Turso.
        with db():
            pass
        source = sqlite3.connect(DB_PATH)
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        await update.effective_message.reply_document(document=target.open("rb"), caption="Local export of the Turso replica; keep this backup private.")
        audit(update.effective_user.id, "BACKUP_CREATED", str(target))
    except Exception:
        log.exception("Backup failed")
        await update.effective_message.reply_text("Backup असफल हुआ। लॉग जाँचें।")

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    # Send reminders only to users with non-terminal orders; never change status automatically.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_SLA_HOURS)
    with db() as c:
        rows = c.execute("""SELECT * FROM orders WHERE due_at < ? AND status NOT IN
          ('COMPLETED','CANCELLED','REFUNDED','REJECTED') ORDER BY due_at LIMIT 20""",
          (cutoff.isoformat(),)).fetchall()
    for order in rows:
        # Avoid alert storms: only remind once per 24 hours.
        try:
            last = datetime.fromisoformat(order["last_notification"]) if order["last_notification"] else None
        except ValueError:
            last = None
        if last and datetime.now(timezone.utc) - last < timedelta(hours=24):
            continue
        await safe_send(context.bot, order["user_id"],
            f"⏰ आपका ऑर्डर <code>{esc(order['order_code'])}</code> अभी पूरा नहीं हुआ है। स्थिति: "
            f"{esc(ORDER_STATUSES[order['status']])}\nयदि सहायता चाहिए तो /complaint लिखें।",
            parse_mode=ParseMode.HTML)
        with db() as c:
            c.execute("UPDATE orders SET last_notification=?,updated_at=? WHERE order_code=?",
                      (now_iso(), now_iso(), order["order_code"]))
        await notify_admins(context,
            f"⏰ <b>Overdue Order</b>\n<code>{esc(order['order_code'])}</code>\n"
            f"Status: {esc(ORDER_STATUSES[order['status']])}\nDue: {esc(order['due_at'])}")

async def post_init(app: Application):
    init_db()
    load_runtime_settings()
    ensure_font()
    if app.job_queue:
        app.job_queue.run_repeating(reminder_job, interval=3600, first=60, name="overdue_reminders")
    log.info("Bot initialized. Turso + Telegram only; local OCR=%s; business modules=inventory, expenses, P&L, CRM, SLA", OCR_AVAILABLE)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled Telegram handler error", exc_info=context.error)
    try:
        if ADMIN_ALERT_CHAT_ID:
            await context.bot.send_message(ADMIN_ALERT_CHAT_ID,
                f"⚠️ Bot error: {esc(type(context.error).__name__)} — check private logs.")
    except Exception:
        pass

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("guide", guide_command))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("setup", setup_command))
    app.add_handler(CommandHandler("checksetup", checksetup_command))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("myorders", lambda u, c: my_orders(u, c)))
    app.add_handler(CommandHandler("complaint", complaint_command))
    app.add_handler(CommandHandler("loyalty", loyalty_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("setstatus", admin_status_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("biz", lambda u, c: u.effective_message.reply_text(
        "Business OS: /stock, /stockadd, /stockuse, /expense, /expenses, /pnl, /crm, /sla. Owner payment tools: /providers /addprovider /toggleprovider /delprovider /testprovider",
        parse_mode=ParseMode.HTML) if is_admin(u.effective_user.id) else u.effective_message.reply_text("केवल अधिकृत एडमिन।")))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("stockadd", stockadd_command))
    app.add_handler(CommandHandler("stockuse", stockuse_command))
    app.add_handler(CommandHandler("expense", expense_command))
    app.add_handler(CommandHandler("expenses", expenses_command))
    app.add_handler(CommandHandler("pnl", pnl_command))
    app.add_handler(CommandHandler("crm", crm_command))
    app.add_handler(CommandHandler("sla", sla_command))
    app.add_handler(CommandHandler("paymentsetup", paymentsetup_command))
    app.add_handler(CommandHandler("gatewaylist", providers_command))
    app.add_handler(CommandHandler("providers", providers_command))
    app.add_handler(CommandHandler("addprovider", addprovider_command))
    app.add_handler(CommandHandler("delprovider", delprovider_command))
    app.add_handler(CommandHandler("toggleprovider", toggleprovider_command))
    app.add_handler(CommandHandler("testprovider", testprovider_command))

    app.add_handler(CallbackQueryHandler(show_category, pattern=r"^cat_"))
    app.add_handler(CallbackQueryHandler(show_service, pattern=r"^service:"))
    app.add_handler(CallbackQueryHandler(toggle_urgent, pattern=r"^urgent:"))
    app.add_handler(CallbackQueryHandler(create_order_handler, pattern=r"^order:"))
    app.add_handler(CallbackQueryHandler(my_orders, pattern=r"^my_orders$"))
    app.add_handler(CallbackQueryHandler(order_detail, pattern=r"^order_detail:"))
    app.add_handler(CallbackQueryHandler(upload_docs_prompt, pattern=r"^upload_docs:"))
    app.add_handler(CallbackQueryHandler(attach_proof_callback, pattern=r"^attach_proof:"))
    app.add_handler(CallbackQueryHandler(admin_order_view, pattern=r"^admin_order:"))
    app.add_handler(CallbackQueryHandler(admin_payment_view, pattern=r"^admin_payment:"))
    app.add_handler(CallbackQueryHandler(payment_details_view, pattern=r"^paydetails:"))
    app.add_handler(CallbackQueryHandler(change_status_callback, pattern=r"^status:"))
    app.add_handler(CallbackQueryHandler(payment_decision, pattern=r"^(payapprove|payreject|paymore|payunverify):"))
    app.add_handler(CallbackQueryHandler(payment_gateway_callback, pattern=r"^paygw:"))
    app.add_handler(CallbackQueryHandler(setup_wizard_callback, pattern=r"^setup_wizard$"))
    app.add_handler(CallbackQueryHandler(setup_checklist_callback, pattern=r"^setup_checklist$"))
    app.add_handler(CallbackQueryHandler(business_menu_callback, pattern=r"^admin_biz_menu$"))
    app.add_handler(CallbackQueryHandler(admin_menu, pattern=r"^admin_menu$"))
    app.add_handler(CallbackQueryHandler(admin_manage_services, pattern=r"^admin_manage_services$"))
    app.add_handler(CallbackQueryHandler(admin_add_service_start, pattern=r"^admin_add_service$"))
    app.add_handler(CallbackQueryHandler(admin_add_category_start, pattern=r"^admin_add_category$"))
    app.add_handler(CallbackQueryHandler(admin_service_category, pattern=r"^admin_svc_cat:"))
    app.add_handler(CallbackQueryHandler(admin_fee_service_start, pattern=r"^admin_fee_service$"))
    app.add_handler(CallbackQueryHandler(admin_docs_text_start, pattern=r"^admin_docs_text$"))
    app.add_handler(CallbackQueryHandler(admin_doc_file_start, pattern=r"^admin_doc_file$"))
    app.add_handler(CallbackQueryHandler(admin_rename_service_start, pattern=r"^admin_rename_service$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_service_start, pattern=r"^admin_toggle_service$"))
    app.add_handler(CallbackQueryHandler(admin_clear_files_start, pattern=r"^admin_clear_files$"))
    app.add_handler(CallbackQueryHandler(admin_select_service_action, pattern=r"^admin_(fee_pick|docs_pick|file_pick):"))
    app.add_handler(CallbackQueryHandler(admin_service_extra_action, pattern=r"^admin_(rename_pick|toggle_pick|clearfiles_pick):"))
    app.add_handler(CallbackQueryHandler(admin_setting_start, pattern=r"^admin_(urgent_fee|set_upi|set_payee|set_sla)$"))
    app.add_handler(CallbackQueryHandler(admin_list_callback, pattern=r"^admin_list:"))
    app.add_handler(CallbackQueryHandler(admin_report_callback, pattern=r"^admin_report:"))
    app.add_handler(CallbackQueryHandler(admin_security_callback, pattern=r"^admin_security$"))
    app.add_handler(CallbackQueryHandler(rating_callback, pattern=r"^rate:"))
    app.add_handler(CallbackQueryHandler(privacy_callback, pattern=r"^privacy_info$"))
    app.add_handler(CallbackQueryHandler(back_main, pattern=r"^back_main$"))

    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, payment_proof_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    log.info("Starting polling bot")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)

if __name__ == "__main__":
    main()
