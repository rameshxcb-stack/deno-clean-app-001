import io
import os
import asyncio
import logging
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import qrcode

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
BOT_TOKEN     = os.getenv("BOT_TOKEN")
UPI_ID        = os.getenv("UPI_ID")
PAYEE_NAME    = os.getenv("PAYEE_NAME", "My Cyber Cafe")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
# ============================================================

CATEGORIES = {
    "print": {
        "name": "🖨️ Printing & Photocopy",
        "desc": "B&W/Color print, xerox, scan, lamination",
        "services": [
            {"id": "print_bw",       "name": "B&W Print (Per Page)",     "price": 2,   "emoji": "📄"},
            {"id": "print_color",    "name": "Color Print (Per Page)",   "price": 10,  "emoji": "🌈"},
            {"id": "photocopy",      "name": "Photocopy (Per Page)",     "price": 1,   "emoji": "📑"},
            {"id": "scan",           "name": "Scanning (Per Page)",      "price": 5,   "emoji": "📷"},
            {"id": "lam_a4",         "name": "Lamination A4",            "price": 30,  "emoji": "🪪"},
            {"id": "lam_a3",         "name": "Lamination A3",            "price": 50,  "emoji": "📰"},
            {"id": "lam_id",         "name": "Lamination ID Card",       "price": 15,  "emoji": "🆔"},
            {"id": "passport_photo", "name": "Passport Photo (8 Copies)", "price": 50,  "emoji": "👤"},
            {"id": "photo_print",    "name": "Photo Print (Per Copy)",   "price": 15,  "emoji": "🖼️"},
            {"id": "id_card_print",  "name": "ID Card Print",            "price": 30,  "emoji": "🎫"},
            {"id": "visiting_card",  "name": "Visiting Card (100 pcs)",  "price": 300, "emoji": "📇"},
            {"id": "flex_banner",    "name": "Flex Banner (Per Sq Ft)",  "price": 50,  "emoji": "🎨"},
        ],
    },
    "gov": {
        "name": "🏛️ Government Services",
        "desc": "PAN, Aadhaar, Voter ID, License aur baaki",
        "services": [
            {"id": "pan_new",        "name": "PAN Card (New)",              "price": 150, "emoji": "💳"},
            {"id": "pan_correct",    "name": "PAN Card Correction",         "price": 200, "emoji": "✏️"},
            {"id": "aadhaar_update", "name": "Aadhaar Update/Correction",   "price": 100, "emoji": "🆔"},
            {"id": "voter_new",      "name": "Voter ID (New)",              "price": 100, "emoji": "🗳️"},
            {"id": "voter_correct",  "name": "Voter ID Correction",         "price": 100, "emoji": "✏️"},
            {"id": "dl_learner",     "name": "Driving License (Learner)",   "price": 500, "emoji": "🚗"},
            {"id": "dl_permanent",   "name": "Driving License (Permanent)", "price": 800, "emoji": "🚙"},
            {"id": "ration_card",    "name": "Ration Card",                 "price": 150, "emoji": "🍚"},
            {"id": "birth_cert",     "name": "Birth Certificate",           "price": 200, "emoji": "👶"},
            {"id": "death_cert",     "name": "Death Certificate",           "price": 200, "emoji": "🕊️"},
            {"id": "income_cert",    "name": "Income Certificate",          "price": 150, "emoji": "💰"},
            {"id": "caste_cert",     "name": "Caste Certificate",           "price": 150, "emoji": "📜"},
            {"id": "domicile",       "name": "Domicile Certificate",        "price": 150, "emoji": "🏠"},
            {"id": "marriage_cert",  "name": "Marriage Certificate",        "price": 300, "emoji": "💍"},
            {"id": "eshram",         "name": "E-Shram Card",                "price": 50,  "emoji": "👷"},
            {"id": "ayushman",       "name": "Ayushman Card",               "price": 50,  "emoji": "🏥"},
            {"id": "pm_kisan",       "name": "PM Kisan Registration",       "price": 100, "emoji": "🌾"},
            {"id": "passport_apply", "name": "Passport Application",        "price": 500, "emoji": "🛂"},
        ],
    },
    "forms": {
        "name": "📝 Online Exam Forms",
        "desc": "SSC, Railway, Bank, Police, College forms",
        "services": [
            {"id": "ssc_form",         "name": "SSC Exam Form",             "price": 100, "emoji": "📋"},
            {"id": "railway_form",     "name": "Railway Exam Form",         "price": 100, "emoji": "🚂"},
            {"id": "bank_form",        "name": "Bank Exam Form",            "price": 100, "emoji": "🏦"},
            {"id": "police_form",      "name": "Police Bharti Form",        "price": 100, "emoji": "👮"},
            {"id": "college_form",     "name": "College Admission Form",    "price": 200, "emoji": "🎓"},
            {"id": "scholarship_form", "name": "Scholarship Form",          "price": 100, "emoji": "🎖️"},
            {"id": "govt_job_form",    "name": "Government Job Form",       "price": 100, "emoji": "💼"},
            {"id": "army_form",        "name": "Army/Navy/Airforce Form",   "price": 150, "emoji": "⚔️"},
        ],
    },
    "doc": {
        "name": "📄 Document Services",
        "desc": "Typing, Resume, Email ID, Naukri profile",
        "services": [
            {"id": "typing",          "name": "Document Typing (Per Page)", "price": 20,  "emoji": "⌨️"},
            {"id": "resume",          "name": "Resume/CV Making",           "price": 100, "emoji": "📃"},
            {"id": "cover_letter",    "name": "Cover Letter",               "price": 50,  "emoji": "✉️"},
            {"id": "email_create",    "name": "Email ID Creation",          "price": 30,  "emoji": "📧"},
            {"id": "naukri_profile",  "name": "Naukri.com Profile",         "price": 100, "emoji": "🔍"},
            {"id": "linkedin_profile","name": "LinkedIn Profile Setup",     "price": 150, "emoji": "💼"},
        ],
    },
    "bill": {
        "name": "💡 Bill Payment & Recharge",
        "desc": "Mobile, DTH, electricity, water bill, transfer",
        "services": [
            {"id": "mobile_recharge",   "name": "Mobile Recharge",              "price": 10, "emoji": "📱"},
            {"id": "dth_recharge",      "name": "DTH Recharge",                 "price": 20, "emoji": "📡"},
            {"id": "electricity_bill",  "name": "Electricity Bill Payment",     "price": 20, "emoji": "💡"},
            {"id": "water_bill",        "name": "Water Bill Payment",           "price": 20, "emoji": "💧"},
            {"id": "gas_bill",          "name": "Gas Bill Payment",             "price": 20, "emoji": "🔥"},
            {"id": "broadband_bill",    "name": "Broadband Bill Payment",       "price": 20, "emoji": "🌐"},
            {"id": "money_transfer",    "name": "Money Transfer (Up to ₹5000)", "price": 50, "emoji": "💸"},
        ],
    },
    "ticket": {
        "name": "🎫 Ticket Booking",
        "desc": "Train, bus, flight, movie tickets",
        "services": [
            {"id": "train_ticket",  "name": "Train Ticket (IRCTC)", "price": 50,  "emoji": "🚆"},
            {"id": "bus_ticket",    "name": "Bus Ticket Booking",   "price": 30,  "emoji": "🚌"},
            {"id": "flight_ticket", "name": "Flight Ticket Booking","price": 100, "emoji": "✈️"},
            {"id": "movie_ticket",  "name": "Movie Ticket Booking", "price": 30,  "emoji": "🎬"},
        ],
    },
    "computer": {
        "name": "💻 Computer Services",
        "desc": "Software, antivirus, data recovery, setup",
        "services": [
            {"id": "software_install", "name": "Software Installation",  "price": 100, "emoji": "💾"},
            {"id": "antivirus",        "name": "Antivirus Installation", "price": 200, "emoji": "🛡️"},
            {"id": "windows_install",  "name": "Windows Installation",   "price": 300, "emoji": "🪟"},
            {"id": "data_recovery",    "name": "Data Recovery",          "price": 500, "emoji": "💿"},
            {"id": "whatsapp_setup",   "name": "WhatsApp Setup",         "price": 30,  "emoji": "💬"},
            {"id": "upi_setup",        "name": "UPI Setup",              "price": 30,  "emoji": "📲"},
            {"id": "printer_setup",    "name": "Printer Setup",          "price": 100, "emoji": "🖨️"},
        ],
    },
    "advanced": {
        "name": "⚡ Advanced Services",
        "desc": "GST, ITR, MSME, Digital Signature, Editing",
        "services": [
            {"id": "gst_reg",          "name": "GST Registration",         "price": 500,  "emoji": "🧾"},
            {"id": "itr_filing",       "name": "ITR Filing",               "price": 500,  "emoji": "📊"},
            {"id": "msme_reg",         "name": "MSME/Udyam Registration",  "price": 500,  "emoji": "🏭"},
            {"id": "digital_sig",      "name": "Digital Signature",        "price": 1000, "emoji": "🖊️"},
            {"id": "photo_edit",       "name": "Photo Editing",            "price": 50,   "emoji": "🎨"},
            {"id": "video_edit",       "name": "Video Editing",            "price": 100,  "emoji": "🎥"},
            {"id": "visiting_design",  "name": "Visiting Card Design",     "price": 100,  "emoji": "📇"},
        ],
    },
}


