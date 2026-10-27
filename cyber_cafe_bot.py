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
# 🛠️ सर्विस और जरूरी कागजात की लिस्ट (2-लाइन बटन नाम के साथ)
# ------------------------------------------------------------
CATEGORIES = {
    "pan": {
        "name": "💳 पैन कार्ड का काम",
        "desc": "नया पैन, गलती सुधारना, पैन की जानकारी",
        "services": [
            {"id": "pan_new_aadhaar", "name": "नया पैन (सिर्फ आधार से)", "btn_name": "नया पैन\n(सिर्फ आधार से)", "price": 200, "emoji": "💳", "docs": "📄 आधार कार्ड\n🖼️ फोटो\n✍️ हस्ताक्षर (साइन)\n📱 मोबाइल नंबर\n📧 ईमेल (अगर है तो)\n\n⚠️ <i>आधार में मोबाइल लिंक होना जरूरी है, OTP आएगा।</i>"},
            {"id": "pan_new_metric", "name": "नया पैन (मार्कशीट/जन्म प्रमाण से)", "btn_name": "नया पैन\n(जन्म प्रमाण से)", "price": 200, "emoji": "🎓", "docs": "📄 आधार कार्ड\n🖼️ फोटो\n✍️ हस्ताक्षर (साइन)\n📱 मोबाइल नंबर\n📧 ईमेल (अगर है तो)\n\n✅ <i>इसमें आधार का OTP नहीं लगेगा।</i>"},
            {"id": "pan_correct_name", "name": "पैन में नाम/पिता का नाम बदलना", "btn_name": "नाम/पिता का नाम\nबदलना", "price": 1500, "emoji": "✏️", "docs": "📄 आधार कार्ड\n💳 पुराना पैन कार्ड\n🖼️ फोटो, साइन, मोबाइल, ईमेल\n📜 जन्म प्रमाण पत्र या मार्कशीट\n\n⚠️ <i>आधार OTP जरूरी है।</i>"},
            {"id": "pan_correct_other", "name": "पैन में छोटी गलती सुधारना", "btn_name": "छोटी गलती\nसुधारना", "price": 250, "emoji": "📝", "docs": "📄 आधार कार्ड\n💳 पुराना पैन कार्ड\n🖼️ फोटो, साइन, मोबाइल, ईमेल\n\n⚠️ <i>आधार OTP जरूरी है।</i>"},
            {"id": "pan_single_letter", "name": "सिंगल लेटर वाला पैन (जैसे P Sonu)", "btn_name": "सिंगल लेटर पैन\n(जैसे P Sonu)", "price": 1500, "emoji": "🔠", "docs": "📄 आधार PDF\n🖼️ फोटो\n📱 मोबाइल, ईमेल\n✍️ हस्ताक्षर (या अंगूठा)\n👨‍🦳 पिता का नाम"},
            {"id": "pan_business", "name": "बिजनेस पैन कार्ड", "btn_name": "बिजनेस पैन\nकार्ड", "price": 2000, "emoji": "🏢", "docs": "🏪 दुकान का नाम\n📅 खुलने की तारीख\n📍 पूरा पता\n📱 मोबाइल और 📧 ईमेल\n🪪 मालिक का आधार और पैन\n\n⏳ <i>समय: 7 से 10 दिन</i>"},
            {"id": "pan_lost", "name": "पैन कार्ड खो गया है (नंबर पता करना)", "btn_name": "पैन खो गया है\n(नंबर पता करें)", "price": 100, "emoji": "🔍", "docs": "📄 आधार कार्ड नंबर\n\n⚡ <i>2 मिनट में पैन नंबर मिल जाएगा।</i>"},
            {"id": "pan_details", "name": "पैन कार्ड की पूरी जानकारी", "btn_name": "पैन की पूरी\nजानकारी", "price": 100, "emoji": "ℹ️", "docs": "💳 पैन कार्ड नंबर"},
            {"id": "pan_find_mobile", "name": "मोबाइल नंबर से पैन खोजना", "btn_name": "मोबाइल से पैन\nखोजना", "price": 150, "emoji": "📱", "docs": "📱 मोबाइल नंबर"},
            {"id": "pan_find_aadhaar", "name": "पैन से आधार नंबर खोजना", "btn_name": "पैन से आधार\nखोजना", "price": 350, "emoji": "🆔", "docs": "💳 पैन कार्ड नंबर"}
        ]
    },
    "aadhaar": {
        "name": "🆔 आधार कार्ड का काम",
        "desc": "पता बदलना, पिता का नाम, LMS सर्टिफिकेट",
        "services": [
            {"id": "aadhaar_address", "name": "आधार में पता बदलवाना", "btn_name": "आधार में पता\nबदलवाना", "price": 300, "emoji": "🏠", "docs": "आधार का OTP लगेगा। नया पता अंग्रेजी या हिंदी में भेजें:\nगाँव, डाकघर, थाना, जिला, राज्य, पिन कोड।\n\n✅ <i>गारंटी के साथ - पता अपडेट नहीं हुआ तो पैसे वापस या फ्री में दोबारा।</i>"},
            {"id": "aadhaar_father", "name": "आधार में पिता का नाम बदलवाना", "btn_name": "पिता का नाम\nबदलवाना", "price": 250, "emoji": "👨‍🦳", "docs": "पिता के आधार में मोबाइल जुड़ा हो + आपके आधार में भी। दोनों पर OTP आएगा।\n\n⚠️ <i>पिता के आधार वाला नाम ही आपके आधार में आएगा।</i>"},
            {"id": "aadhaar_lms", "name": "आधार LMS सर्टिफिकेट", "btn_name": "LMS सर्टिफिकेट\nबनवाना", "price": 1500, "emoji": "📄", "docs": "🖊️ नाम, 📱 मोबाइल नंबर, 📧 ईमेल ID, 🌍 राज्य, 🏙️ जिला, 🆔 आधार नंबर"},
            {"id": "aadhaar_ration", "name": "राशन कार्ड से परिवार का आधार नंबर", "btn_name": "राशन से परिवार\nका आधार नंबर", "price": 400, "emoji": "🍚", "docs": "सिर्फ राशन कार्ड नंबर भेजें।\n\n⚠️ <i>नाम राशन कार्ड में होना चाहिए और आखिरी 4 अंक पता होना चाहिए।</i>"}
        ]
    },
    "ration": {
        "name": "🍚 राशन कार्ड का काम",
        "desc": "नया कार्ड, सदस्य जोड़ना, दूसरे काम",
        "services": [
            {"id": "ration_new", "name": "नया राशन कार्ड बनवाना", "btn_name": "नया राशन कार्ड\nबनवाना", "price": 200, "emoji": "🆕", "docs": "📄 सभी सदस्यों का आधार (उम्र 5 साल से ज्यादा)\n📄 जाति प्रमाण पत्र (अगर SC/ST हैं तो)\n📱 मोबाइल नंबर (आधार से जुड़ा हो)\n🏦 बैंक पासबुक (अगर है तो)\n🏠 घर की फोटो"},
            {"id": "ration_add_member", "name": "राशन कार्ड में नया सदस्य जोड़ना", "btn_name": "नया सदस्य\nजोड़ना", "price": 100, "emoji": "➕", "docs": "📄 पुराना राशन कार्ड\n📄 नए सदस्य का आधार कार्ड\n📄 मुखिया का आधार कार्ड (मोबाइल लिंक हो, OTP आएगा)"},
            {"id": "ration_other", "name": "राशन कार्ड का दूसरा काम", "btn_name": "दूसरा काम\n(एडमिन से पूछें)", "price": 0, "emoji": "⚙️", "docs": "राशन कार्ड से जुड़े दूसरे कामों के लिए कृपया एडमिन से संपर्क करें।", "contact_admin": True}
        ]
    },
    "certificates": {
        "name": "📜 जाति, निवास और आय प्रमाण पत्र",
        "desc": "जाति, निवास, आय और NCL सर्टिफिकेट",
        "services": [
            {"id": "caste_cert", "name": "जाति प्रमाण पत्र", "btn_name": "जाति प्रमाण\nपत्र", "price": 150, "emoji": "📜", "docs": "📄 आधार कार्ड\n📄 खतियान\n📄 रसीद\n📝 फॉर्म (एडमिन से लें, मुखिया का साइन जरूरी है)\n\n⚠️ <i>लड़की की शादी हो गई है, तो उसका जाति प्रमाण पत्र उसके पापा के घर के कागजों से बनेगा।</i>"},
            {"id": "resident_cert", "name": "निवास प्रमाण पत्र", "btn_name": "निवास प्रमाण\nपत्र", "price": 150, "emoji": "🏠", "docs": "📄 आधार कार्ड\n📄 खतियान\n📄 रसीद\n📝 फॉर्म (एडमिन से लें, मुखिया का साइन जरूरी है)\n\n⚠️ <i>लड़की की शादी हो गई है, तो उसका निवास प्रमाण पत्र उसके पति के घर के कागजों से बनेगा।</i>"},
            {"id": "income_cert", "name": "आय प्रमाण पत्र", "btn_name": "आय प्रमाण\nपत्र", "price": 150, "emoji": "💰", "docs": "📄 आधार कार्ड\n📄 रसीद (अगर है तो)\n📄 शपथ पत्र (Affidavit)\n📝 फॉर्म (एडमिन से लें, मुखिया का साइन जरूरी है)"},
            {"id": "ncl_cert", "name": "NCL सर्टिफिकेट", "btn_name": "NCL सर्टिफिकेट\n(एडमिन से पूछें)", "price": 0, "emoji": "📑", "docs": "NCL सर्टिफिकेट बनवाने के लिए कृपया एडमिन से संपर्क करें।", "contact_admin": True}
        ]
    },
    "voter": {
        "name": "🗳️ वोटर आईडी का काम",
        "desc": "नया कार्ड, गलती सुधारना, पीडीएफ और मोबाइल जोड़ना",
        "services": [
            {"id": "voter_new_card", "name": "नया वोटर आईडी कार्ड", "btn_name": "नया वोटर\nआईडी कार्ड", "price": 100, "emoji": "🆕", "docs": "📄 आधार कार्ड\n📱 मोबाइल नंबर\n🖼️ फोटो\n📄 मम्मी-पापा या पति/पत्नी का वोटर कार्ड\n\n⚠️ <i>आधार में मोबाइल नंबर जुड़ा होना जरूरी है।</i>"},
            {"id": "voter_correction", "name": "वोटर कार्ड में गलती सुधारना", "btn_name": "गलती\nसुधारना", "price": 100, "emoji": "✏️", "docs": "📄 आधार कार्ड\n📱 मोबाइल नंबर\n🖼️ फोटो\n\n⚠️ <i>आधार में मोबाइल नंबर जुड़ा होना जरूरी है।</i>"},
            {"id": "voter_other", "name": "पीडीएफ, नाम सुधार और मोबाइल जोड़ना", "btn_name": "PDF और नाम\nसुधारना", "price": 150, "emoji": "⚙️", "docs": "✅ आधार और वोटर कार्ड में नाम अलग-अलग है तो उसे एक जैसा करवाना\n✅ वोटर कार्ड की पीडीएफ डाउनलोड करके देना\n✅ वोटर कार्ड में मोबाइल नंबर जोड़ना"}
        ]
    },
    "exam": {
        "name": "🎓 फॉर्म और एडमिट कार्ड",
        "desc": "कॉलेज फॉर्म, सरकारी भर्ती फॉर्म, एडमिट कार्ड",
        "services": [
            {"id": "college_exam_form", "name": "कॉलेज/यूनिवर्सिटी एग्जाम फॉर्म", "btn_name": "कॉलेज एग्जाम\nफॉर्म", "price": 100, "emoji": "🏫", "docs": "यूनिवर्सिटी का नाम, रोल नंबर, रजिस्ट्रेशन नंबर, विषय, सेमेस्टर, फोटो, साइन, मोबाइल, ईमेल\n\n⚠️ <b>ध्यान दें:</b> यहाँ सिर्फ ₹100 (सर्विस चार्ज) का QR बनेगा। असली एग्जाम फीस आपको एडमिन बताएगा।"},
            {"id": "college_admit_card", "name": "कॉलेज एडमिट कार्ड डाउनलोड", "btn_name": "कॉलेज एडमिट\nकार्ड", "price": 100, "emoji": "🪪", "docs": "यूनिवर्सिटी का नाम, रोल नंबर, रजिस्ट्रेशन नंबर, जन्मतिथि\n\n✅ <b>फीस:</b> ₹100 (सिर्फ काम का चार्ज)"},
            {"id": "govt_exam_form", "name": "सरकारी नौकरी का फॉर्म (SSC/रेलवे)", "btn_name": "सरकारी नौकरी\nफॉर्म", "price": 100, "emoji": "🏛️", "docs": "10वीं/12वीं/ग्रेजुएशन मार्कशीट, आधार, फोटो, साइन, जाति सर्टिफिकेट (अगर हो)\n\n⚠️ <b>ध्यान दें:</b> यहां सिर्फ ₹100 (सर्विस चार्ज) का QR बनेगा। असली फॉर्म की फीस अलग से देनी होगी।"},
            {"id": "govt_admit_card", "name": "सरकारी नौकरी का एडमिट कार्ड", "btn_name": "सरकारी एडमिट\nकार्ड", "price": 100, "emoji": "🖨️", "docs": "रजिस्ट्रेशन नंबर / रोल नंबर, जन्मतिथि, मोबाइल नंबर\n\n✅ <b>फीस:</b> ₹100 (सिर्फ काम का चार्ज)"}
        ]
    },
    "tax": {
        "name": "💼 टैक्स और बिजनेस का काम",
        "desc": "इनकम टैक्स, GST, MSME, फूड लाइसेंस",
        "services": [
            {"id": "itr_filing", "name": "इनकम टैक्स रिटर्न (ITR) फाइल करना", "btn_name": "ITR फाइल\nकरना", "price": 1000, "emoji": "📊", "docs": "आधार, पैन, बैंक खाता नंबर, IFSC कोड, बैंक का नाम, मोबाइल, OTP\n\n💰 <b>फीस:</b> ITR-1: ₹1000, ITR-2: ₹1500, ITR-3: ₹2000, ITR-4: ₹3000"},
            {"id": "gst_reg", "name": "GST नंबर बनवाना", "btn_name": "GST नंबर\nबनवाना", "price": 2000, "emoji": "🧾", "docs": "आधार, पैन, फोटो, ईमेल, मोबाइल, दुकान का नाम/पता, बिजली बिल या रेंट एग्रीमेंट\n\n💰 <b>फीस:</b> कागज नहीं है तो: ₹3000, कागज है तो: ₹2000"},
            {"id": "msme_reg", "name": "MSME (उद्यम) रजिस्ट्रेशन", "btn_name": "MSME\nरजिस्ट्रेशन", "price": 200, "emoji": "🏭", "docs": "आधार (दोनों तरफ), पैन, बैंक अकाउंट नंबर व IFSC, मोबाइल, ईमेल, फर्म का नाम और पता"},
            {"id": "food_licence", "name": "फूड लाइसेंस (FSSAI)", "btn_name": "फूड लाइसेंस\n(FSSAI)", "price": 500, "emoji": "🍽️", "docs": "आधार कार्ड, पैन कार्ड, फोटो, दुकान का पता (रेंट या बिजली बिल), मोबाइल नंबर, ईमेल ID"},
            {"id": "rc_pdf", "name": "गाड़ी के नंबर से RC (कागज)", "btn_name": "गाड़ी का RC\nडाउनलोड", "price": 100, "emoji": "🚗", "docs": "गाड़ी का नंबर भेजें"}
        ]
    },
    "print": {
        "name": "🖨️ प्रिंट और फोटोकॉपी",
        "desc": "रंगीन/ब्लैक एंड व्हाइट प्रिंट, स्कैन",
        "services": [
            {"id": "print_bw",       "name": "ब्लैक एंड व्हाइट प्रिंट (1 पेज)", "btn_name": "B&W प्रिंट\n(1 पेज)", "price": 2,   "emoji": "📄", "docs": "PDF, वर्ड फाइल या फोटो"},
            {"id": "print_color",    "name": "रंगीन प्रिंट (1 पेज)",           "btn_name": "रंगीन प्रिंट\n(1 पेज)", "price": 10,  "emoji": "🌈", "docs": "PDF, वर्ड फाइल या फोटो"},
            {"id": "photocopy",      "name": "फोटोकॉपी (1 पेज)",               "btn_name": "फोटोकॉपी\n(1 पेज)", "price": 1,   "emoji": "📑", "docs": "ओरिजिनल कागज"},
            {"id": "scan",           "name": "स्कैनिंग (1 पेज)",               "btn_name": "स्कैनिंग\n(1 पेज)", "price": 5,   "emoji": "📷", "docs": "ओरिजिनल कागज"},
            {"id": "lam_a4",         "name": "लेमिनेशन A4",                    "btn_name": "लेमिनेशन\nA4", "price": 30,  "emoji": "🪪", "docs": "A4 साइज का कागज"},
            {"id": "passport_photo", "name": "पासपोर्ट साइज फोटो (8 कॉपी)",    "btn_name": "पासपोर्ट फोटो\n(8 कॉपी)", "price": 50,  "emoji": "👤", "docs": "कुछ नहीं चाहिए, बस कैफे आ जाएं"}
        ]
    },
    "csc": {
        "name": "💻 CSC के काम",
        "desc": "CSC ID, TEC रजिस्ट्रेशन और एग्जाम",
        "services": [
            {"id": "csc_id_approval", "name": "CSC ID अप्रूवल", "btn_name": "CSC ID\nअप्रूवल", "price": 0, "emoji": "✅", "docs": "CSC ID अप्रूवल के लिए कृपया एडमिन से संपर्क करें।", "contact_admin": True},
            {"id": "csc_id_password", "name": "CSC ID पासवर्ड", "btn_name": "CSC ID\nपासवर्ड", "price": 0, "emoji": "🔑", "docs": "CSC ID पासवर्ड के लिए कृपया एडमिन से संपर्क करें।", "contact_admin": True},
            {"id": "csc_tec_reg", "name": "CSC TEC रजिस्ट्रेशन", "btn_name": "TEC\nरजिस्ट्रेशन", "price": 0, "emoji": "📝", "docs": "CSC TEC रजिस्ट्रेशन के लिए कृपया एडमिन से संपर्क करें।", "contact_admin": True},
            {"id": "csc_tec_exam", "name": "CSC TEC एग्जाम", "btn_name": "TEC\nएग्जाम", "price": 0, "emoji": "📚", "docs": "CSC TEC एग्जाम के लिए कृपया एडमिन से संपर्क करें।", "contact_admin": True}
        ]
    },
    "gov": {
        "name": "🏛️ दूसरे सरकारी काम",
        "desc": "ड्राइविंग लाइसेंस, ई-श्रम आदि",
        "services": [
            {"id": "dl_learner",     "name": "ड्राइविंग लाइसेंस (लर्निंग)",    "btn_name": "DL लर्निंग\nलाइसेंस", "price": 0, "emoji": "🚗", "docs": "आधार कार्ड, फोटो, मेडिकल फॉर्म\n\n⚠️ <b>ध्यान दें:</b> फीस और प्रोसेस के लिए एडमिन से संपर्क करें।", "contact_admin": True},
            {"id": "dl_permanent",   "name": "ड्राइविंग लाइसेंस (पक्का)",      "btn_name": "DL पक्का\nलाइसेंस", "price": 0, "emoji": "🚙", "docs": "लर्निंग लाइसेंस, आधार, फोटो\n\n⚠️ <b>ध्यान दें:</b> फीस और प्रोसेस के लिए एडमिन से संपर्क करें।", "contact_admin": True},
            {"id": "eshram",         "name": "ई-श्रम कार्ड (मजदूरों के लिए)",  "btn_name": "ई-श्रम\nकार्ड", "price": 50,  "emoji": "👷", "docs": "आधार कार्ड, बैंक पासबुक"}
        ]
    }
}

