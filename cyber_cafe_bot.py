import io
import os
import asyncio
import logging
from urllib.parse import quote
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, KeyboardButton
)
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
PAYEE_NAME    = os.getenv("PAYEE_NAME", "मेरा साइबर कैफे")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
# ============================================================

# ------------------------------------------------------------
# 🛠️ सर्विस और डॉक्यूमेंट्स की लिस्ट (आसान भाषा में)
# ------------------------------------------------------------
CATEGORIES = {
    "print": {
        "name": "🖨️ प्रिंट और फोटोकॉपी",
        "desc": "रंगीन/ब्लैक एंड व्हाइट प्रिंट, फोटोकॉपी, स्कैन",
        "services": [
            {"id": "print_bw",       "name": "ब्लैक एंड व्हाइट प्रिंट (1 पेज)", "price": 2,   "emoji": "📄", "docs": "PDF, वर्ड फाइल या फोटो"},
            {"id": "print_color",    "name": "रंगीन प्रिंट (1 पेज)",           "price": 10,  "emoji": "🌈", "docs": "PDF, वर्ड फाइल या फोटो"},
            {"id": "photocopy",      "name": "फोटोकॉपी (1 पेज)",               "price": 1,   "emoji": "📑", "docs": "ओरिजिनल डॉक्यूमेंट"},
            {"id": "scan",           "name": "स्कैनिंग (1 पेज)",               "price": 5,   "emoji": "📷", "docs": "ओरिजिनल डॉक्यूमेंट"},
            {"id": "lam_a4",         "name": "लेमिनेशन A4",                    "price": 30,  "emoji": "🪪", "docs": "A4 साइज का डॉक्यूमेंट"},
            {"id": "lam_id",         "name": "लेमिनेशन आईडी कार्ड",             "price": 15,  "emoji": "🆔", "docs": "आईडी कार्ड (आधार/पैन आदि)"},
            {"id": "passport_photo", "name": "पासपोर्ट साइज फोटो (8 कॉपी)",    "price": 50,  "emoji": "👤", "docs": "कुछ नहीं चाहिए, बस आना है"},
            {"id": "photo_print",    "name": "फोटो प्रिंट (1 कॉपी)",           "price": 15,  "emoji": "🖼️", "docs": "मोबाइल में फोटो"},
        ],
    },
    "gov": {
        "name": "🏛️ सरकारी काम (Government)",
        "desc": "पैन, आधार, वोटर आईडी, लाइसेंस आदि",
        "services": [
            {"id": "pan_new",        "name": "नया पैन कार्ड",                  "price": 150, "emoji": "💳", "docs": "आधार कार्ड, फोटो, सिग्नेचर"},
            {"id": "pan_correct",    "name": "पैन कार्ड में सुधार",            "price": 200, "emoji": "✏️", "docs": "आधार, पुराना पैन, फोटो"},
            {"id": "aadhaar_update", "name": "आधार कार्ड अपडेट",               "price": 100, "emoji": "🆔", "docs": "आधार कार्ड, एड्रेस प्रूफ"},
            {"id": "voter_new",      "name": "नया वोटर आईडी",                  "price": 100, "emoji": "🗳️", "docs": "आधार कार्ड, फोटो, एड्रेस प्रूफ"},
            {"id": "dl_learner",     "name": "ड्राइविंग लाइसेंस (लर्निंग)",    "price": 500, "emoji": "🚗", "docs": "आधार कार्ड, फोटो, मेडिकल फॉर्म"},
            {"id": "dl_permanent",   "name": "ड्राइविंग लाइसेंस (पक्का)",      "price": 800, "emoji": "🚙", "docs": "लर्निंग लाइसेंस, आधार, फोटो"},
            {"id": "ration_card",    "name": "राशन कार्ड",                     "price": 150, "emoji": "🍚", "docs": "आधार कार्ड, एड्रेस प्रूफ, फोटो"},
            {"id": "birth_cert",     "name": "जन्म प्रमाण पत्र",               "price": 200, "emoji": "👶", "docs": "अस्पताल की पर्ची, माता-पिता का आधार"},
            {"id": "income_cert",    "name": "आय प्रमाण पत्र",                 "price": 150, "emoji": "💰", "docs": "आधार, राशन कार्ड, स्वयं घोषणा पत्र"},
            {"id": "caste_cert",     "name": "जाति प्रमाण पत्र",               "price": 150, "emoji": "📜", "docs": "आधार, पिता का जाति प्रमाण पत्र"},
            {"id": "eshram",         "name": "ई-श्रम कार्ड",                   "price": 50,  "emoji": "👷", "docs": "आधार कार्ड, बैंक पासबुक"},
            {"id": "ayushman",       "name": "आयुष्मान कार्ड",                 "price": 50,  "emoji": "🏥", "docs": "आधार कार्ड, राशन कार्ड"},
        ],
    },
    "forms": {
        "name": "📝 ऑनलाइन एग्जाम फॉर्म",
        "desc": "SSC, रेलवे, पुलिस, कॉलेज के फॉर्म",
        "services": [
            {"id": "ssc_form",         "name": "SSC एग्जाम फॉर्म",            "price": 100, "emoji": "📋", "docs": "10वीं/12वीं की मार्कशीट, आधार, फोटो, साइन"},
            {"id": "railway_form",     "name": "रेलवे एग्जाम फॉर्म",          "price": 100, "emoji": "🚂", "docs": "10वीं/12वीं की मार्कशीट, आधार, फोटो, साइन"},
            {"id": "police_form",      "name": "पुलिस भर्ती फॉर्म",           "price": 100, "emoji": "👮", "docs": "मार्कशीट, आधार, जाति प्रमाण पत्र, फोटो"},
            {"id": "college_form",     "name": "कॉलेज एडमिशन फॉर्म",          "price": 200, "emoji": "🎓", "docs": "12वीं की मार्कशीट, TC, माइग्रेशन, आधार"},
            {"id": "scholarship_form", "name": "स्कॉलरशिप फॉर्म",             "price": 100, "emoji": "🎖️", "docs": "आधार, मार्कशीट, बैंक पासबुक"},
        ],
    },
    "doc": {
        "name": "📄 डॉक्यूमेंट के काम",
        "desc": "टाइपिंग, रिज्यूमे, ईमेल आईडी आदि",
        "services": [
            {"id": "typing",          "name": "डॉक्यूमेंट टाइपिंग (1 पेज)",   "price": 20,  "emoji": "⌨️", "docs": "हाथ से लिखा हुआ कॉपी या पुरानी फाइल"},
            {"id": "resume",          "name": "रिज्यूमे (CV) बनाना",         "price": 100, "emoji": "📃", "docs": "पढ़ाई की डिटेल, फोटो, काम का अनुभव"},
            {"id": "email_create",    "name": "ईमेल आईडी बनाना",             "price": 30,  "emoji": "📧", "docs": "मोबाइल नंबर, नाम, जन्मतिथि"},
            {"id": "naukri_profile",  "name": "Naukri.com प्रोफाइल",         "price": 100, "emoji": "🔍", "docs": "रिज्यूमे, पढ़ाई की डिटेल"},
        ],
    },
    "bill": {
        "name": "💡 बिल पेमेंट और रिचार्ज",
        "desc": "मोबाइल, DTH, बिजली बिल, पानी बिल",
        "services": [
            {"id": "mobile_recharge",   "name": "मोबाइल रिचार्ज",              "price": 10, "emoji": "📱", "docs": "मोबाइल नंबर और राशि"},
            {"id": "dth_recharge",      "name": "DTH रिचार्ज",                 "price": 20, "emoji": "📡", "docs": "कस्टमर ID या रजिस्टर्ड नंबर"},
            {"id": "electricity_bill",  "name": "बिजली बिल पेमेंट",            "price": 20, "emoji": "💡", "docs": "कंज्यूमर नंबर या पुराना बिल"},
            {"id": "gas_bill",          "name": "गैस बिल पेमेंट",              "price": 20, "emoji": "🔥", "docs": "कंज्यूमर नंबर"},
            {"id": "money_transfer",    "name": "पैसे भेजें (Money Transfer)",  "price": 50, "emoji": "💸", "docs": "बैंक डिटेल या मोबाइल नंबर"},
        ],
    },
    "ticket": {
        "name": "🎫 टिकट बुकिंग",
        "desc": "ट्रेन, बस, फ्लाइट, मूवी टिकट",
        "services": [
            {"id": "train_ticket",  "name": "ट्रेन टिकट (IRCTC)", "price": 50,  "emoji": "🚆", "docs": "आधार/आईडी कार्ड, यात्रा की डिटेल"},
            {"id": "bus_ticket",    "name": "बस टिकट बुकिंग",   "price": 30,  "emoji": "🚌", "docs": "यात्री का नाम, उम्र, मोबाइल"},
            {"id": "flight_ticket", "name": "फ्लाइट टिकट बुकिंग","price": 100, "emoji": "✈️", "docs": "आईडी प्रूफ, यात्रा की तारीख"},
        ],
    },
    "computer": {
        "name": "💻 कंप्यूटर के काम",
        "desc": "सॉफ्टवेयर, एंटीवायरस, डेटा रिकवरी",
        "services": [
            {"id": "windows_install",  "name": "विंडोज इंस्टॉल",        "price": 300, "emoji": "🪟", "docs": "लैपटॉप/कंप्यूटर (कैफे लेकर आएं)"},
            {"id": "antivirus",        "name": "एंटीवायरस इंस्टॉल",     "price": 200, "emoji": "🛡️", "docs": "लैपटॉप/कंप्यूटर"},
            {"id": "data_recovery",    "name": "डेटा रिकवरी",          "price": 500, "emoji": "💿", "docs": "हार्ड डिस्क / पेन ड्राइव"},
            {"id": "printer_setup",    "name": "प्रिंटर सेटअप",         "price": 100, "emoji": "🖨️", "docs": "प्रिंटर और लैपटॉप"},
        ],
    },
    "advanced": {
        "name": "⚡ एडवांस काम",
        "desc": "GST, ITR, MSME, डिजिटल सिग्नेचर",
        "services": [
            {"id": "gst_reg",          "name": "GST रजिस्ट्रेशन",         "price": 500,  "emoji": "🧾", "docs": "आधार, पैन, फोटो, बैंक पासबुक"},
            {"id": "itr_filing",       "name": "ITR (इनकम टैक्स) फाइलिंग", "price": 500,  "emoji": "📊", "docs": "पैन, आधार, बैंक स्टेटमेंट, फॉर्म 16"},
            {"id": "msme_reg",         "name": "MSME (उद्यम) रजिस्ट्रेशन", "price": 500,  "emoji": "🏭", "docs": "आधार कार्ड, पैन कार्ड"},
            {"id": "digital_sig",      "name": "डिजिटल सिग्नेचर",        "price": 1000, "emoji": "🖊️", "docs": "पैन, आधार, मोबाइल, ईमेल, वीडियो (वेरिफिकेशन के लिए)"},
            {"id": "photo_edit",       "name": "फोटो एडिटिंग",            "price": 50,   "emoji": "🎨", "docs": "ओरिजिनल फोटो, क्या बदलना है"},
            {"id": "video_edit",       "name": "वीडियो एडिटिंग",          "price": 100,  "emoji": "🎥", "docs": "वीडियो क्लिप, क्या करना है"},
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

def get_reply_keyboard():
    # नीचे हमेशा दिखने वाले बटन
    reply_keyboard = [
        [KeyboardButton("🛍️ सर्विस मेनू")],
        [KeyboardButton("🆘 मदद"), KeyboardButton("📞 संपर्क करें")]
    ]
    return ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, is_persistent=True)

# ---------------- Handlers ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = await update.message.reply_text("🤖 <b>बॉट शुरू हो रहा है...</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.4)
    await msg.edit_text("🔧 <b>सर्विस लोड हो रही हैं...</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.4)
    await msg.edit_text("✨ <b>बस थोड़ा सा और इंतज़ार करें...</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.4)

    total = sum(len(c["services"]) for c in CATEGORIES.values())
    welcome = (
        f"🙏 <b>नमस्ते, {user.first_name}!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏪 <b>{PAYEE_NAME}</b> में आपका स्वागत है!\n\n"
        f"✅ <b>{total}+</b> सर्विसेज उपलब्ध हैं\n"
        f"💳 <b>UPI पेमेंट</b> — इंस्टेंट QR कोड\n"
        f"⚡ <b>तेज़ काम</b> — 100% भरोसेमंद\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 <b>नीचे से कोई कैटेगरी चुनें:</b>"
    )
    await msg.edit_text(welcome, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML)
    await update.message.reply_text("👆 आप नीचे दिए गए बटन से भी मेनू खोल सकते हैं।", reply_markup=get_reply_keyboard())


async def show_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = query.data.replace("cat_", "")
    cat = CATEGORIES.get(cat_id)
    if not cat:
        await query.edit_message_text("❌ कैटेगरी नहीं मिली।")
        return

    await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(0.3)

    keyboard = []
    for svc in cat["services"]:
        price_text = f"₹{svc['price']}" if svc["price"] > 0 else "फ्री जानकारी"
        keyboard.append([InlineKeyboardButton(
            f"{svc['emoji']} {svc['name']} — {price_text}",
            callback_data=f"svc_{svc['id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 मुख्य मेनू", callback_data="back_main")])

    text = (
        f"{cat['name']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{cat['desc']}</i>\n\n"
        f"👇 <b>सर्विस चुनें:</b>"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def show_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    svc_id = query.data.replace("svc_", "")
    svc = find_service(svc_id)
    if not svc:
        await query.edit_message_text("❌ सर्विस नहीं मिली।")
        return
    context.user_data["selected_service"] = svc

    keyboard = [
        [InlineKeyboardButton("💳 अब पेमेंट करें", callback_data="pay_now")],
        [InlineKeyboardButton("🔙 मुख्य मेनू", callback_data="back_main")],
    ]
    
    # डॉक्यूमेंट्स दिखाने का लॉजिक
    docs_text = ""
    if svc.get("docs"):
        docs_text = f"\n📄 <b>ज़रूरी डॉक्यूमेंट्स:</b>\n<code>{svc['docs']}</code>\n"

    text = (
        f"{svc['emoji']} <b>{svc['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>कीमत:</b> ₹{svc['price']}\n"
        f"{docs_text}"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 पेमेंट करने के लिए <b>अब पेमेंट करें</b> दबाएं।\n"
        f"QR स्कैन करके पैसे भेजें, और स्क्रीनशॉट यहाँ भेज दें।"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def pay_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    svc = context.user_data.get("selected_service")
    if not svc:
        await query.edit_message_text("⚠️ पहले सर्विस चुनें। /start दबाएं")
        return

    chat_id = query.message.chat_id
    msg_id = query.message.message_id

    await query.edit_message_text("⏳ <b>QR कोड बन रहा है...</b>", parse_mode=ParseMode.HTML)
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
            f"💳 <b>पेमेंट की जानकारी</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{svc['emoji']} <b>सर्विस:</b> {svc['name']}\n"
            f"💰 <b>पैसे:</b> ₹{amount}\n"
            f"🆔 <b>UPI ID:</b> <code>{UPI_ID}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📸 <b>QR स्कैन करके पेमेंट करें</b>\n"
            f"पेमेंट के बाद अपना <b>स्क्रीनशॉट यहाँ भेजें</b>।\n"
            f"चेक करने के बाद आपका काम शुरू हो जाएगा। ✅"
        )
        await context.bot.send_photo(chat_id=chat_id, photo=buf, caption=caption, parse_mode=ParseMode.HTML)
    except Exception:
        logger.exception("QR error")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ QR कोड नहीं बन पाया। एडमिन से बात करें।"
        )


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("selected_service", None)
    total = sum(len(c["services"]) for c in CATEGORIES.values())
    text = (
        f"🏪 <b>{PAYEE_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>{total}+</b> सर्विसेज उपलब्ध हैं\n"
        f"💳 <b>UPI पेमेंट</b> — इंस्टेंट QR कोड\n\n"
        f"👇 <b>कैटेगरी चुनें:</b>"
    )
    await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML)


async def payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    svc = context.user_data.get("selected_service")
    service_name = svc["name"] if svc else "पता नहीं"
    amount = svc["price"] if svc else "N/A"

    admin_text = (
        f"🔔 <b>नया पेमेंट स्क्रीनशॉट</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>नाम:</b> {user.full_name}\n"
        f"🆔 <b>यूजर ID:</b> <code>{user.id}</code>\n"
        f"📱 <b>यूजरनेम:</b> @{user.username or 'N/A'}\n"
        f"🛠️ <b>सर्विस:</b> {service_name}\n"
        f"💰 <b>पैसे:</b> ₹{amount}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    admin_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ एप्रूव करें", callback_data=f"approve_{user.id}"),
        InlineKeyboardButton("❌ रिजेक्ट करें",  callback_data=f"reject_{user.id}"),
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
        f"✅ <b>स्क्रीनशॉट मिल गया है!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛠️ <b>सर्विस:</b> {service_name}\n"
        f"💰 <b>पैसे:</b> ₹{amount}\n\n"
        f"⏳ एडमिन चेक करके आपको अपडेट देगा।\n"
        f"धन्यवाद! 🙏",
        parse_mode=ParseMode.HTML,
    )
    context.user_data.pop("selected_service", None)
    
    # पेमेंट के बाद वापस मेनू का ऑप्शन
    await update.message.reply_text(
        "क्या आपको कोई और काम है? नीचे मेनू से चुनें 👇",
        reply_markup=main_menu_keyboard()
    )


async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("❌ आप एडमिन नहीं हैं", show_alert=True)
        return
    await query.answer()
    action, uid = query.data.split("_", 1)
    uid = int(uid)

    if action == "approve":
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"✅ <b>पेमेंट मिल गया!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"आपका पेमेंट कन्फर्म हो गया है।\n"
                    f"अब आपका काम जल्दी शुरू होगा। 🚀\n\n"
                    f"धन्यवाद! 🙏"
                ),
                parse_mode=ParseMode.HTML,
            )
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ यूजर <code>{uid}</code> को मैसेज भेज दिया गया है।", parse_mode=ParseMode.HTML)
        except Exception as e:
            await query.message.reply_text(f"❌ यूजर को मैसेज नहीं गया: {e}")
    else:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"❌ <b>पेमेंट रिजेक्ट हो गया</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"आपका पेमेंट वेरिफाई नहीं हो पाया।\n"
                    f"एडमिन से बात करें या दोबारा स्क्रीनशॉट भेजें।"
                ),
                parse_mode=ParseMode.HTML,
            )
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"❌ यूजर <code>{uid}</code> को रिजेक्ट मैसेज भेज दिया गया है।", parse_mode=ParseMode.HTML)
        except Exception as e:
            await query.message.reply_text(f"❌ यूजर को मैसेज नहीं गया: {e}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"🆘 <b>मदद (Help)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"/start — मुख्य मेनू\n"
        f"/help — मदद का मैसेज\n"
        f"/cancel — काम रोकें\n\n"
        f"💡 <b>बॉट कैसे चलाएं:</b>\n"
        f"1️⃣ कैटेगरी चुनें\n"
        f"2️⃣ सर्विस चुनें\n"
        f"3️⃣ 'पेमेंट करें' दबाएं\n"
        f"4️⃣ QR स्कैन करके पैसे भेजें\n"
        f"5️⃣ स्क्रीनशॉट भेजें\n"
        f"6️⃣ एडमिन चेक करेगा\n\n"
        f"📞 <b>कॉन्टैक्ट:</b> {PAYEE_NAME}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("selected_service", None)
    await update.message.reply_text(
        "🔄 <b>काम रद्द कर दिया गया है।</b>\n\nनीचे मेनू से दोबारा शुरू करें।",
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.HTML,
    )


# नया टेक्स्ट हैंडलर (बटन और रैंडम मैसेज के लिए)
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    
    if "सर्विस मेनू" in text:
        total = sum(len(c["services"]) for c in CATEGORIES.values())
        await update.message.reply_text(
            f"🏪 <b>{PAYEE_NAME}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>{total}+</b> सर्विसेज उपलब्ध हैं\n"
            f"👇 <b>कैटेगरी चुनें:</b>",
            reply_markup=main_menu_keyboard(),
            parse_mode=ParseMode.HTML
        )
    elif "मदद" in text:
        await help_command(update, context)
    elif "संपर्क करें" in text:
        await update.message.reply_text(
            f"📞 <b>संपर्क करें</b>\n\n"
            f"🏪 <b>कैफे का नाम:</b> {PAYEE_NAME}\n"
            f"🆔 <b>UPI ID:</b> <code>{UPI_ID}</code>\n\n"
            f"किसी भी सवाल के लिए मैसेज करें।",
            parse_mode=ParseMode.HTML
        )
    else:
        # अगर कोई कुछ और टाइप करे
        await update.message.reply_text(
            f"नमस्ते {user.first_name}! मैं आपकी क्या मदद कर सकता हूँ?\n\n"
            f"काम करवाने के लिए नीचे मेनू से चुनें या <b>🛍️ सर्विस मेनू</b> बटन दबाएं।",
            reply_markup=main_menu_keyboard(),
            parse_mode=ParseMode.HTML
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
    
    # फोटो/इमेज हैंडलर
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, payment_proof))
    
    # टेक्स्ट हैंडलर
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
