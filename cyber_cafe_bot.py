import io
import os
import asyncio
import logging
import requests
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
from PIL import Image, ImageDraw, ImageFont

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

# Safety Check for Token (Review Point 3)
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN is missing! Please set it in GitHub Secrets.")
# ============================================================

# Telegram Message Effect IDs
EFFECT_CONFETTI = "5046509860389126442"  
EFFECT_HEART = "5159385139981059251"     
EFFECT_STARS = "5104841245755180586"     
EFFECT_THUMBS = "5107584321108051014"    

# ------------------------------------------------------------
# 🖼️ फॉन्ट डाउनलोडर (हिंदी के लिए Fix)
# ------------------------------------------------------------
FONT_PATH = "NotoSansDevanagari-Bold.ttf"
FONT_URL = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Bold.ttf"

def ensure_hindi_font():
    if not os.path.exists(FONT_PATH):
        try:
            logger.info("Downloading Hindi Font...")
            r = requests.get(FONT_URL)
            with open(FONT_PATH, 'wb') as f:
                f.write(r.content)
            logger.info("Font downloaded successfully!")
        except Exception as e:
            logger.error(f"Font download failed: {e}")

# ------------------------------------------------------------
# 🎬 GIF बैनर जेनरेटर (CSS जैसा एनिमेशन)
# ------------------------------------------------------------
def create_animated_banner(title, subtitle="Premium Digital Services"):
    frames = []
    # गहरे रंगों का ग्रेडिएंट (जो धीरे-धीरे बदलेगा)
    colors = [(10,15,30), (20,25,50), (30,35,70), (20,25,50)] 
    
    for i, bg in enumerate(colors):
        img = Image.new('RGB', (800, 400), color=bg)
        draw = ImageDraw.Draw(img)
        
        # Glowing border (बॉर्डर का चमकना)
        glow = 150 + int(105 * abs((i % 4) - 2) / 2) 
        draw.rectangle([(0,0),(800,10)], fill=(255, 215, glow))
        draw.rectangle([(0,390),(800,400)], fill=(255, 215, glow))
        draw.rectangle([(0,0),(10,400)], fill=(glow//2, 150, 255))
        draw.rectangle([(790,0),(800,400)], fill=(glow//2, 150, 255))
        
        # हिंदी फॉन्ट लोड करना
        try:
            font_large = ImageFont.truetype(FONT_PATH, 60)
            font_small = ImageFont.truetype(FONT_PATH, 30)
        except IOError:
            # Fallback अगर फॉन्ट डाउनलोड न हो पाए
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        # Text fade-in effect (टेक्स्ट का धीरे-धीरे आना)
        alpha_factor = min(1.0, (i + 1) / 2)
        text_color = tuple(int(c * alpha_factor) for c in (255,255,255))
        
        bbox = draw.textbbox((0,0), title, font=font_large)
        x = (800 - (bbox[2]-bbox[0])) / 2
        draw.text((x, 150), title, font=font_large, fill=text_color)
        
        sub_bbox = draw.textbbox((0,0), subtitle, font=font_small)
        draw.text(((800-(sub_bbox[2]-sub_bbox[0]))/2, 230), subtitle,
                  font=font_small, fill=(255, 215, 0))
        
        frames.append(img)
    
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True,
                   append_images=frames[1:], duration=400, loop=0)
    buf.seek(0)
    buf.name = "banner.gif"
    return buf

# ------------------------------------------------------------
# 🛠️ सर्विस और जरूरी कागजात की लिस्ट
# ------------------------------------------------------------
CATEGORIES = {
    "pan": {
        "name": "💳 पैन कार्ड का काम",
        "desc": "नया पैन, गलती सुधारना, पैन की जानकारी",
        "services": [
            {"id": "pan_new_aadhaar", "name": "नया पैन (सिर्फ आधार से)", "btn_name": "नया पैन\n(सिर्फ आधार से)", "price": 200, "emoji": "💳", "docs": "📄 आधार कार्ड\n🖼️ फोटो\n✍️ हस्ताक्षर (Signature)\n📱 मोबाइल नंबर\n📧 ईमेल आईडी (अगर है तो)\n\n⚠️ <b>नोट :-</b> आधार कार्ड में मोबाइल नंबर लिंक होना जरूरी है, OTP लगेगा।"},
            {"id": "pan_new_metric", "name": "नया पैन (मैट्रिक/जन्म प्रमाण से)", "btn_name": "नया पैन\n(मैट्रिक/जन्म प्रमाण)", "price": 200, "emoji": "🎓", "docs": "📄 आधार कार्ड\n🖼️ फोटो\n✍️ हस्ताक्षर (Signature)\n📱 मोबाइल नंबर\n📧 ईमेल आईडी (अगर है तो)\n\n✅ <i>इसमें कोई आधार OTP नहीं लगेगा, सीधे बन जाएगा।</i>"},
            {"id": "pan_correct_name", "name": "पैन में पूरा नाम या पिता का नाम बदलना", "btn_name": "पूरा नाम/पिता\nका नाम बदलना", "price": 1500, "emoji": "✏️", "docs": "📄 आधार कार्ड\n💳 पैन कार्ड (अगर पैन नंबर है तो वो भी चलेगा)\n🖼️ फोटो\n✍️ हस्ताक्षर\n📱 मोबाइल नंबर\n📧 ईमेल आईडी (अगर है तो)\n\n⚠️ <b>नोट :-</b> आधार कार्ड में मोबाइल नंबर लिंक होना जरूरी है, OTP लगेगा। अगर OTP नहीं देते हैं तो पेमेंट ज्यादा लग सकता है। अगर जन्म प्रमाण पत्र या मैट्रिक सर्टिफिकेट है तो पेमेंट ₹200 ही लगेगा।"},
            {"id": "pan_correct_other", "name": "पैन में बाकी कोई भी सुधार करवाना", "btn_name": "बाकी कोई सुधार\nकरवाना", "price": 250, "emoji": "📝", "docs": "📄 आधार कार्ड\n💳 पैन कार्ड (अगर पैन नंबर है तो वो भी चलेगा)\n🖼️ फोटो\n✍️ हस्ताक्षर\n📱 मोबाइल नंबर\n📧 ईमेल आईडी (अगर है तो)\n\n⚠️ <b>नोट :-</b> आधार कार्ड में मोबाइल नंबर लिंक होना जरूरी है, OTP लगेगा। अगर OTP नहीं देते हैं तो पेमेंट ज्यादा लग सकता है।"},
            {"id": "pan_single_letter", "name": "सिंगल लेटर पैन (जैसे P Sonu)", "btn_name": "सिंगल लेटर पैन\n(जैसे P Sonu)", "price": 1500, "emoji": "🔠", "docs": "📄 आधार PDF\n🖼️ आवेदक का फोटो\n📱 मोबाइल नंबर\n📧 ईमेल आईडी\n✍️ आवेदक का हस्ताक्षर\n👨🏻‍🦳 पिता का नाम\n\n🧏🏻‍♂️ <b>नोट :-</b> अगर आवेदक को हस्ताक्षर करना नहीं आता है तो उनका अंगूठा (थम्ब) लगेगा, लेकिन आधार कार्ड में जो नंबर लिंक रहेगा उस पर एक OTP जाएगा।\n\n<i>जो हस्ताक्षर करना जानता है उसका बिना OTP के ही हो जाएगा।</i>"},
            {"id": "pan_business", "name": "बिजनेस पैन कार्ड", "btn_name": "बिजनेस पैन\nकार्ड", "price": 2000, "emoji": "🏢", "docs": "📲 पैन अप्लाई करने के लिए बस ये डिटेल्स भेजें :-\n\n🏪 बिजनेस का नाम\n📅 खुलने की तारीख\n📍 पूरा पता\n📱 मोबाइल नंबर\n📧 ईमेल आईडी\n🪪 मालिक का आधार कार्ड\n💱 मालिक का पैन कार्ड\n\n✅ डिटेल्स सही-सही भेजें\n⚡ तेज और आसान प्रक्रिया\n⏰ <b>समय:</b> 7 से 10 दिन"},
            {"id": "pan_lost", "name": "पैन कार्ड खो गया है (नंबर पता करना)", "btn_name": "पैन खो गया है\n(नंबर पता करें)", "price": 100, "emoji": "🔍", "docs": "👉 आधार कार्ड नंबर भेजें\n\n⚡ <i>2 मिनट में पैन कार्ड नंबर मिल जाएगा।</i>"},
            {"id": "pan_details", "name": "पैन कार्ड की जानकारी चाहिए", "btn_name": "पैन कार्ड की\nजानकारी", "price": 100, "emoji": "ℹ️", "docs": "पैन कार्ड नंबर है लेकिन डिटेल याद नहीं है।\n\n👉 पैन कार्ड नंबर भेजें।"},
            {"id": "pan_find_mobile", "name": "मोबाइल नंबर से पैन कार्ड खोजना", "btn_name": "मोबाइल से पैन\nखोजना", "price": 150, "emoji": "📱", "docs": "मोबाइल नंबर याद है, पैन कार्ड नंबर याद नहीं है।\n\n👉 मोबाइल नंबर भेजें।"},
            {"id": "pan_find_aadhaar", "name": "पैन कार्ड से आधार नंबर खोजना", "btn_name": "पैन से आधार\nखोजना", "price": 350, "emoji": "🆔", "docs": "पैन कार्ड नंबर है, आधार नंबर याद नहीं है।\n\n👉 पैन कार्ड नंबर भेजें।"}
        ]
    },
    "aadhaar": {
        "name": "🆔 आधार कार्ड का काम",
        "desc": "पता बदलना, पिता का नाम, LMS सर्टिफिकेट",
        "services": [
            {"id": "aadhaar_address", "name": "आधार में पता बदलवाना", "btn_name": "आधार में पता\nबदलवाना", "price": 300, "emoji": "🏠", "docs": "केवल आधार OTP लगेगा और एड्रेस सही लिख कर भेजें, हिंदी और इंग्लिश दोनों में।\n\n<b>अंग्रेजी में इस प्रकार भेजें :-</b>\nVill -\nPost -\nPolice Station -\nDistrict -\nState -\nPin Code -\n\n<b>हिंदी में इस प्रकार भेजें :-</b>\nगाँव -\nडाकघर -\nपुलिस स्टेशन -\nजिला -\nराज्य -\nपिन कोड -\n\n✅ <i>गारंटी के साथ - अगर किसी कारण से एड्रेस अपडेट नहीं होता है तो पेमेंट रिफंड कर दिया जाएगा या दोबारा फ्री में कर दिया जाएगा।</i>"},
            {"id": "aadhaar_father", "name": "आधार में पिता का नाम बदलवाना", "btn_name": "पिता का नाम\nबदलवाना", "price": 250, "emoji": "👨‍🦳", "docs": "पिता के आधार कार्ड में मोबाइल नंबर लिंक होना चाहिए और जिसका नाम बदलवाना है उसके आधार कार्ड में भी मोबाइल नंबर लिंक होना चाहिए, दोनों पर OTP जाएगा।\n\n⚠️ <b>नोट :-</b> जो नाम आपके पिता के आधार कार्ड में होगा, वही नाम आपके आधार कार्ड में आएगा।"},
            {"id": "aadhaar_lms", "name": "आधार LMS सर्टिफिकेट", "btn_name": "LMS सर्टिफिकेट\nबनवाना", "price": 1500, "emoji": "📄", "docs": "🖊️ नाम\n📱 मोबाइल नंबर\n📧 ईमेल आईडी\n🌍 राज्य\n🏙️ जिला\n🆔 आधार नंबर\n\n👉 <b>अभी डाटा भेजें</b>"},
            {"id": "aadhaar_ration", "name": "राशन कार्ड से परिवार का आधार नंबर", "btn_name": "राशन से परिवार\nका आधार नंबर", "price": 400, "emoji": "🍚", "docs": "📍 <i>सभी राज्यों के लिए उपलब्ध:</i>\n\n🔀 पूरे परिवार का आधार नंबर ले सकते हैं लेकिन ध्यान रहे उसका राशन कार्ड में नाम होना चाहिए और आखिरी का 4 अंकों का शो होना चाहिए ऑनलाइन चेक करने पर।\n\n📩 <b>जरूरी:</b> सिर्फ राशन कार्ड नंबर भेजें।"}
        ]
    },
    "ration": {
        "name": "🍚 राशन कार्ड का काम",
        "desc": "नया कार्ड, सदस्य जोड़ना, दूसरे काम",
        "services": [
            {"id": "ration_new", "name": "नया राशन कार्ड बनवाना", "btn_name": "नया राशन कार्ड\nबनवाना", "price": 200, "emoji": "🆕", "docs": "📄 आधार कार्ड (जितना भी मेंबर्स का राशन कार्ड बनवाना है सभी का)\n🕒 सभी की उम्र 5 साल से ज्यादा होनी चाहिए\n📄 जाति प्रमाण पत्र (अगर SC/ST में हैं तो)\n📱 मोबाइल नंबर (आधार से जुड़ा हो, OTP आएगा)\n🏦 बैंक पासबुक (Optional है)\n🏠 घर का फोटो"},
            {"id": "ration_add_member", "name": "राशन कार्ड में नया सदस्य जोड़ना", "btn_name": "नया सदस्य\nजोड़ना", "price": 100, "emoji": "➕", "docs": "📄 राशन कार्ड\n📄 जिसे जोड़ना है उसका आधार कार्ड\n📄 जो राशन कार्ड में Head of Family है उसका आधार कार्ड (और इसमें मोबाइल नंबर लिंक होना जरूरी है)"},
            {"id": "ration_other", "name": "राशन कार्ड का दूसरा काम", "btn_name": "बाकी काम के लिए\nएडमिन से पूछें", "price": 0, "emoji": "⚙️", "docs": "राशन कार्ड के बाकी कामों के लिए कृपया एडमिन से संपर्क करें।", "contact_admin": True}
        ]
    },
    "certificates": {
        "name": "📜 जाति, निवास और आय प्रमाण पत्र",
        "desc": "जाति, निवास, आय और NCL सर्टिफिकेट",
        "services": [
            {"id": "caste_cert", "name": "जाति प्रमाण पत्र", "btn_name": "जाति प्रमाण\nपत्र", "price": 150, "emoji": "📜", "docs": "📄 आधार कार्ड\n📄 खतियान\n📄 रसीद\n📝 फॉर्म (आप एडमिन से ले सकते हैं, इसमें आपके गाँव के मुखिया का सिग्नेचर जरूरी है)\n\n⚠️ <b>नोट :-</b> अगर लड़की की शादी हो गई है तो उसका जाति प्रमाण पत्र उसके पापा के घर से बनेगा, यानी सारे डॉक्यूमेंट्स पापा के घर के लगेंगे।"},
            {"id": "resident_cert", "name": "निवास प्रमाण पत्र", "btn_name": "निवास प्रमाण\nपत्र", "price": 150, "emoji": "🏠", "docs": "📄 आधार कार्ड\n📄 खतियान\n📄 रसीद\n📝 फॉर्म (आप एडमिन से ले सकते हैं, इसमें आपके गाँव के मुखिया का सिग्नेचर जरूरी है)\n\n⚠️ <b>नोट :-</b> अगर लड़की की शादी हो गई है तो उसका निवास प्रमाण पत्र उसके पति के घर से बनेगा, यानी सारे डॉक्यूमेंट्स पति के घर के लगेंगे।"},
            {"id": "income_cert", "name": "आय प्रमाण पत्र", "btn_name": "आय प्रमाण\nपत्र", "price": 150, "emoji": "💰", "docs": "📄 आधार कार्ड\n📄 रसीद (अगर available हो)\n📄 Affidavit (शपथ पत्र)\n📝 फॉर्म (आप एडमिन से ले सकते हैं, इसमें आपके गाँव के मुखिया का सिग्नेचर जरूरी है)\n\n⚠️ <b>नोट :-</b> अगर लड़की की शादी हो गई है तो उसका आय प्रमाण पत्र उसके पति के घर से बनेगा।"},
            {"id": "ncl_cert", "name": "NCL सर्टिफिकेट", "btn_name": "NCL सर्टिफिकेट\n(एडमिन से पूछें)", "price": 0, "emoji": "📑", "docs": "NCL सर्टिफिकेट बनवाने के लिए कृपया एडमिन से संपर्क करें।", "contact_admin": True}
        ]
    },
    "voter": {
        "name": "🗳️ वोटर आईडी का काम",
        "desc": "नया कार्ड, गलती सुधारना, पीडीएफ और मोबाइल जोड़ना",
        "services": [
            {"id": "voter_new_card", "name": "नया वोटर आईडी कार्ड बनवाने के लिए", "btn_name": "नया वोटर\nआईडी कार्ड", "price": 100, "emoji": "🆕", "docs": "📄 आधार कार्ड\n📱 मोबाइल नंबर\n🖼️ फोटो\n📄 पिता / माता / पति / पत्नी में से किसी एक का वोटर ID\n\n⚠️ <b>नोट:</b> आधार में मोबाइल नंबर लिंक होना जरूरी है।"},
            {"id": "voter_correction", "name": "वोटर आईडी में सुधार (Correction) के लिए", "btn_name": "वोटर में सुधार\nकरवाना", "price": 100, "emoji": "✏️", "docs": "📄 आधार कार्ड\n📱 मोबाइल नंबर\n🖼️ फोटो\n\n⚠️ <b>नोट:</b> आधार में मोबाइल नंबर लिंक होना जरूरी है।"},
            {"id": "voter_other", "name": "अन्य सर्विस (PDF, नाम सुधार, मोबाइल लिंक)", "btn_name": "PDF, नाम सुधार\nऔर मोबाइल", "price": 150, "emoji": "⚙️", "docs": "✅ आधार कार्ड और वोटर ID में नाम का अंतर (Mismatch) और वोटर ID की PDF चाहिए मिल जाएगा मिल जाएगी\n✅ वोटर ID में मोबाइल नंबर लिंक नहीं हो रहा है, हो जाएगा"}
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
            {"id": "itr_filing", "name": "ITR (आयकर रिटर्न) फाइल करना", "btn_name": "ITR फाइल\nकरना", "price": 1000, "emoji": "📊", "docs": "📃 <b>जरूरी दस्तावेज :-</b>\nआधार नंबर\nपैन नंबर\nखाता नंबर\nIFSC कोड\nबैंक का नाम\nमोबाइल नंबर\nOTP\n\n💰 <b>फीस :-</b>\nITR-1 :- ₹1000\nITR-2 :- ₹1500\nITR-3 :- ₹2000\nITR-4 :- ₹3000"},
            {"id": "gst_reg", "name": "GST नंबर बनवाना", "btn_name": "GST नंबर\nबनवाना", "price": 2000, "emoji": "🧾", "docs": "✨ आधार कार्ड\n✨ पैन कार्ड\n✨ फोटो\n✨ ईमेल आईडी\n✨ मोबाइल नंबर\n✨ बिजनेस का नाम\n✨ बिजनेस का पता\n\n✨ अगर बिजनेस खुद का है तो - बिजली बिल\n✨ अगर बिजनेस किराए पर है तो - रेंट एग्रीमेंट और मालिक का बिजली बिल\n\n💰 <b>फीस :-</b>\n<i>अगर रेंट एग्रीमेंट या बिजली बिल नहीं है तो - ₹3000</i>\n<i>अगर रेंट एग्रीमेंट / बिजली बिल है तो - ₹2000</i>\n\n⚡ <i>केवल 1 घंटे में जीएसटी नंबर मिल जाएगा!</i>"},
            {"id": "msme_reg", "name": "MSME / उद्यम रजिस्ट्रेशन", "btn_name": "MSME\nरजिस्ट्रेशन", "price": 200, "emoji": "🏭", "docs": "1. ✅ आधार कार्ड (दोनों साइड)\n2. ✅ पैन कार्ड\n3. ✅ बैंक अकाउंट नंबर व IFSC कोड\n4. ✅ आधार से मोबाइल नंबर लिंक होना चाहिए\n5. 📱 मोबाइल नंबर\n6. 📧 ईमेल आईडी\n7. 🏢 फर्म का नाम\n8. 🏠 फर्म का पता\n\n⏳ <i>समय सीमा: तुरंत</i>"},
            {"id": "food_licence", "name": "फूड लाइसेंस (FSSAI)", "btn_name": "फूड लाइसेंस\n(FSSAI)", "price": 500, "emoji": "🍽️", "docs": "आधार कार्ड, पैन कार्ड, फोटो, दुकान का पता (रेंट या बिजली बिल), मोबाइल नंबर, ईमेल ID"},
            {"id": "rc_pdf", "name": "गाड़ी के नंबर से RC PDF", "btn_name": "गाड़ी का RC\nडाउनलोड", "price": 100, "emoji": "🚗", "docs": "गाड़ी नंबर है तो RC PDF मिल जाएगी।\n\n👉 <b>गाड़ी का नंबर भेजें।</b>"}
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
    
    # Smooth Spinning Animation
    frames = ["🕐", "🕒", "🕕", "🕖", "🕘", "🕚"]
    msg = await update.message.reply_text(f"{frames[0]} <b>बॉट शुरू हो रहा है...</b>", parse_mode=ParseMode.HTML)
    
    for frame in frames[1:]:
        await asyncio.sleep(0.2)
        try:
            await msg.edit_text(f"{frame} <b>सर्विस लोड हो रही है...</b>", parse_mode=ParseMode.HTML)
        except:
            pass # Ignore "Message is not modified" error
    
    try:
        await msg.edit_text("🎯 <b>तैयार है!</b>", parse_mode=ParseMode.HTML)
    except:
        pass
    await asyncio.sleep(0.2)
    
    try:
        await msg.delete()
    except:
        pass

    total = sum(len(c["services"]) for c in CATEGORIES.values())
    
    # GIF Banner Generation
    banner = create_animated_banner(PAYEE_NAME, "Premium Digital Services")
    welcome_text = (
        f"🙏 <b>नमस्ते, {user.first_name}!</b>\n\n"
        f"🏪 <b>{PAYEE_NAME}</b> में आपका स्वागत है!\n\n"
        f"✅ <b>{total}+</b> प्रीमियम सर्विसेज उपलब्ध हैं\n"
        f"💳 <b>इंस्टेंट UPI पेमेंट</b> और तेज़ काम\n\n"
        f"👇 <b>नीचे से कोई कैटेगरी चुनें:</b>"
    )
    
    if banner:
        try:
            await update.message.reply_animation(
                animation=banner,
                caption=welcome_text,
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu_keyboard(),
                message_effect_id=EFFECT_CONFETTI
            )
        except Exception as e:
            logger.error(f"GIF failed, sending text: {e}")
            await update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(
            welcome_text, 
            reply_markup=main_menu_keyboard(), 
            parse_mode=ParseMode.HTML,
            message_effect_id=EFFECT_CONFETTI
        )
        
    await update.message.reply_text("💡 नीचे दिए गए बटन से भी मेनू खोल सकते हैं।", reply_markup=get_reply_keyboard())


async def show_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = query.data.replace("cat_", "")
    cat = CATEGORIES.get(cat_id)
    if not cat:
        await query.edit_message_text("❌ कैटेगरी नहीं मिली।")
        return

    await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(0.4)

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
        
    keyboard.append([InlineKeyboardButton("🔙 पीछे जाएं (मुख्य मेनू)", callback_data="back_main")])

    text = (
        f"📂 <b>{cat['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ℹ️ <i>{cat['desc']}</i>\n\n"
        f"👇 <b>सर्विस चुनें:</b>"
    )
    
    try:
        await query.message.delete()
    except:
        pass
        
    # Stars Animation
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
        message_effect_id=EFFECT_STARS
    )


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
    cat_id = get_category_id(svc_id)

    keyboard = []
    if not is_contact_admin:
        keyboard.append([InlineKeyboardButton("💳 पेमेंट करें", callback_data="pay_now")])
    
    nav_row = []
    if cat_id:
        nav_row.append(InlineKeyboardButton("🔙 पीछे जाएं", callback_data=f"cat_{cat_id}"))
    nav_row.append(InlineKeyboardButton("🏠 मुख्य मेनू", callback_data="back_main"))
    keyboard.append(nav_row)

    price_text = "एडमिन से पूछें" if is_contact_admin else f"₹{svc['price']}"
    
    docs_text = ""
    if svc.get("docs"):
        docs_text = f"\n📄 <b>ज़रूरी जानकारी / कागजात:</b>\n<blockquote expandable><tg-spoiler>{svc['docs']}</tg-spoiler></blockquote>\n"

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

    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    except Exception as e:
        # Ignore "Message is not modified" error (Review Point 4)
        if "Message is not modified" not in str(e):
            logger.error(f"Edit message error: {e}")


async def pay_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    svc = context.user_data.get("selected_service")
    if not svc or svc.get("contact_admin"):
        await query.edit_message_text("⚠️ पहले सर्विस चुनें या एडमिन से संपर्क करें। /start दबाएं")
        return

    chat_id = query.message.chat_id
    msg_id = query.message.message_id

    frames = ["⚙️", "🔄", "🔃"]
    msg = await query.edit_message_text(f"{frames[0]} <b>QR कोड बन रहा है...</b>", parse_mode=ParseMode.HTML)
    
    for frame in frames[1:]:
        await asyncio.sleep(0.3)
        try:
            await msg.edit_text(f"{frame} <b>QR कोड बन रहा है...</b>", parse_mode=ParseMode.HTML)
        except:
            pass
        
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)

    try:
        amount = svc["price"]
        note = f"{svc['name']} - {query.from_user.id}"
        upi_uri = (
            f"upi://pay?pa={quote(UPI_ID)}&pn={quote(PAYEE_NAME)}"
            f"&am={amount:.2f}&cu=INR&tn={quote(note)}"
        )
        
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(upi_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="navy", back_color="white")
        
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "upi_qr.png"

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

        caption = (
            f"💳 <b>सुरक्षित पेमेंट</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛠️ <b>सर्विस:</b> {svc['name']}\n"
            f"💰 <b>कुल फीस:</b> ₹{amount}\n"
            f"🆔 <b>UPI ID:</b> <code>{UPI_ID}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📸 <b>QR स्कैन करके पेमेंट करें</b>\n\n"
            f"📌 <b>ध्यान दें:</b> पेमेंट के बाद अपना <b>स्क्रीनशॉट</b> और सभी <b>ज़रूरी कागजात</b> यहीं भेज दें।"
        )
        await context.bot.send_photo(
            chat_id=chat_id, 
            photo=buf, 
            caption=caption, 
            parse_mode=ParseMode.HTML
        )
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
        f"🔹 <b>{total}+</b> प्रीमियम सर्विसेज उपलब्ध हैं\n"
        f"🔹 <b>UPI पेमेंट</b> — इंस्टेंट QR कोड\n\n"
        f"👇 <b>कैटेगरी चुनें:</b>"
    )
    
    try:
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML)
    except:
        pass


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
            reply_markup=admin_kb, parse_mode=ParseMode.HTML,
            message_effect_id=EFFECT_THUMBS
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
        message_effect_id=EFFECT_HEART
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
                message_effect_id=EFFECT_CONFETTI
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
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID, 
                text=admin_text, 
                parse_mode=ParseMode.HTML,
                message_effect_id=EFFECT_STARS 
            )
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
    # फॉन्ट डाउनलोड करना (स्टार्ट होने से पहले)
    ensure_hindi_font()
    
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