# सर्विस आईडी से कैटेगरी आईडी पता करने का फंक्शन (बैक बटन के लिए)
def get_category_id(service_id):
    for cat_id, cat in CATEGORIES.items():
        for svc in cat["services"]:
            if svc["id"] == service_id:
                return cat_id
    return None

def find_service(service_id):
    for cat in CATEGORIES.values():
        for svc in cat["services"]:
            if svc["id"] == service_id:
                return svc
    return None

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("💳 पैन कार्ड", callback_data="cat_pan"), InlineKeyboardButton("🆔 आधार कार्ड", callback_data="cat_aadhaar")],
        [InlineKeyboardButton("🍚 राशन कार्ड", callback_data="cat_ration"), InlineKeyboardButton("📜 जाति/निवास/आय", callback_data="cat_certificates")],
        [InlineKeyboardButton("🗳️ वोटर आईडी", callback_data="cat_voter"), InlineKeyboardButton("🎓 फॉर्म/एडमिट", callback_data="cat_exam")],
        [InlineKeyboardButton("💼 टैक्स/बिजनेस", callback_data="cat_tax"), InlineKeyboardButton("🖨️ प्रिंट/कॉपी", callback_data="cat_print")],
        [InlineKeyboardButton("💻 CSC के काम", callback_data="cat_csc"), InlineKeyboardButton("🏛️ अन्य सरकारी", callback_data="cat_gov")],
        [InlineKeyboardButton("📝 कोई और काम (Other)", callback_data="other_service")]
    ]
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
    msg = await update.message.reply_text("✨ <b>बॉट शुरू हो रहा है...</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.4)
    await msg.edit_text("⚙️ <b>सर्विस लोड हो रही हैं...</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.4)
    await msg.edit_text("🎯 <b>बस थोड़ा सा और इंतज़ार करें...</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.4)

    total = sum(len(c["services"]) for c in CATEGORIES.values())
    welcome = (
        f"🙏 <b>नमस्ते, {user.first_name}!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏪 <b>{PAYEE_NAME}</b> में आपका स्वागत है!\n\n"
        f"🔹 <b>{total}+</b> सर्विसेज उपलब्ध हैं\n"
        f"🔹 <b>UPI पेमेंट</b> — इंस्टेंट QR कोड\n"
        f"🔹 <b>तेज़ और भरोसेमंद काम</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 <b>नीचे से कोई कैटेगरी चुनें:</b>"
    )
    await msg.edit_text(welcome, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML)
    await update.message.reply_text("💡 आप नीचे दिए गए बटन से भी मेनू खोल सकते हैं।", reply_markup=get_reply_keyboard())


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
    services = cat["services"]
    
    for i in range(0, len(services), 2):
        row = []
        svc1 = services[i]
        name1 = svc1.get("btn_name", svc1["name"])
        row.append(InlineKeyboardButton(f"{svc1['emoji']} {name1}", callback_data=f"svc_{svc1['id']}"))
        
        if i + 1 < len(services):
            svc2 = services[i+1]
            name2 = svc2.get("btn_name", svc2["name"])
            row.append(InlineKeyboardButton(f"{svc2['emoji']} {name2}", callback_data=f"svc_{svc2['id']}"))
        
        keyboard.append(row)
        
    # पीछे जाने का बटन (यहाँ से सीधे मेन मेनू जाएगा)
    keyboard.append([InlineKeyboardButton("🔙 पीछे जाएं (मुख्य मेनू)", callback_data="back_main")])

    text = (
        f"📂 <b>{cat['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ℹ️ <i>{cat['desc']}</i>\n\n"
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
    is_contact_admin = svc.get("contact_admin", False)
    cat_id = get_category_id(svc_id) # कैटेगरी आईडी निकालें

    keyboard = []
    if not is_contact_admin:
        keyboard.append([InlineKeyboardButton("💳 पेमेंट करें", callback_data="pay_now")])
    
    # नेविगेशन बटन (पीछे और होम)
    nav_row = []
    if cat_id:
        nav_row.append(InlineKeyboardButton("🔙 पीछे जाएं", callback_data=f"cat_{cat_id}"))
    nav_row.append(InlineKeyboardButton("🏠 मुख्य मेनू", callback_data="back_main"))
    keyboard.append(nav_row)

    price_text = "एडमिन से पूछें" if is_contact_admin else f"₹{svc['price']}"
    
    docs_text = ""
    if svc.get("docs"):
        docs_text = f"\n📄 <b>ज़रूरी कागजात:</b>\n<blockquote>{svc['docs']}</blockquote>\n"

    text = (
        f"🛠️ <b>{svc['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>फीस:</b> {price_text}\n"
        f"{docs_text}"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if is_contact_admin:
        text += (
            f"\n📞 <b>कृपया एडमिन से संपर्क करें:</b>\n"
            f"आप नीचे दिए गए <b>संपर्क करें</b> बटन से या कैफे पर आकर पूरी जानकारी ले सकते हैं।"
        )
    else:
        text += (
            f"\n📌 <b>ध्यान दें:</b> पेमेंट करने के बाद अपने सभी <b>डॉक्यूमेंट्स (कागजात)</b> और <b>स्क्रीनशॉट</b> यहीं इस चैट में भेज दें।\n\n"
            f"👇 पेमेंट करने के लिए नीचे बटन दबाएं।"
        )

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def pay_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    svc = context.user_data.get("selected_service")
    if not svc or svc.get("contact_admin"):
        await query.edit_message_text("⚠️ पहले सर्विस चुनें या एडमिन से संपर्क करें। /start दबाएं")
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
            f"🛠️ <b>सर्विस:</b> {svc['name']}\n"
            f"💰 <b>कुल फीस:</b> ₹{amount}\n"
            f"🆔 <b>UPI ID:</b> <code>{UPI_ID}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📸 <b>QR स्कैन करके पेमेंट करें</b>\n\n"
            f"📌 <b>ध्यान दें:</b> पेमेंट के बाद अपना <b>स्क्रीनशॉट</b> और अपने सभी <b>ज़रूरी कागजात (डॉक्यूमेंट्स)</b> यहीं इस चैट में भेज दें। ✅"
        )
        await context.bot.send_photo(chat_id=chat_id, photo=buf, caption=caption, parse_mode=ParseMode.HTML)
    except Exception:
        logger.exception("QR error")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ QR कोड नहीं बन पाया। एडमिन से बात करें।"
        )

async def ask_other_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_custom_request'] = True
    
    await query.edit_message_text(
        "📝 <b>कोई और काम (Other Service)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "अगर आपको कोई ऐसा काम करवाना है जो लिस्ट में नहीं है, तो आप यहाँ लिख सकते हैं।\n\n"
        "👇 <b>कृपया अपना काम टाइप करके भेजें:</b>\n"
        "<i>(जैसे: 'मुझे एक वीडियो एडिट करवाना है' या 'मुझे कॉलेज का फॉर्म भरना है')</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 पीछे जाएं (मुख्य मेनू)", callback_data="back_main")]])
    )


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("selected_service", None)
    context.user_data.pop("awaiting_custom_request", None) 
    
    total = sum(len(c["services"]) for c in CATEGORIES.values())
    text = (
        f"🏪 <b>{PAYEE_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔹 <b>{total}+</b> सर्विसेज उपलब्ध हैं\n"
        f"🔹 <b>UPI पेमेंट</b> — इंस्टेंट QR कोड\n\n"
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
        f"💰 <b>फीस:</b> ₹{amount}\n"
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
        f"💰 <b>फीस:</b> ₹{amount}\n\n"
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
                    f"आपका पेमेंट या कागजात वेरिफाई नहीं हो पाया।\n"
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
        f"5️⃣ स्क्रीनशॉट और कागजात यहीं भेजें\n"
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


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    
    if context.user_data.get('awaiting_custom_request'):
        context.user_data['awaiting_custom_request'] = False
        
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

    if "सर्विस मेनू" in text:
        total = sum(len(c["services"]) for c in CATEGORIES.values())
        await update.message.reply_text(
            f"🏪 <b>{PAYEE_NAME}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔹 <b>{total}+</b> सर्विसेज उपलब्ध हैं\n"
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
    app.add_handler(CallbackQueryHandler(ask_other_service, pattern="^other_service$"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^(approve|reject)_"))
    
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, payment_proof))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
