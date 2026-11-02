import os
import json
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from libsql_client import create_client_sync

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
TURSO_URL = os.getenv("TURSO_DATABASE_URL").replace("libsql://", "https://")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_USER_ID"))

PAGE_SIZE = 15          # एक पेज पर कितनी सेवाएं दिखें
CATS_PER_PAGE = 10      # एक पेज पर कितनी श्रेणियां दिखें
SEARCH_PER_PAGE = 10    # सर्च रिजल्ट एक पेज पर कितने दिखें


def get_db():
    return create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)


def trunc(s, n=45):
    return s if len(s) <= n else s[:n-3] + "..."


# ============ डेटाबेस सेटअप ============
def init_db():
    with get_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, price INTEGER, docs TEXT,
            is_active INTEGER DEFAULT 1
        )""")
        try: db.execute("ALTER TABLE services ADD COLUMN is_active INTEGER DEFAULT 1")
        except: pass
        try: db.execute("ALTER TABLE services ADD COLUMN category_id INTEGER")
        except: pass
        try: db.execute("UPDATE services SET is_active = 1 WHERE is_active IS NULL")
        except: pass
        db.execute("""CREATE TABLE IF NOT EXISTS admin_state (
            admin_id INTEGER PRIMARY KEY, step TEXT, temp_data TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT, username TEXT, last_seen TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS user_state (
            user_id INTEGER PRIMARY KEY, step TEXT, data TEXT
        )""")
        try: db.execute("ALTER TABLE user_state ADD COLUMN data TEXT")
        except: pass

    with get_db() as db:
        orphans = db.execute("SELECT COUNT(*) as c FROM services WHERE category_id IS NULL").fetchone()['c']
        if orphans > 0:
            db.execute("INSERT OR IGNORE INTO categories (name) VALUES ('📦 अन्य सेवाएं')")
            cat = db.execute("SELECT id FROM categories WHERE name='📦 अन्य सेवाएं'").fetchone()
            db.execute("UPDATE services SET category_id=? WHERE category_id IS NULL", [cat['id']])


def save_user(user):
    with get_db() as db:
        db.execute("""INSERT INTO users (user_id, name, username, last_seen)
                      VALUES (?, ?, ?, ?)
                      ON CONFLICT(user_id) DO UPDATE SET
                        name=excluded.name, username=excluded.username, last_seen=excluded.last_seen""",
                   [user.id, user.first_name or "", user.username or "",
                    datetime.now(timezone.utc).isoformat()])


def user_display(user_id):
    with get_db() as db:
        row = db.execute("SELECT name, username FROM users WHERE user_id=?", [user_id]).fetchone()
    if not row: return f"User {user_id}"
    name = row['name'] or "User"
    return f"{name} (@{row['username']})" if row['username'] else name


def get_or_create_category(name):
    with get_db() as db:
        db.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", [name])
        row = db.execute("SELECT id FROM categories WHERE name=?", [name]).fetchone()
    return row['id']


def set_user_state(user_id, step, data=None):
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO user_state (user_id, step, data) VALUES (?, ?, ?)",
                   [user_id, step, data])


def get_user_state(user_id):
    with get_db() as db:
        return db.execute("SELECT * FROM user_state WHERE user_id=?", [user_id]).fetchone()


def clear_user_state(user_id):
    with get_db() as db:
        db.execute("DELETE FROM user_state WHERE user_id=?", [user_id])


# ============ ग्राहक (User) वाला हिस्सा ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        await update.message.reply_text("🛠️ एडमिन पैनल में आपका स्वागत है।\nसेवाएं जोड़ने या बदलने के लिए /admin दबाएं।")
        return
    save_user(user)
    clear_user_state(user.id)
    await send_categories(update.message, page=0, edit=False)


async def send_categories(target, page=0, edit=False):
    with get_db() as db:
        cats = db.execute("""SELECT c.id, c.name, COUNT(s.id) as cnt
                             FROM categories c
                             LEFT JOIN services s ON s.category_id = c.id AND s.is_active = 1
                             WHERE c.is_active = 1
                             GROUP BY c.id
                             ORDER BY c.sort_order, c.name""").fetchall()
    cats = [c for c in cats if c['cnt'] > 0]

    if not cats:
        txt = ("🙏 नमस्ते!\n\nअभी कोई सेवा उपलब्ध नहीं है।\n"
               "आप अपनी जरूरत यहाँ सीधे मैसेज करके बता सकते हैं, हमारी टीम आपसे संपर्क करेगी।")
        if edit: await target.edit_message_text(txt)
        else: await target.reply_text(txt)
        return

    total = len(cats)
    total_pages = (total + CATS_PER_PAGE - 1) // CATS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    page_cats = cats[page * CATS_PER_PAGE:(page + 1) * CATS_PER_PAGE]

    # 🔥 2 बटन एक लाइन में (Landscape Layout) - बिना नाम काटे
    kb = []
    row = []
    for c in page_cats:
        btn_text = c['name'] 
        row.append(InlineKeyboardButton(btn_text, callback_data=f"ucat_{c['id']}_0"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: 
        kb.append(row)

    # आगे-पीछे जाने वाले बटन
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ पिछला", callback_data=f"ucats_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("अगला ➡️", callback_data=f"ucats_{page+1}"))
    if nav:
        kb.append(nav)

    # नीचे के बटन
    kb.append([InlineKeyboardButton("🔍 सेवा खोजें (Search)", callback_data="u_search")])
    kb.append([InlineKeyboardButton("💬 सीधे मैसेज करें", callback_data="u_help")])

    txt = (f"🙏 <b>नमस्ते! हमारी सेवाओं में आपका स्वागत है।</b>\n\n"
           f"👇 <b>नीचे दिए गए विकल्पों में से सेवा चुनें:</b> (पेज {page+1}/{total_pages})")
    if edit:
        await target.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        await target.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def show_category_page(query, cat_id, page):
    with get_db() as db:
        cat = db.execute("SELECT * FROM categories WHERE id=?", [cat_id]).fetchone()
        if not cat:
            await query.edit_message_text("क्षमा करें, यह श्रेणी नहीं मिली।")
            return
        total = db.execute("SELECT COUNT(*) as c FROM services WHERE category_id=? AND is_active=1",
                           [cat_id]).fetchone()['c']
        if total == 0:
            await query.edit_message_text("इस श्रेणी में अभी कोई सेवा उपलब्ध नहीं है।")
            return
        rows = db.execute("SELECT * FROM services WHERE category_id=? AND is_active=1 ORDER BY id LIMIT ? OFFSET ?",
                          [cat_id, PAGE_SIZE, page * PAGE_SIZE]).fetchall()

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    
    msg = f"📁 <b>{cat['name']}</b>  ({page+1}/{total_pages})\n\n"
    for row in rows:
        msg += f"🔹 <b>{row['name']}</b>\n💰 फीस: ₹{row['price']}\n📄 जरूरी दस्तावेज़: {row['docs']}\n\n"

    kb = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ पिछला", callback_data=f"ucat_{cat_id}_{page-1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("अगला ➡️", callback_data=f"ucat_{cat_id}_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🔍 सेवा खोजें", callback_data="u_search")])
    kb.append([InlineKeyboardButton("🔙 मुख्य पेज पर जाएं", callback_data="u_cats")])

    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def show_search_results(target, query_text, page=0, edit=True):
    query_text = (query_text or "").strip()
    if not query_text:
        txt = "कृपया कुछ लिखकर सर्च करें।"
        if edit: await target.edit_message_text(txt)
        else: await target.reply_text(txt)
        return

    like = f"%{query_text}%"
    with get_db() as db:
        total = db.execute("""SELECT COUNT(*) as c FROM services s
                              LEFT JOIN categories c ON c.id = s.category_id
                              WHERE s.is_active = 1 AND (c.is_active = 1 OR c.id IS NULL)
                              AND (s.name LIKE ? OR s.docs LIKE ?)""",
                           [like, like]).fetchone()['c']
        if total == 0:
            kb = [[InlineKeyboardButton("🔍 दोबारा खोजें", callback_data="u_search")],
                  [InlineKeyboardButton("🔙 मुख्य पेज पर जाएं", callback_data="u_cats")]]
            txt = f"🔍 '<b>{query_text}</b>' के लिए कोई सेवा नहीं मिली।\n\nकृपया कोई दूसरा शब्द आज़माएं।"
            if edit:
                await target.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            else:
                await target.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            return
        rows = db.execute("""SELECT s.*, c.name as cat_name FROM services s
                             LEFT JOIN categories c ON c.id = s.category_id
                             WHERE s.is_active = 1 AND (c.is_active = 1 OR c.id IS NULL)
                             AND (s.name LIKE ? OR s.docs LIKE ?)
                             ORDER BY s.name LIMIT ? OFFSET ?""",
                          [like, like, SEARCH_PER_PAGE, page * SEARCH_PER_PAGE]).fetchall()

    total_pages = (total + SEARCH_PER_PAGE - 1) // SEARCH_PER_PAGE
    msg = f"🔍 <b>'{query_text}'</b> के लिए {total} परिणाम मिले (पेज {page+1}/{total_pages})\n\n"
    for row in rows:
        cat = row['cat_name'] or "—"
        msg += f"🔹 <b>{row['name']}</b>\n💰 फीस: ₹{row['price']}\n📁 {cat} · 📄 {row['docs']}\n\n"

    kb = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ पिछला", callback_data=f"usearch_{page-1}"))
    if (page + 1) * SEARCH_PER_PAGE < total:
        nav.append(InlineKeyboardButton("अगला ➡️", callback_data=f"usearch_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🔍 नई खोज करें", callback_data="u_search")])
    kb.append([InlineKeyboardButton("🔙 मुख्य पेज पर जाएं", callback_data="u_cats")])

    if edit:
        await target.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        await target.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


# ============ एडमिन (Admin) वाला हिस्सा ============
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    with get_db() as db:
        db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
    await update.message.reply_text("🛠️ <b>एडमिन पैनल</b>\nआप क्या करना चाहेंगे?",
                                    reply_markup=admin_kb(), parse_mode="HTML")


def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ नई सर्विस जोड़ें", callback_data="add_service")],
        [InlineKeyboardButton("📦 एक साथ कई सर्विस जोड़ें (Bulk)", callback_data="bulk_add")],
        [InlineKeyboardButton("📁 श्रेणियां (Categories) मैनेज करें", callback_data="cat_menu")],
        [InlineKeyboardButton("📋 सभी सर्विस की लिस्ट देखें", callback_data="svclist_0")],
        [InlineKeyboardButton("👥 यूजर्स की लिस्ट (चैट के लिए)", callback_data="show_users")],
    ])


async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    with get_db() as db:
        rows = db.execute("SELECT user_id, name FROM users ORDER BY last_seen DESC").fetchall()
    if not rows:
        await update.message.reply_text("अभी तक किसी यूजर ने मैसेज नहीं किया है।")
        return
    kb = [[InlineKeyboardButton(f"👤 {row['name'] or 'User'}", callback_data=f"rep_{row['user_id']}")] for row in rows[:30]]
    await update.message.reply_text(f"👥 <b>कुल यूजर्स ({len(rows)})</b>\nजिसे जवाब देना है उस पर टैप करें:",
                                    reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    with get_db() as db:
        db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
    await update.message.reply_text("✅ आपका पिछला काम रद्द कर दिया गया है। दोबारा शुरू करने के लिए /admin दबाएं।")


# ---- श्रेणी (Category) मैनेजमेंट ----
async def show_cat_menu(query):
    with get_db() as db:
        cats = db.execute("""SELECT c.id, c.name, c.is_active, COUNT(s.id) as cnt
                             FROM categories c
                             LEFT JOIN services s ON s.category_id = c.id
                             GROUP BY c.id ORDER BY c.sort_order, c.name""").fetchall()
    kb = []
    for c in cats:
        status = "✅" if c['is_active'] else "⛔"
        kb.append([InlineKeyboardButton(f"{status} {trunc(c['name'], 30)} ({c['cnt']})",
                                        callback_data=f"cat_view_{c['id']}")])
    kb.append([InlineKeyboardButton("➕ नई श्रेणी जोड़ें", callback_data="cat_add")])
    kb.append([InlineKeyboardButton("🔙 पीछे जाएं", callback_data="back_admin")])
    await query.edit_message_text(f"📁 <b>आपकी श्रेणियां ({len(cats)})</b>\nकिसी श्रेणी को बदलने के लिए उस पर टैप करें:",
                                  reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def show_cat_card(query, cat_id):
    with get_db() as db:
        cat = db.execute("SELECT * FROM categories WHERE id=?", [cat_id]).fetchone()
        if not cat:
            await query.edit_message_text("श्रेणी नहीं मिली।")
            return
        cnt = db.execute("SELECT COUNT(*) as c FROM services WHERE category_id=?", [cat_id]).fetchone()['c']
        act = db.execute("SELECT COUNT(*) as c FROM services WHERE category_id=? AND is_active=1",
                         [cat_id]).fetchone()['c']

    status = "✅ चालू" if cat['is_active'] else "⛔ बंद"
    toggle = "⛔ श्रेणी को बंद करें" if cat['is_active'] else "✅ श्रेणी को चालू करें"
    txt = (f"📁 <b>{cat['name']}</b>\n\n"
           f"कुल सर्विस: {cnt}\nचालू सर्विस: {act}\nस्थिति: {status}")
    kb = [
        [InlineKeyboardButton("✏️ नाम बदलें", callback_data=f"cat_ren_{cat_id}")],
        [InlineKeyboardButton(toggle, callback_data=f"cat_tog_{cat_id}")],
        [InlineKeyboardButton("🔙 पीछे जाएं", callback_data="cat_menu")],
    ]
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


# ---- सर्विस लिस्ट / कार्ड ----
async def show_service_list_page(query, page):
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) as c FROM services").fetchone()['c']
        if total == 0:
            await query.edit_message_text("अभी कोई सर्विस नहीं है।")
            return
        rows = db.execute("SELECT * FROM services ORDER BY category_id, id LIMIT ? OFFSET ?",
                          [PAGE_SIZE, page * PAGE_SIZE]).fetchall()
    kb = [[InlineKeyboardButton(f"{'✅' if r['is_active'] else '⛔'} {trunc(r['name'], 25)} — ₹{r['price']}",
                                callback_data=f"svc_{r['id']}")] for r in rows]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ पिछला", callback_data=f"svclist_{page-1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("अगला ➡️", callback_data=f"svclist_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🔙 पीछे जाएं", callback_data="back_admin")])
    await query.edit_message_text(f"📋 <b>सभी सर्विस</b> (कुल {total}) — पेज {page+1}:",
                                  reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def show_service_card(query, sid):
    with get_db() as db:
        row = db.execute("SELECT * FROM services WHERE id=?", [sid]).fetchone()
        if not row:
            await query.edit_message_text("❌ सर्विस नहीं मिली।")
            return
        cat = db.execute("SELECT name FROM categories WHERE id=?", [row['category_id']]).fetchone() if row['category_id'] else None
    cat_name = cat['name'] if cat else "—"
    if row['is_active']:
        status, toggle = "✅ चालू", "⛔ डिसेबल करें"
    else:
        status, toggle = "⛔ बंद", "✅ इनेबल करें"
    txt = f"<b>{row['name']}</b>\n📁 श्रेणी: {cat_name}\n💰 फीस: ₹{row['price']}\n📄 दस्तावेज़: {row['docs']}\n\nस्थिति: {status}"
    kb = [
        [InlineKeyboardButton("✏️ नाम बदलें", callback_data=f"ef_name_{sid}"),
         InlineKeyboardButton("💰 फीस बदलें", callback_data=f"ef_price_{sid}")],
        [InlineKeyboardButton("📄 दस्तावेज़ बदलें", callback_data=f"ef_docs_{sid}")],
        [InlineKeyboardButton(toggle, callback_data=f"tog_{sid}")],
        [InlineKeyboardButton("🔙 लिस्ट पर वापस", callback_data="svclist_0")],
    ]
    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


# ---- बल्क (Bulk) पार्सर ----
def parse_bulk(text):
    lines = [l.strip() for l in text.strip().split('\n') if l.strip() and not l.strip().startswith('//')]
    result, errors = [], []
    current_cat = None
    for line in lines:
        if line.startswith('#'):
            current_cat = line.lstrip('#').strip() or None
            if not current_cat:
                errors.append(f"खाली श्रेणी: {line[:40]}")
            continue
        if '|' not in line:
            errors.append(f"'|' नहीं मिला: {line[:40]}")
            continue
        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 2:
            errors.append(f"नाम और फीस जरूरी है: {line[:40]}")
            continue
        name = parts[0]
        if not name:
            errors.append(f"नाम खाली है: {line[:40]}")
            continue
        try:
            price = int(parts[1])
            if price <= 0: raise ValueError
        except ValueError:
            errors.append(f"गलत फीस: {line[:40]}")
            continue
        docs = parts[2] if len(parts) > 2 else "—"
        result.append((current_cat, name, price, docs))
    return result, errors


# ============ बटन क्लिक हैंडलर ============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ---- ग्राहक (USER) के बटन ----
    if data == "u_cats":
        clear_user_state(query.from_user.id)
        await send_categories(query, page=0, edit=True); return
    if data == "u_help":
        clear_user_state(query.from_user.id)
        await query.edit_message_text(
            "💬 आप अपना सवाल या जरूरत यहाँ टाइप करके भेज सकते हैं। हमारी टीम जल्द ही आपसे संपर्क करेगी।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 मुख्य पेज पर जाएं", callback_data="u_cats")]]))
        return
    if data == "u_search":
        set_user_state(query.from_user.id, 'search_wait', None)
        await query.edit_message_text(
            "🔍 आप किस सेवा को खोजना चाहते हैं? उसका नाम नीचे लिखकर भेजें:\n\n"
            "उदाहरण: <code>PAN</code>, <code>आधार</code>, <code>शादी</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ रद्द करें", callback_data="u_cats")]]),
            parse_mode="HTML")
        return
    if data == "noop":
        return
    if data.startswith("ucats_"):
        await send_categories(query, page=int(data.split("_")[1]), edit=True); return
    if data.startswith("ucat_"):
        p = data.split("_")
        await show_category_page(query, int(p[1]), int(p[2])); return
    if data.startswith("usearch_"):
        page = int(data.split("_")[1])
        st = get_user_state(query.from_user.id)
        if st and st['step'] == 'search_done' and st['data']:
            await show_search_results(query, st['data'], page=page, edit=True)
        else:
            await query.edit_message_text("सर्च का समय समाप्त हो गया है। कृपया फिर से खोजें।",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔍 दोबारा खोजें", callback_data="u_search")]]))
        return

    # ---- एडमिन (ADMIN) के बटन ----
    if query.from_user.id != ADMIN_ID: return

    if data == "back_admin":
        with get_db() as db:
            db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
        await query.edit_message_text("🛠️ <b>एडमिन पैनल</b>", reply_markup=admin_kb(), parse_mode="HTML"); return
    if data == "cat_menu":
        await show_cat_menu(query); return
    if data == "cat_add":
        with get_db() as db:
            db.execute("INSERT OR REPLACE INTO admin_state VALUES (?, 'new_cat', '{}')", [ADMIN_ID])
        await query.edit_message_text("📁 नई श्रेणी का नाम क्या रखना है?\n\n💡 <i>नोट: नाम के आगे इमोजी जरूर लगाएं (जैसे: 💳 पैन कार्ड)</i>", parse_mode="HTML"); return
    if data.startswith("cat_view_"):
        await show_cat_card(query, int(data.split("_")[2])); return
    if data.startswith("cat_ren_"):
        cid = int(data.split("_")[2])
        with get_db() as db:
            db.execute("INSERT OR REPLACE INTO admin_state VALUES (?, 'edit_cat', ?)",
                       [ADMIN_ID, json.dumps({"id": cid})])
        await query.edit_message_text("✏️ श्रेणी का नया नाम क्या रखना है?"); return
    if data.startswith("cat_tog_"):
        cid = int(data.split("_")[2])
        with get_db() as db:
            row = db.execute("SELECT is_active FROM categories WHERE id=?", [cid]).fetchone()
            db.execute("UPDATE categories SET is_active=? WHERE id=?", [0 if row['is_active'] else 1, cid])
        await show_cat_card(query, cid); return
    if data == "bulk_add":
        with get_db() as db:
            db.execute("INSERT OR REPLACE INTO admin_state VALUES (?, 'bulk_add', '{}')", [ADMIN_ID])
        help_txt = (
            "📦 <b>एक साथ कई सर्विस जोड़ें</b>\n\n"
            "नीचे दिए गए फॉर्मेट में टेक्स्ट कॉपी करके पेस्ट करें (हर लाइन में एक सर्विस):\n\n"
            "<code># श्रेणी का नाम\n"
            "सर्विस का नाम | फीस | दस्तावेज़\n"
            "पैन कार्ड | 150 | आधार, फोटो\n"
            "आधार अपडेट | 100 | आधार कॉपी</code>\n\n"
            "• <code># श्रेणी</code> से श्रेणी तय होगी (नहीं लिखा तो 'अन्य' में जाएगा)\n"
            "• फीस में सिर्फ नंबर लिखें, 0 से बड़ा होना चाहिए\n"
            "• दस्तावेज़ लिखना जरूरी नहीं है\n"
            "• <code>|</code> (पाइप) का इस्तेमाल करना जरूरी है\n"
            "• एक बार में 30-40 सर्विस भेज सकते हैं\n\n"
            "अब अपना टेक्स्ट भेजें:"
        )
        await query.edit_message_text(help_txt, parse_mode="HTML"); return
    if data == "add_service":
        with get_db() as db:
            cats = db.execute("SELECT id, name FROM categories WHERE is_active=1 ORDER BY sort_order, name").fetchall()
        if not cats:
            await query.edit_message_text("पहले एक श्रेणी बनाएं।")
            return
        kb = [[InlineKeyboardButton(f"📁 {trunc(c['name'], 28)}", callback_data=f"asel_{c['id']}")] for c in cats]
        await query.edit_message_text("यह सर्विस किस श्रेणी में जोड़नी है?", reply_markup=InlineKeyboardMarkup(kb)); return
    if data.startswith("asel_"):
        cid = int(data.split("_")[1])
        with get_db() as db:
            db.execute("INSERT OR REPLACE INTO admin_state VALUES (?, 'name', ?)",
                       [ADMIN_ID, json.dumps({"cat_id": cid})])
        await query.edit_message_text("सर्विस का नाम क्या रखना है? (उदा. पैन कार्ड अप्लाई)"); return
    if data.startswith("svclist_"):
        await show_service_list_page(query, int(data.split("_")[1])); return
    if data.startswith("svc_"):
        await show_service_card(query, int(data.split("_")[1])); return
    if data.startswith("tog_"):
        sid = int(data.split("_")[1])
        with get_db() as db:
            row = db.execute("SELECT is_active FROM services WHERE id=?", [sid]).fetchone()
            db.execute("UPDATE services SET is_active=? WHERE id=?", [0 if row['is_active'] else 1, sid])
        await show_service_card(query, sid); return
    if data.startswith("ef_"):
        p = data.split("_")
        field, sid = p[1], int(p[2])
        with get_db() as db:
            db.execute("INSERT OR REPLACE INTO admin_state VALUES (?, ?, ?)",
                       [ADMIN_ID, f"edit_{field}", json.dumps({"id": sid})])
        prompts = {"name": "✏️ सर्विस का नया नाम भेजें:", "price": "💰 नई फीस क्या रखनी है? (सिर्फ नंबर में):", "docs": "📄 कौन से दस्तावेज़ जरूरी होंगे? (जैसे: आधार, फोटो):"}
        await query.edit_message_text(prompts[field]); return
    if data.startswith("rep_"):
        tid = int(data.split("_")[1])
        with get_db() as db:
            db.execute("INSERT OR REPLACE INTO admin_state VALUES (?, 'reply', ?)",
                       [ADMIN_ID, json.dumps({"target": tid})])
        try: await query.edit_message_reply_markup(reply_markup=None)
        except: pass
        await query.message.reply_text(f"✍️ <b>{user_display(tid)}</b> को जवाब लिखें:", parse_mode="HTML"); return
    if data == "show_users":
        with get_db() as db:
            rows = db.execute("SELECT user_id, name FROM users ORDER BY last_seen DESC").fetchall()
        if not rows:
            await query.edit_message_text("अभी किसी यूजर ने मैसेज नहीं किया है।")
            return
        kb = [[InlineKeyboardButton(f"👤 {row['name'] or 'User'}", callback_data=f"rep_{row['user_id']}")] for row in rows[:30]]
        kb.append([InlineKeyboardButton("🔙 पीछे जाएं", callback_data="back_admin")])
        await query.edit_message_text(f"👥 यूजर्स की लिस्ट ({len(rows)}):", reply_markup=InlineKeyboardMarkup(kb)); return


# ============ टेक्स्ट मैसेज हैंडलर ============
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    msg = update.message

    if user.id == ADMIN_ID:
        # पुराना तरीका (नोटिफिकेशन पर रिप्लाई)
        if msg.reply_to_message and msg.reply_to_message.text and "User ID:" in msg.reply_to_message.text:
            try:
                tid = int(msg.reply_to_message.text.split("User ID: ")[1].split("\n")[0].strip())
            except Exception:
                await msg.reply_text("❌ User ID पढ़ने में दिक्कत आ रही है।"); return
            await context.bot.send_message(chat_id=tid, text=f"👨‍💼 <b>एडमिन:</b>\n{text}", parse_mode="HTML")
            await msg.reply_text(f"✅ जवाब भेज दिया गया → {user_display(tid)}"); return

        with get_db() as db:
            state = db.execute("SELECT * FROM admin_state WHERE admin_id=?", [ADMIN_ID]).fetchone()

        if state:
            step = state['step']
            temp = json.loads(state['temp_data'] or '{}')

            if step == 'reply':
                tid = temp['target']
                await context.bot.send_message(chat_id=tid, text=f"👨‍💼 <b>एडमिन:</b>\n{text}", parse_mode="HTML")
                with get_db() as db:
                    db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
                await msg.reply_text(f"✅ जवाब भेज दिया गया → {user_display(tid)}\n\nबाकी यूजर्स को जवाब देने के लिए /users दबाएं।"); return
            
            if step == 'new_cat':
                if len(text) > 50:
                    await msg.reply_text("❌ श्रेणी का नाम 50 अक्षरों से बड़ा नहीं होना चाहिए।"); return
                with get_db() as db:
                    if db.execute("SELECT id FROM categories WHERE name=?", [text]).fetchone():
                        await msg.reply_text("❌ यह नाम पहले से मौजूद है।"); return
                    db.execute("INSERT INTO categories (name) VALUES (?)", [text])
                    db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
                await msg.reply_text(f"✅ नई श्रेणी '{text}' जोड़ दी गई है।"); return
            
            if step == 'edit_cat':
                if len(text) > 50:
                    await msg.reply_text("❌ श्रेणी का नाम 50 अक्षरों से बड़ा नहीं होना चाहिए।"); return
                with get_db() as db:
                    db.execute("UPDATE categories SET name=? WHERE id=?", [text, temp['id']])
                    db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
                await msg.reply_text("✅ श्रेणी का नाम बदल दिया गया है।"); return
            
            if step == 'bulk_add':
                items, errors = parse_bulk(text)
                if not items and not errors:
                    await msg.reply_text("❌ कोई भी सही लाइन नहीं मिली। कृपया फॉर्मेट चेक करें।"); return
                added, cats = 0, set()
                for cat_name, name, price, docs in items:
                    cat = cat_name if cat_name else "📦 अन्य सेवाएं"
                    cid = get_or_create_category(cat)
                    with get_db() as db:
                        db.execute("INSERT INTO services (name, price, docs, category_id, is_active) VALUES (?, ?, ?, ?, 1)",
                                   [name, price, docs, cid])
                    added += 1; cats.add(cat)
                with get_db() as db:
                    db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
                r = f"✅ <b>{added} सर्विस सफलतापूर्वक जोड़ दी गईं</b>\n📁 श्रेणियां: {', '.join(sorted(cats))}\n"
                if errors:
                    r += f"\n⚠️ {len(errors)} लाइनें छोड़ दी गईं क्योंकि उनमें गलती थी:\n"
                    for e in errors[:10]: r += f"• {e}\n"
                    if len(errors) > 10: r += f"...और {len(errors)-10} गलतियां\n"
                await msg.reply_text(r, parse_mode="HTML"); return
            
            if step == 'name':
                temp['name'] = text
                with get_db() as db:
                    db.execute("UPDATE admin_state SET step='price', temp_data=? WHERE admin_id=?",
                               [json.dumps(temp), ADMIN_ID])
                await msg.reply_text("💰 इसकी फीस कितनी है? (सिर्फ नंबर में लिखें):"); return
            
            if step == 'price':
                try:
                    temp['price'] = int(text)
                    if temp['price'] <= 0: raise ValueError
                except ValueError:
                    await msg.reply_text("❌ गलत फीस। कृपया सिर्फ नंबर लिखें (0 से बड़ा):"); return
                with get_db() as db:
                    db.execute("UPDATE admin_state SET step='docs', temp_data=? WHERE admin_id=?",
                               [json.dumps(temp), ADMIN_ID])
                await msg.reply_text("📄 इसके लिए कौन-कौन से दस्तावेज़ चाहिए? (जैसे: आधार कार्ड, फोटो):"); return
            
            if step == 'docs':
                with get_db() as db:
                    db.execute("INSERT INTO services (name, price, docs, category_id, is_active) VALUES (?, ?, ?, ?, 1)",
                               [temp['name'], temp['price'], text, temp['cat_id']])
                    db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
                await msg.reply_text("✅ नई सर्विस जोड़ दी गई है!"); return
            
            if step == 'edit_name':
                with get_db() as db:
                    db.execute("UPDATE services SET name=? WHERE id=?", [text, temp['id']])
                    db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
                await msg.reply_text("✅ सर्विस का नाम अपडेट हो गया है।"); return
            
            if step == 'edit_price':
                try:
                    np = int(text)
                    if np <= 0: raise ValueError
                except ValueError:
                    await msg.reply_text("❌ गलत फीस। कृपया सिर्फ नंबर लिखें:"); return
                with get_db() as db:
                    db.execute("UPDATE services SET price=? WHERE id=?", [np, temp['id']])
                    db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
                await msg.reply_text("✅ फीस अपडेट हो गई है।"); return
            
            if step == 'edit_docs':
                with get_db() as db:
                    db.execute("UPDATE services SET docs=? WHERE id=?", [text, temp['id']])
                    db.execute("DELETE FROM admin_state WHERE admin_id=?", [ADMIN_ID])
                await msg.reply_text("✅ दस्तावेज़ अपडेट हो गए हैं।"); return
            return

        await msg.reply_text("🤖 माफी, मैं समझ नहीं पाया।\n\n• सर्विस जोड़ने के लिए /admin दबाएं\n• यूजर्स को जवाब देने के लिए /users दबाएं"); return

    # ---- ग्राहक (USER) का मैसेज ----
    st = get_user_state(user.id)
    if st and st['step'] == 'search_wait':
        set_user_state(user.id, 'search_done', text)
        await show_search_results(msg, text, page=0, edit=False)
        return

    save_user(user)
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(f"💬 <b>नया मैसेज आया है</b>\n👤 {user.first_name or 'User'}"
              + (f" (@{user.username})" if user.username else "") +
              f"\n🆔 User ID: {user.id}\n\n{text}"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ जवाब दें", callback_data=f"rep_{user.id}")
        ]]))
    await msg.reply_text("✅ आपका मैसेज हमें मिल गया है। हम जल्द ही आपसे संपर्क करेंगे।")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if user.id != ADMIN_ID:
        save_user(user)
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(f"📁 <b>नई फाइल/फोटो प्राप्त हुई</b>\n👤 {user.first_name or 'User'}"
                  + (f" (@{user.username})" if user.username else "") +
                  f"\n🆔 User ID: {user.id}"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ जवाब दें", callback_data=f"rep_{user.id}")
            ]]))
        await msg.forward(chat_id=ADMIN_ID)
        await msg.reply_text("✅ आपकी फाइल हमें मिल गई है।")


def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("users", users_list))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_document))
    print("बॉट चालू हो गया है...")
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