def find_service(service_id):
    for cat in CATEGORIES.values():
        for svc in cat["services"]:
            if svc["id"] == service_id:
                return svc
    return None


def main_menu_keyboard():
    keyboard, cats = [], list(CATEGORIES.items())
    for i in range(0, len(cats), 2):
        row = [InlineKeyboardButton(cats[i][1]["name"], callback_data=f"cat_{cats[i][0]}")]
        if i + 1 < len(cats):
            row.append(InlineKeyboardButton(cats[i+1][1]["name"], callback_data=f"cat_{cats[i+1][0]}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)


# ---------------- Handlers ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = await update.message.reply_text("🤖 <b>Bot starting...</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.4)
    await msg.edit_text("🔧 <b>Loading services...</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.4)
    await msg.edit_text("✨ <b>Almost ready...</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.4)

    total = sum(len(c["services"]) for c in CATEGORIES.values())
    welcome = (
        f"🙏 <b>Namaste, {user.first_name}!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏪 <b>{PAYEE_NAME}</b> mein aapka swagat hai!\n\n"
        f"✅ <b>{total}+</b> services available\n"
        f"💳 <b>UPI Payment</b> — instant QR\n"
        f"⚡ <b>Fast Service</b> — 100% trusted\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 <b>Neeche se category chunein:</b>"
    )
    await msg.edit_text(welcome, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML)


async def show_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = query.data.replace("cat_", "")
    cat = CATEGORIES.get(cat_id)
    if not cat:
        await query.edit_message_text("❌ Category not found.")
        return

    await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(0.3)

    keyboard = []
    for svc in cat["services"]:
        price_text = f"₹{svc['price']}" if svc["price"] > 0 else "Free Info"
        keyboard.append([InlineKeyboardButton(
            f"{svc['emoji']} {svc['name']} — {price_text}",
            callback_data=f"svc_{svc['id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="back_main")])

    text = (
        f"{cat['name']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{cat['desc']}</i>\n\n"
        f"👇 <b>Service chunein:</b>"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def show_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    svc_id = query.data.replace("svc_", "")
    svc = find_service(svc_id)
    if not svc:
        await query.edit_message_text("❌ Service not found.")
        return
    context.user_data["selected_service"] = svc

    keyboard = [
        [InlineKeyboardButton("💳 Pay Now", callback_data="pay_now")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_main")],
    ]
    text = (
        f"{svc['emoji']} <b>{svc['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Price:</b> ₹{svc['price']}\n\n"
        f"💡 Payment karne ke liye <b>Pay Now</b> dabayein.\n"
        f"QR scan karke pay karein, phir screenshot bhejein."
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def pay_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    svc = context.user_data.get("selected_service")
    if not svc:
        await query.edit_message_text("⚠️ Pehle service select karein. /start")
        return

    chat_id = query.message.chat_id
    msg_id = query.message.message_id

    await query.edit_message_text("⏳ <b>QR generate ho raha hai...</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.5)
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)

    try:
        amount = svc["price"]
        note = f"{svc['name']} - {query.from_user.id}"
        upi_uri = (
            f"upi://pay?pa={quote(UPI_ID)}&pn={quote(PAYEE_NAME)}"
            f"&am={amount:.2f}&cu=INR&tn={quote(note)}"
        )
        img = qrcode.make(upi_uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "upi_qr.png"

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

        caption = (
            f"💳 <b>Payment Details</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{svc['emoji']} <b>Service:</b> {svc['name']}\n"
            f"💰 <b>Amount:</b> ₹{amount}\n"
            f"🆔 <b>UPI ID:</b> <code>{UPI_ID}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📸 <b>QR scan karke payment karein</b>\n"
            f"Payment ke baad <b>screenshot</b> yahan bhejein.\n"
            f"Verification ke baad service start hogi. ✅"
        )
        await context.bot.send_photo(chat_id=chat_id, photo=buf, caption=caption, parse_mode=ParseMode.HTML)
    except Exception:
        logger.exception("QR error")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ QR generate nahi hua. Admin se contact karein."
        )


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("selected_service", None)
    total = sum(len(c["services"]) for c in CATEGORIES.values())
    text = (
        f"🏪 <b>{PAYEE_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>{total}+</b> services available\n"
        f"💳 <b>UPI Payment</b> — instant QR\n\n"
        f"👇 <b>Category chunein:</b>"
    )
    await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML)


async def payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    svc = context.user_data.get("selected_service")
    service_name = svc["name"] if svc else "Unknown"
    amount = svc["price"] if svc else "N/A"

    admin_text = (
        f"🔔 <b>New Payment Proof</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Name:</b> {user.full_name}\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"📱 <b>Username:</b> @{user.username or 'N/A'}\n"
        f"🛠️ <b>Service:</b> {service_name}\n"
        f"💰 <b>Amount:</b> ₹{amount}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    admin_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{user.id}"),
    ]])

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=admin_text,
            reply_markup=admin_kb, parse_mode=ParseMode.HTML
        )
        if update.message.photo:
            await update.message.forward(chat_id=ADMIN_CHAT_ID)
        elif update.message.document:
            await update.message.forward(chat_id=ADMIN_CHAT_ID)
    except Exception:
        logger.exception("Admin message failed")

    await update.message.reply_text(
        f"✅ <b>Screenshot receive ho gaya!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛠️ <b>Service:</b> {service_name}\n"
        f"💰 <b>Amount:</b> ₹{amount}\n\n"
        f"⏳ Admin verify karega aur aapko update dega.\n"
        f"Dhanyavaad! 🙏",
        parse_mode=ParseMode.HTML,
    )
    context.user_data.pop("selected_service", None)


async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("❌ Not authorized", show_alert=True)
        return
    await query.answer()
    action, uid = query.data.split("_", 1)
    uid = int(uid)

    if action == "approve":
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"✅ <b>Payment Verified!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Aapki payment confirm ho gayi hai.\n"
                    f"Ab service jaldi start hogi. 🚀\n\n"
                    f"Dhanyavaad! 🙏"
                ),
                parse_mode=ParseMode.HTML,
            )
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ User <code>{uid}</code> ko approval bheja.", parse_mode=ParseMode.HTML)
        except Exception as e:
            await query.message.reply_text(f"❌ User ko message nahi gaya: {e}")
    else:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"❌ <b>Payment Reject</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Aapka payment verify nahi ho paya.\n"
                    f"Admin se contact karein ya dobara screenshot bhejein."
                ),
                parse_mode=ParseMode.HTML,
            )
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"❌ User <code>{uid}</code> ko reject bheja.", parse_mode=ParseMode.HTML)
        except Exception as e:
            await query.message.reply_text(f"❌ User ko message nahi gaya: {e}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"🆘 <b>Help Center</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"/start — Service menu\n"
        f"/help — Yeh message\n"
        f"/cancel — Process cancel\n\n"
        f"💡 <b>Kaise use karein:</b>\n"
        f"1️⃣ Category chunein\n"
        f"2️⃣ Service chunein\n"
        f"3️⃣ Pay Now dabayein\n"
        f"4️⃣ QR scan karke pay karein\n"
        f"5️⃣ Screenshot bhejein\n"
        f"6️⃣ Admin verify karega\n\n"
        f"📞 <b>Contact:</b> {PAYEE_NAME}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("selected_service", None)
    await update.message.reply_text(
        "🔄 <b>Process cancel ho gayi.</b>\n\n/start se dobara shuru karein.",
        parse_mode=ParseMode.HTML,
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CallbackQueryHandler(show_category, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(show_service, pattern="^svc_"))
    app.add_handler(CallbackQueryHandler(pay_now, pattern="^pay_now$"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^(approve|reject)_"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, payment_proof))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
