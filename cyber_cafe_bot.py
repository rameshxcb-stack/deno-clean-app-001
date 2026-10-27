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
# 🛠️ सर्विस और डॉक्यूमेंट्स की लिस्ट
# ------------------------------------------------------------
CATEGORIES = {
    "pan": {
        "name": "💳 पैन कार्ड सर्विस",
        "desc": "नया पैन, करेक्शन, बिजनेस पैन, डिटेल्स",
        "services": [
            {"id": "pan_new_aadhaar", "name": "नया पैन (सिर्फ आधार से)", "price": 200, "emoji": "💳", "docs": "आधार कार्ड, फोटो, हस्ताक्षर, मोबाइल नंबर, ईमेल ID\n(आधार में मोबाइल लिंक होना जरूरी है, OTP लगेगा)"},
            {"id": "pan_new_metric", "name": "नया पैन (मैट्रिक/जन्म प्रमाण से)", "price": 200, "emoji": "🎓", "docs": "आधार कार्ड, फोटो, हस्ताक्षर, मोबाइल नंबर, ईमेल ID\n(आधार OTP नहीं लगेगा, सीधे बन जाएगा)"},
            {"id": "pan_correct_name", "name": "पैन करेक्शन (पूरा नाम/पिता का नाम)", "price": 1500, "emoji": "✏️", "docs": "आधार कार्ड, पुराना पैन, फोटो, हस्ताक्षर, मोबाइल, ईमेल, जन्म/मैट्रिक प्रमाण पत्र\n(आधार OTP जरूरी है)"},
            {"id": "pan_correct_other", "name": "पैन करेक्शन (छोटा सुधार)", "price": 250, "emoji": "📝", "docs": "आधार कार्ड, पुराना पैन, फोटो, हस्ताक्षर, मोबाइल नंबर, ईमेल ID\n(आधार OTP जरूरी है)"},
            {"id": "pan_single_letter", "name": "सिंगल लेटर पैन (बिना जन्म प्रमाण)", "price": 1500, "emoji": "🔠", "docs": "आधार PDF, फोटो, मोबाइल, ईमेल, हस्ताक्षर (या अंगूठा), पिता का नाम\n(OTP आधार में लिंक मोबाइल पर आएगा)"},
            {"id": "pan_business", "name": "बिजनेस पैन कार्ड", "price": 2000, "emoji": "🏢", "docs": "बिजनेस का नाम, खुलने की तारीख, पूरा पता, मोबाइल, ईमेल, मालिक का आधार और पैन\n(समय: 7 से 10 दिन)"},
            {"id": "pan_lost", "name": "खोया हुआ पैन (आधार से)", "price": 100, "emoji": "🔍", "docs": "आधार कार्ड नंबर\n(2 मिनट में पैन मिल जाएगा)"},
            {"id": "pan_details", "name": "पैन कार्ड की जानकारी", "price": 100, "emoji": "ℹ️", "docs": "पैन कार्ड नंबर\n(नंबर है लेकिन डिटेल याद नहीं है तो)"},
            {"id": "pan_find_mobile", "name": "मोबाइल से पैन खोजें", "price": 150, "emoji": "📱", "docs": "मोबाइल नंबर\n(मोबाइल याद है, पैन नहीं)"},
            {"id": "pan_find_aadhaar", "name": "पैन से आधार खोजें", "price": 350, "emoji": "🆔", "docs": "पैन कार्ड नंबर\n(पैन है, आधार नंबर याद नहीं है)"}
        ]
    },
    "aadhaar": {
        "name": "🆔 आधार कार्ड सर्विस",
        "desc": "पता बदलें, पिता का नाम, LMS सर्टिफिकेट",
        "services": [
            {"id": "aadhaar_address", "name": "आधार में पता बदलें", "price": 300, "emoji": "🏠", "docs": "आधार OTP लगेगा। नया पता अंग्रेजी/हिंदी में भेजें:\nVill/गाँव, Post/डाकघर, PS/थाना, Dist/जिला, State/राज्य, Pin/पिन कोड\n(गारंटी के साथ - अपडेट नहीं हुआ तो रिफंड या फ्री में दोबारा)"},
            {"id": "aadhaar_father", "name": "आधार में पिता का नाम बदलें", "price": 250, "emoji": "👨‍🦳", "docs": "पिता के आधार में मोबाइल लिंक हो + आवेदक के आधार में भी। दोनों पर OTP जाएगा।\n(पिता के आधार वाला नाम ही आपके आधार में आएगा)"},
            {"id": "aadhaar_lms", "name": "आधार LMS सर्टिफिकेट", "price": 1500, "emoji": "📄", "docs": "नाम, मोबाइल नंबर, ईमेल ID, राज्य, जिला, आधार नंबर"},
            {"id": "aadhaar_ration", "name": "राशन कार्ड से आधार नंबर", "price": 400, "emoji": "🍚", "docs": "सिर्फ राशन कार्ड नंबर भेजें।\n(पूरे परिवार का मिलेगा, नाम राशन कार्ड में होना चाहिए और आखिरी 4 अंक पता हो)"}
        ]
    },
    "tax": {
        "name": "💼 टैक्स और बिजनेस",
        "desc": "ITR, GST, MSME, RC PDF",
        "services": [
            {"id": "itr_filing", "name": "ITR फाइलिंग (शुरुआती ₹1000)", "price": 1000, "emoji": "📊", "docs": "आधार, पैन, खाता नंबर, IFSC कोड, बैंक का नाम, मोबाइल, OTP\n\n💰 फीस:\n• ITR-1: ₹1000\n• ITR-2: ₹1500\n• ITR-3: ₹2000\n• ITR-4: ₹3000"},
            {"id": "gst_reg", "name": "GST रजिस्ट्रेशन (पेपर हों तो ₹2000)", "price": 2000, "emoji": "🧾", "docs": "आधार, पैन, फोटो, ईमेल, मोबाइल, बिजनेस का नाम/पता, बिजली बिल या रेंट एग्रीमेंट\n\n💰 फीस:\n• पेपर नहीं है तो: ₹3000\n• पेपर (रेंट/बिल) है तो: ₹2000\n⚡ केवल 1 घंटे में जीएसटी नंबर मिल जाएगा!"},
            {"id": "msme_reg", "name": "MSME / उद्यम रजिस्ट्रेशन", "price": 200, "emoji": "🏭", "docs": "आधार (दोनों साइड), पैन, बैंक अकाउंट नंबर व IFSC, आधार लिंक मोबाइल, ईमेल, फर्म का नाम और पता\n(समय: तुरंत)"},
            {"id": "rc_pdf", "name": "गाड़ी नंबर से RC PDF", "price": 100, "emoji": "🚗", "docs": "गाड़ी का नंबर भेजें"}
        ]
    },
    "print": {
        "name": "🖨️ प्रिंट और फोटोकॉपी",
        "desc": "रंगीन/ब्लैक एंड व्हाइट प्रिंट, स्कैन",
        "services": [
            {"id": "print_bw",       "name": "ब्लैक एंड व्हाइट प्रिंट (1 पेज)", "price": 2,   "emoji": "📄", "docs": "PDF, वर्ड फाइल या फोटो"},
            {"id": "print_color",    "name": "रंगीन प्रिंट (1 पेज)",           "price": 10,  "emoji": "🌈", "docs": "PDF, वर्ड फाइल या फोटो"},
            {"id": "photocopy",      "name": "फोटोकॉपी (1 पेज)",               "price": 1,   "emoji": "📑", "docs": "ओरिजिनल डॉक्यूमेंट"},
            {"id": "scan",           "name": "स्कैनिंग (1 पेज)",               "price": 5,   "emoji": "📷", "docs": "ओरिजिनल डॉक्यूमेंट"},
            {"id": "lam_a4",         "name": "लेमिनेशन A4",                    "price": 30,  "emoji": "🪪", "docs": "A4 साइज का डॉक्यूमेंट"},
            {"id": "passport_photo", "name": "पासपोर्ट साइज फोटो (8 कॉपी)",    "price": 50,  "emoji": "👤", "docs": "कुछ नहीं चाहिए, बस आना है"}
        ]
    },
    "gov": {
        "name": "🏛️ अन्य सरकारी काम",
        "desc": "वोटर आईडी, ड्राइविंग लाइसेंस आदि",
        "services": [
            {"id": "voter_new",      "name": "नया वोटर आईडी",                  "price": 100, "emoji": "🗳️", "docs": "आधार कार्ड, फोटो, एड्रेस प्रूफ"},
            {"id": "dl_learner",     "name": "ड्राइविंग लाइसेंस (लर्निंग)",    "price": 500, "emoji": "🚗", "docs": "आधार कार्ड, फोटो, मेडिकल फॉर्म"},
            {"id": "dl_permanent",   "name": "ड्राइविंग लाइसेंस (पक्का)",      "price": 800, "emoji": "🚙", "docs": "लर्निंग लाइसेंस, आधार, फोटो"},
            {"id": "birth_cert",     "name": "जन्म प्रमाण पत्र",               "price": 200, "emoji": "👶", "docs": "अस्पताल की पर्ची, माता-पिता का आधार"},
            {"id": "eshram",         "name": "ई-श्रम कार्ड",                   "price": 50,  "emoji": "👷", "docs": "आधार कार्ड, बैंक पासबुक"}
        ]
    }
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
    
    # नया बटन: अन्य काम के लिए
    keyboard.append([InlineKeyboardButton("📝 अन्य काम (कोई और सर्विस)", callback_data="other_service")])
    
    return InlineKeyboardMarkup(keyboard)

def get_reply_keyboard():
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
            f"पेमेंट के बाद अपना <b>स्क्रीनशॉट यहाँ भेजें</b> और अपने डॉक्यूमेंट्स भी भेज दें।\n"
            f"चेक करने के बाद आपका काम शुरू हो जाएगा। ✅"
        )
        await context.bot.send_photo(chat_id=chat_id, photo=buf, caption=caption, parse_mode=ParseMode.HTML)
    except Exception:
        logger.exception("QR error")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ QR कोड नहीं बन पाया। एडमिन से बात करें।"
        )

# ------------------------------------------------------------
# नया हैंडलर: अन्य काम के लिए
# ------------------------------------------------------------
async def ask_other_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # यूजर को स्टेट में डाल दो कि वो कस्टम रिक्वेस्ट टाइप करने वाला है
    context.user_data['awaiting_custom_request'] = True
    
    await query.edit_message_text(
        "📝 <b>अन्य काम (Other Service)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "अगर आपको कोई ऐसा काम करवाना है जो लिस्ट में नहीं है, तो आप यहाँ लिख सकते हैं।\n\n"
        "👇 <b>कृपया अपना काम टाइप करके भेजें:</b>\n"
        "<i>(जैसे: 'मुझे एक वीडियो एडिट करवाना है' या 'मुझे कॉलेज का फॉर्म भरना है')</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 मुख्य मेनू", callback_data="back_main")]])
    )


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("selected_service", None)
    # अगर कस्टम रिक्वेस्ट का स्टेट चालू था तो उसे बंद कर दो
    context.user_data.pop("awaiting_custom_request", None) 
    
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
        f"🔔 <b>नया पेमेंट या डॉक्यूमेंट</b>\n"
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
        f"✅ <b>स्क्रीनशॉट/डॉक्यूमेंट मिल गया है!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛠️ <b>सर्विस:</b> {service_name}\n"
        f"💰 <b>पैसे:</b> ₹{amount}\n\n"
        f"⏳ एडमिन चेक करके आपको अपडेट देगा।\n"
        f"धन्यवाद! 🙏",
        parse_mode=ParseMode.HTML,
    )
    context.user_data.pop("selected_service", None)
    
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
                    f"✅ <b>पेमेंट/डॉक्यूमेंट मिल गया!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"आपका काम कन्फर्म हो गया है।\n"
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
                    f"❌ <b>रिजेक्ट हो गया</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"आपका पेमेंट या डॉक्यूमेंट वेरिफाई नहीं हो पाया।\n"
                    f"एडमिन से बात करें या दोबारा भेजें।"
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
        f"5️⃣ स्क्रीनशॉट और डॉक्यूमेंट्स भेजें\n"
        f"6️⃣ एडमिन चेक करेगा\n\n"
        f"📞 <b>कॉन्टैक्ट:</b> {PAYEE_NAME}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("selected_service", None)
    context.user_data.pop("awaiting_custom_request", None)
    await update.message.reply_text(
        "🔄 <b>काम रद्द कर दिया गया है।</b>\n\nनीचे मेनू से दोबारा शुरू करें।",
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.HTML,
    )


# नया टेक्स्ट हैंडलर (बटन, कस्टम रिक्वेस्ट और रैंडम मैसेज के लिए)
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    
    # 1. चेक करें कि क्या यूजर 'अन्य काम' के लिए मैसेज टाइप कर रहा है?
    if context.user_data.get('awaiting_custom_request'):
        context.user_data['awaiting_custom_request'] = False # स्टेट रीसेट करें
        
        admin_text = (
            f"🔔 <b>नया कस्टम रिक्वेस्ट (Other Service)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>नाम:</b> {user.full_name}\n"
            f"🆔 <b>यूजर ID:</b> <code>{user.id}</code>\n"
            f"📱 <b>यूजरनेम:</b> @{user.username or 'N/A'}\n"
            f"💬 <b>काम:</b> {text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_text, parse_mode=ParseMode.HTML)
            await update.message.reply_text(
                "✅ <b>आपका मैसेज एडमिन को भेज दिया गया है!</b>\n\n"
                "एडमिन जल्द ही आपसे संपर्क करके रेट और डिटेल्स बताएगा।\n"
                "धन्यवाद! 🙏",
                reply_markup=main_menu_keyboard(),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Failed to send custom request to admin: {e}")
            await update.message.reply_text("❌ मैसेज भेजने में दिक्कत आई। कृपया बाद में कोशिश करें।")
        return

    # 2. अगर नीचे वाले बटन दबाए गए हैं
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
        # 3. अगर कोई कुछ और टाइप करे
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
    app.add_handler(CallbackQueryHandler(ask_other_service, pattern="^other_service$")) # नया हैंडलर
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^(approve|reject)_"))
    
    # फोटो/इमेज हैंडलर
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, payment_proof))
    
    # टेक्स्ट हैंडलर
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
