import io
import os
import re
import sys
import time
import json
import fcntl
import base64
import hashlib
import threading
from datetime import datetime, timedelta, timezone
import urllib3
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pymupdf as fitz
from urllib.parse import urljoin, quote

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= CONFIGURATION =================
BOT_TOKEN = (
    os.environ.get("BOT_TOKEN")
    or os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("TOKEN")
    or ""
).strip()

raw_chat_id = os.environ.get("CHAT_ID", "").strip()
if not raw_chat_id:
    CHAT_ID = "@topkeralapsc"
elif "t.me/" in raw_chat_id:
    CHAT_ID = "@" + raw_chat_id.split("t.me/")[-1].replace("/", "")
elif not raw_chat_id.startswith("@") and not raw_chat_id.startswith("-"):
    CHAT_ID = "@" + raw_chat_id
else:
    CHAT_ID = raw_chat_id

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "nikhiltk4u-jpg/PSC").strip()

CHANNEL_LINK = "t.me/topkeralapsc"
CHANNEL_URL = "https://t.me/topkeralapsc"
HISTORY_FILE = "posted_links.txt"
PDF_MAP_FILE = "posted_data.json"

SEED_LIMIT_PER_CATEGORY = 2
MAX_NOTIFICATIONS_PER_RUN = 3
SCRAPE_INTERVAL_SECONDS = 1800  # 30 minutes

if not BOT_TOKEN:
    print("❌ FATAL ERROR: BOT_TOKEN is empty!")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
BOT_USERNAME = bot.get_me().username

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

BASE_URL = "https://www.keralapsc.gov.in"
NOTIFICATIONS_URL = "https://www.keralapsc.gov.in/notifications"

SOURCES = [
    {
        "name": "RANKED LIST / MARK LIST",
        "short_tag": "RankList",
        "emoji": "🏆",
        "url": "https://www.keralapsc.gov.in/rankedlist",
        "hashtag": "#RankList #KeralaPSC"
    },
    {
        "name": "QUESTION PAPER & OMR ANSWER KEY",
        "short_tag": "OMR",
        "emoji": "📝",
        "url": "https://www.keralapsc.gov.in/answerkey_omrexams",
        "hashtag": "#QuestionPaper #AnswerKey #KeralaPSC"
    },
    {
        "name": "SHORT LIST",
        "short_tag": "ShortList",
        "emoji": "📋",
        "url": "https://www.keralapsc.gov.in/shortlists",
        "hashtag": "#ShortList #KeralaPSC"
    }
]

KERALA_DISTRICTS = [
    "Thiruvananthapuram", "Kollam", "Pathanamthitta", "Alappuzha", "Kottayam",
    "Idukki", "Ernakulam", "Thrissur", "Palakkad", "Malappuram", "Kozhikode",
    "Wayanad", "Kannur", "Kasaragod", "Kasargod", "Statewide"
]

MEMORY_PDF_MAP = {}
MEMORY_POSTED_LINKS = set()
LOCK_FILE_HANDLE = None

BOT_STATUS = {
    "started_at": "",
    "last_scrape_time": "Waiting for initial scrape...",
    "total_posted_this_session": 0,
    "last_log": "Initializing...",
    "threads_started": False
}


def log_status(msg):
    print(msg, flush=True)
    BOT_STATUS["last_log"] = msg


# ================= 1. ZERO-STORAGE MEMORY + GITHUB CLOUD SYNC =================
def init_storage():
    global MEMORY_PDF_MAP, MEMORY_POSTED_LINKS
    if os.path.exists(PDF_MAP_FILE):
        try:
            with open(PDF_MAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    MEMORY_PDF_MAP.update(data)
        except Exception:
            pass

    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                MEMORY_POSTED_LINKS.update(line.strip() for line in f if line.strip())
        except Exception:
            pass
    log_status(f"[*] Loaded {len(MEMORY_POSTED_LINKS)} previously posted links from history.")


def push_file_to_github_api(filepath, commit_msg):
    if not GITHUB_TOKEN or not os.path.exists(filepath):
        return
    try:
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        r = requests.get(api_url, headers=headers, timeout=15)
        sha = r.json().get("sha") if r.status_code == 200 else None

        with open(filepath, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {"message": commit_msg, "content": content_b64}
        if sha:
            payload["sha"] = sha

        requests.put(api_url, headers=headers, json=payload, timeout=15)
        log_status(f"[+] Synced {filepath} to GitHub repo {GITHUB_REPO}!")
    except Exception as e:
        log_status(f"[!] GitHub API sync notice: {e}")


def save_pdf_entry(file_id, pdf_url, filename, title):
    MEMORY_PDF_MAP[file_id] = {
        "url": pdf_url,
        "filename": filename.replace("_@topkeralapsc", "_NoWatermark"),
        "title": title
    }
    if len(MEMORY_PDF_MAP) > 500:
        for k in list(MEMORY_PDF_MAP.keys())[:-500]:
            MEMORY_PDF_MAP.pop(k, None)

    try:
        with open(PDF_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(MEMORY_PDF_MAP, f, indent=2)
    except Exception:
        pass


def save_posted_link(link):
    MEMORY_POSTED_LINKS.add(link)
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(f"{link}\n")
    except Exception:
        pass


def make_file_id(pdf_url):
    return hashlib.md5(pdf_url.encode("utf-8")).hexdigest()[:10]


# ================= 2. INSTANT 0.1s FORCE-SUBSCRIBE & RAM STREAMING =================
def is_user_subscribed(user_id):
    try:
        member = bot.get_chat_member(CHAT_ID, user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        log_status(f"[!] Membership check error for {user_id}: {e}")
        return False


def send_clean_pdf_to_user_zero_storage(user_id, file_id):
    entry = MEMORY_PDF_MAP.get(file_id)
    if not entry:
        bot.send_message(
            user_id,
            "⚠️ Could not find this PDF in memory. Please tap the button on any recent post in @topkeralapsc!"
        )
        return

    status_msg = bot.send_message(
        user_id,
        f"✅ <b>Verified Subscriber of @topkeralapsc!</b>\n⏳ <i>Sending your clean (No-Watermark) PDF for:</i>\n<b>{entry['title']}</b>...",
        parse_mode="HTML"
    )

    pdf_bytes = fetch_url(entry["url"], is_pdf=True)
    if pdf_bytes and pdf_bytes.startswith(b"%PDF"):
        try:
            pdf_stream = io.BytesIO(pdf_bytes)
            pdf_stream.name = entry["filename"]

            bot.send_document(
                chat_id=user_id,
                document=pdf_stream,
                visible_file_name=entry["filename"],
                caption=(
                    f"✅ <b>Official Un-Watermarked PDF</b>\n"
                    f"📌 <b>Document:</b> {entry['title']}\n\n"
                    f"❤️ <i>Thank you for being a subscriber of @topkeralapsc!</i>"
                ),
                parse_mode="HTML"
            )
            try:
                bot.delete_message(user_id, status_msg.message_id)
            except Exception:
                pass
        except Exception as e:
            log_status(f"[!] Stream send error: {e}")
    else:
        dl_markup = InlineKeyboardMarkup()
        dl_markup.add(InlineKeyboardButton("📥 Click to Open Clean PDF", url=entry["url"]))
        bot.send_message(
            user_id,
            "✅ <b>Verified Subscriber!</b>\nTap below to open your un-watermarked PDF directly:",
            parse_mode="HTML",
            reply_markup=dl_markup
        )


@bot.message_handler(commands=["start"])
def handle_start_command(message):
    user_id = message.from_user.id
    text = message.text.strip()

    if text.startswith("/start dl_"):
        file_id = text.replace("/start dl_", "").strip()

        if not is_user_subscribed(user_id):
            join_markup = InlineKeyboardMarkup(row_width=1)
            join_markup.add(
                InlineKeyboardButton("📢 Step 1: Join @topkeralapsc", url=CHANNEL_URL),
                InlineKeyboardButton("🔓 Step 2: I Joined — Send Clean PDF", callback_data=f"dmcheck_{file_id}")
            )
            bot.send_message(
                user_id,
                "❌ <b>ACCESS DENIED — SUBSCRIPTION REQUIRED!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "To download the <b>Un-Watermarked PDF</b>, you must be a subscriber of <b>@topkeralapsc</b>.\n\n"
                "1️⃣ Tap <b>Step 1</b> below to join the channel\n"
                "2️⃣ Give a ❤️ or 👍 reaction on the post\n"
                "3️⃣ Tap <b>Step 2</b> below for instant delivery!",
                parse_mode="HTML",
                reply_markup=join_markup
            )
            return

        send_clean_pdf_to_user_zero_storage(user_id, file_id)
    else:
        bot.send_message(
            user_id,
            "👋 <b>Welcome to the Official @topkeralapsc Bot!</b>\n\n"
            "Tap the <b>❤️ React & Download PDF (No Watermark)</b> button below any post in "
            "<a href='https://t.me/topkeralapsc'>@topkeralapsc</a> to receive the un-watermarked PDF instantly!",
            parse_mode="HTML"
        )


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("dmcheck_"))
def handle_dm_recheck_button(call):
    user_id = call.from_user.id
    file_id = call.data.replace("dmcheck_", "").strip()

    if not is_user_subscribed(user_id):
        bot.answer_callback_query(
            call.id,
            text="❌ You still haven't joined @topkeralapsc! Tap 'Step 1: Join @topkeralapsc' first.",
            show_alert=True
        )
        return

    bot.answer_callback_query(call.id, text="✅ Subscription Verified! Sending your Clean PDF...")
    send_clean_pdf_to_user_zero_storage(user_id, file_id)


# ================= 3. TIME & DATE HELPERS (IST) =================
def get_ist_now():
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist_tz)


def get_ist_today():
    return get_ist_now().date()


def get_days_until_deadline(date_str):
    date_match = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})", date_str)
    if not date_match:
        return 999
    try:
        day, month, year = map(int, date_match.groups())
        deadline_date = datetime(year, month, day).date()
        return (deadline_date - get_ist_today()).days
    except Exception:
        return 999


# ================= 4. MULTI-PROXY FETCH =================
def fetch_url(url, is_pdf=False):
    try:
        r = requests.get(url, headers=HEADERS, verify=False, timeout=15)
        if r.status_code == 200 and len(r.content) > 500:
            if not is_pdf or r.content.startswith(b"%PDF"):
                return r.content if is_pdf else r.text
    except Exception as e:
        log_status(f"[!] Direct fetch timed out for {url} ({e}), trying proxies...")

    proxy_templates = [
        f"https://api.allorigins.win/raw?url={quote(url, safe='')}",
        f"https://api.codetabs.com/v1/proxy?quest={quote(url, safe='')}",
        f"https://corsproxy.io/?{quote(url, safe='')}"
    ]

    for proxy_url in proxy_templates:
        try:
            r = requests.get(proxy_url, headers=HEADERS, timeout=25)
            if r.status_code == 200 and len(r.content) > 500:
                if not is_pdf or r.content.startswith(b"%PDF"):
                    return r.content if is_pdf else r.text
        except Exception:
            continue

    log_status(f"❌ All fetch attempts failed for: {url}")
    return None


# ================= 5. ZERO-DISK RAM PDF WATERMARKING =================
def watermark_pdf_in_ram(pdf_bytes):
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            page.clean_contents()
            rect = page.rect
            w, h = rect.width, rect.height
            cx, cy = w / 2.0, h / 2.0

            top_text = "TELEGRAM CHANNEL: @topkeralapsc  |  Click to Join: t.me/topkeralapsc"
            top_fs = 8.5
            top_tw = fitz.get_text_length(top_text, fontname="helv", fontsize=top_fs)
            top_pad_x = 18
            top_box = fitz.Rect(cx - (top_tw / 2) - top_pad_x, 6, cx + (top_tw / 2) + top_pad_x, 24)

            page.draw_rect(
                top_box,
                color=(0.0, 0.45, 0.77),
                fill=(0.92, 0.96, 1.0),
                width=1.0,
                radius=0.3,
                overlay=True
            )
            page.insert_text(
                fitz.Point(cx - (top_tw / 2), 18),
                top_text,
                fontsize=top_fs,
                fontname="helv",
                color=(0.0, 0.28, 0.55),
                overlay=True
            )
            page.insert_link({"kind": fitz.LINK_URI, "from": top_box, "uri": CHANNEL_URL})

            bot_text = "JOIN TELEGRAM FOR KERALA PSC UPDATES:  t.me/topkeralapsc  (CLICK HERE)"
            bot_fs = 8.5
            bot_tw = fitz.get_text_length(bot_text, fontname="helv", fontsize=bot_fs)
            bot_pad_x = 18
            bottom_box = fitz.Rect(cx - (bot_tw / 2) - bot_pad_x, h - 25, cx + (bot_tw / 2) + bot_pad_x, h - 7)

            page.draw_rect(
                bottom_box,
                color=(0.0, 0.35, 0.65),
                fill=(0.0, 0.44, 0.76),
                width=1.0,
                radius=0.3,
                overlay=True
            )
            page.insert_text(
                fitz.Point(cx - (bot_tw / 2), h - 13),
                bot_text,
                fontsize=bot_fs,
                fontname="helv",
                color=(1.0, 1.0, 1.0),
                overlay=True
            )
            page.insert_link({"kind": fitz.LINK_URI, "from": bottom_box, "uri": CHANNEL_URL})

            wm_line1 = "TELEGRAM: @topkeralapsc"
            wm_line2 = "https://t.me/topkeralapsc"
            wm_fs = 26

            pivot = fitz.Point(cx, cy)
            w1 = fitz.get_text_length(wm_line1, fontname="helv", fontsize=wm_fs)
            w2 = fitz.get_text_length(wm_line2, fontname="helv", fontsize=wm_fs)

            page.insert_text(
                fitz.Point(cx - (w1 / 2), cy - 8),
                wm_line1,
                fontsize=wm_fs,
                fontname="helv",
                color=(0.10, 0.42, 0.72),
                fill_opacity=0.14,
                morph=(pivot, fitz.Matrix(45)),
                overlay=True
            )
            page.insert_text(
                fitz.Point(cx - (w2 / 2), cy + 24),
                wm_line2,
                fontsize=wm_fs,
                fontname="helv",
                color=(0.10, 0.42, 0.72),
                fill_opacity=0.14,
                morph=(pivot, fitz.Matrix(45)),
                overlay=True
            )

        out_bytes = doc.tobytes()
        doc.close()
        return out_bytes
    except Exception as e:
        log_status(f"❌ Watermark error: {e}")
        return pdf_bytes


# ================= 6. CLEAN STRUCTURED DETAILS PARSER =================
def clean_text(text):
    return " ".join(text.split())


def format_structured_details(item, doc_type_display):
    raw = item["details"]
    tag = item["short_tag"]
    lines = []

    if tag == "JobNotification":
        post_raw = item.get("post_title", raw.split("|")[0]).strip()
        gaz_date = item.get("gaz_date", "")
        last_date = item.get("last_date", "")

        cat_m = re.search(r"(?:Cat\.?\s*No\.?)\s*([0-9/,\s]+)", post_raw, re.I)
        cat_no = cat_m.group(1).strip() if cat_m else ""
        clean_post = re.sub(r"\(?\s*Cat\.?\s*No\.?\s*[0-9/,\s]+\)?", "", post_raw, flags=re.I).strip(" -|()")

        dept = ""
        if " - " in clean_post:
            parts = clean_post.split(" - ", 1)
            clean_post, dept = parts[0].strip(), parts[1].strip()

        lines.append(f"💼 <b>Post:</b> {clean_post}")
        if dept:
            lines.append(f"🏛 <b>Department:</b> {dept}")
        if cat_no:
            lines.append(f"🔢 <b>Category No:</b> <code>{cat_no}</code>")
        if gaz_date:
            lines.append(f"📰 <b>Gazette Date:</b> {gaz_date}")
        if last_date:
            lines.append(f"⏳ <b>Last Date to Apply:</b> <u><b>{last_date}</b></u>")
        lines.append(f"📄 <b>Document:</b> {doc_type_display}")
        lines.append("🖥 <b>Apply Online:</b> <a href='https://thulasi.psc.kerala.gov.in/thulasi/'>Kerala PSC Thulasi Portal</a>")
        return "\n".join(lines), clean_post

    if tag == "OMR":
        qp_code = re.search(r"Question Paper Code\s*:\s*(.*?)(?=Question Paper Medium|Category Code|$)", raw, re.I)
        medium = re.search(r"Question Paper Medium\s*:\s*(.*?)(?=Category Code|Name Of Post|$)", raw, re.I)
        cat_code = re.search(r"Category Code\s*:\s*(.*?)(?=Name Of Post|Department|Date Of Test|$)", raw, re.I)
        post_m = re.search(r"Name Of Post\s*[&:]?\s*(.*?)(?=Department|Date Of Test|\||$)", raw, re.I)
        dept_m = re.search(r"Department\s*:\s*(.*?)(?=Date Of Test|\||$)", raw, re.I)
        date_m = re.search(r"Date Of Test\s*:\s*([0-9]{2}[-/][0-9]{2,3}|[0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9/.-]+)", raw, re.I)

        first_chunk = raw.split("|")[0].strip()
        post_name = post_m.group(1).strip(" :-|") if post_m else first_chunk.split("-")[0].strip()
        dept_name = dept_m.group(1).strip(" :-|") if dept_m else (first_chunk.split("-")[1].strip() if "-" in first_chunk else "")

        if dept_name.lower() == post_name.lower():
            dept_name = ""

        lines.append(f"💼 <b>Post:</b> {post_name}")
        if dept_name:
            lines.append(f"🏛 <b>Department:</b> {dept_name}")
        if cat_code and cat_code.group(1).strip():
            lines.append(f"🔢 <b>Category No:</b> <code>{cat_code.group(1).strip(' |')}</code>")
        if qp_code and qp_code.group(1).strip():
            lines.append(f"🧾 <b>QP Code:</b> <code>{qp_code.group(1).strip(' |')}</code>")
        if medium and medium.group(1).strip():
            lines.append(f"🌐 <b>Medium:</b> {medium.group(1).strip(' |')}")
        if date_m and date_m.group(1).strip():
            lines.append(f"🗓 <b>Exam Date:</b> {date_m.group(1).strip(' |')}")
        lines.append(f"📄 <b>Document:</b> {doc_type_display}")
        return "\n".join(lines), post_name

    cleaned = re.sub(r"\b20\d{2}\s*,\s*", "", raw)
    cleaned = re.sub(r"Featured\s*Latest\s*,?", "", cleaned, flags=re.I)

    district = ""
    for d in KERALA_DISTRICTS:
        if re.search(rf"\b{d}\b", cleaned, re.I):
            district = d
            break

    cat_m = re.search(r"(?:Category\s*No\.?|Cat\.?\s*No\.?)\s*:?\s*([0-9]+\s*/\s*[0-9]{4})", cleaned, re.I)
    cat_no = re.sub(r"\s+", "", cat_m.group(1)) if cat_m else ""

    list_m = re.search(r"(?:Ranked\s*List|Short\s*List|List)\s*No\.?\s*:?\s*([A-Za-z0-9/\s-]+?)(?=\s+wef|\s+Dated|\||\.|$)", cleaned, re.I)
    list_no = list_m.group(1).strip() if list_m else ""

    date_m = re.search(r"(?:wef|Dated)?\s*(\d{2}[/-]\d{2}[/-]\d{4})", cleaned, re.I)
    pub_date = date_m.group(1).strip() if date_m else ""

    chunks = [c.strip() for c in cleaned.split("|") if c.strip()]
    main_desc = chunks[1] if len(chunks) > 1 else chunks[0]
    main_desc = re.sub(r"\(?\s*(?:Category|Cat\.?)\s*No\.?\s*:?\s*[0-9/\s]+\)?", "", main_desc, flags=re.I)
    main_desc = re.sub(r"\s+in\s+[A-Za-z]+\s+District\.?", "", main_desc, flags=re.I).strip(" .-|")

    post_name = main_desc
    dept_name = ""
    if " in " in main_desc:
        parts = main_desc.split(" in ", 1)
        post_name = parts[0].strip()
        dept_name = parts[1].strip()

    lines.append(f"💼 <b>Post:</b> {post_name}")
    if dept_name:
        lines.append(f"🏛 <b>Department:</b> {dept_name}")
    if district:
        lines.append(f"📍 <b>District:</b> {district}")
    if cat_no:
        lines.append(f"🔢 <b>Category No:</b> <code>{cat_no}</code>")
    if list_no:
        lines.append(f"📋 <b>List No:</b> <code>{list_no}</code>")
    if pub_date:
        lines.append(f"🗓 <b>Published Date:</b> {pub_date}")
    lines.append(f"📄 <b>Document:</b> {doc_type_display}")

    return "\n".join(lines), post_name


# ================= 7. COMPACT FILENAME BUILDER =================
def build_clean_filename(post_name, short_tag, label):
    clean_exam = re.sub(r"[^A-Za-z0-9]+", "_", post_name).strip("_")
    words = [w.capitalize() for w in clean_exam.split("_") if w]
    short_exam = "_".join(words[:2])[:14].rstrip("_")
    if not short_exam:
        short_exam = "PSC"

    label_up = label.upper()
    if short_tag == "JobNotification":
        doc_tag = "Job"
    elif "QUESTION" in label_up:
        doc_tag = "QP"
    elif "ANSWER" in label_up or short_tag == "OMR":
        doc_tag = "Key"
    elif short_tag == "RankList":
        doc_tag = "RankList"
    else:
        doc_tag = "ShortList"

    return f"{short_exam}_{doc_tag}_@topkeralapsc.pdf"


# ================= 8. LIVE JOB NOTIFICATIONS + DEADLINE REMINDERS =================
def scrape_notifications_and_send_reminders():
    active_notifications = []
    html = fetch_url(NOTIFICATIONS_URL, is_pdf=False)
    if not html:
        return active_notifications

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tr")

    active_gazettes = []
    for row in rows:
        cols = [clean_text(td.get_text()) for td in row.find_all("td")]
        if len(cols) < 3:
            continue

        title_text, cat_range, last_date_str = cols[0], cols[1], cols[2]
        days_left = get_days_until_deadline(last_date_str)

        if days_left < 0:
            continue

        gaz_date_m = re.search(r"(\d{2}[/-]\d{2}[/-]\d{4})", title_text)
        gaz_date = gaz_date_m.group(1) if gaz_date_m else title_text

        a_tag = row.find("a", href=True)
        if a_tag:
            gazette_url = urljoin(BASE_URL, a_tag["href"].strip())
            active_gazettes.append({
                "gazette_title": title_text,
                "gaz_date": gaz_date,
                "cat_range": cat_range,
                "last_date": last_date_str,
                "days_left": days_left,
                "url": gazette_url
            })

    for gaz in active_gazettes:
        sub_html = fetch_url(gaz["url"], is_pdf=False)
        post_names_list = []

        if sub_html:
            sub_soup = BeautifulSoup(sub_html, "html.parser")
            for a in sub_soup.find_all("a", href=True):
                href = a["href"].strip()
                if ".pdf" in href.lower():
                    pdf_url = urljoin(BASE_URL, href)
                    post_title = clean_text(a.get_text())
                    if not post_title or post_title.lower() == "download":
                        post_title = clean_text(a.parent.get_text()) if a.parent else gaz["gazette_title"]

                    post_names_list.append(f"• {post_title[:85]}")

                    active_notifications.append({
                        "category": "NEW JOB NOTIFICATION (APPLY NOW)",
                        "short_tag": "JobNotification",
                        "emoji": "📢",
                        "hashtag": "#KeralaPSCNotification #PSCJobs #ApplyNow #KeralaPSC",
                        "details": post_title,
                        "post_title": post_title,
                        "gaz_date": gaz["gaz_date"],
                        "last_date": gaz["last_date"],
                        "pdfs": [(post_title, pdf_url)]
                    })

        days_left = gaz["days_left"]
        if days_left in (0, 1):
            reminder_key = f"REMINDER_{days_left}DAY_{gaz['url']}"
            if reminder_key not in MEMORY_POSTED_LINKS:
                send_deadline_warning_alert(gaz, post_names_list, days_left)
                save_posted_link(reminder_key)

    return active_notifications


def send_deadline_warning_alert(gaz, post_names_list, days_left):
    if days_left == 1:
        header = "⚠️ <b>KERALA PSC LAST DATE REMINDER: 1 DAY LEFT!</b> ⚠️"
        urgency_line = "⏳ <b>Hurry Up! TOMORROW is the last date to apply for these Kerala PSC posts:</b>"
    else:
        header = "🚨 <b>FINAL CALL: KERALA PSC APPLICATION CLOSES TODAY!</b> 🚨"
        urgency_line = "⏰ <b>Applications close TONIGHT at 12:00 Midnight! Apply immediately:</b>"

    posts_preview = "\n".join(post_names_list[:12]) if post_names_list else f"• {gaz['cat_range']}"
    if len(post_names_list) > 12:
        posts_preview += f"\n<i>...and {len(post_names_list) - 12} more posts!</i>"

    alert_msg = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{urgency_line}\n\n"
        f"📰 <b>Gazette Date:</b> {gaz['gaz_date']}\n"
        f"🔢 <b>Categories:</b> <code>{gaz['cat_range']}</code>\n"
        f"⏳ <b>Last Date:</b> <u><b>{gaz['last_date']} (12:00 Midnight)</b></u>\n\n"
        f"📌 <b>Included Posts:</b>\n{posts_preview}\n\n"
        f"🖥 <b>Apply Now (Thulasi Login):</b>\n"
        f"👉 https://thulasi.psc.kerala.gov.in/thulasi/\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📲 <b>Telegram:</b> <code>@topkeralapsc</code>\n"
        f"🔗 <b>Join Channel:</b> https://t.me/topkeralapsc\n\n"
        f"#KeralaPSC #LastDateAlert #PSCJobs #Thulasi"
    )

    try:
        bot.send_message(
            chat_id=CHAT_ID,
            text=alert_msg,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        time.sleep(2)
    except Exception as e:
        log_status(f"[!] Failed to send deadline reminder: {e}")


# ================= 9. STANDARD TABLE SCRAPER =================
def scrape_table_items(source):
    items = []
    html = fetch_url(source["url"], is_pdf=False)
    if not html:
        return items

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tr, div.views-row")

    for row in rows:
        pdf_links = []
        for a in row.find_all("a", href=True):
            href = a["href"].strip()
            if ".pdf" in href.lower():
                full_url = urljoin(BASE_URL, href)
                label = clean_text(a.get_text()) or "Download PDF"
                pdf_links.append((label, full_url))

        if not pdf_links:
            continue

        tds = row.find_all("td")
        if tds:
            cols = [clean_text(td.get_text()) for td in tds if clean_text(td.get_text())]
        else:
            cols = [clean_text(row.get_text())]

        details = " | ".join(cols[:4])
        details = details.replace("Download", "").strip(" |")

        items.append({
            "category": source["name"],
            "short_tag": source["short_tag"],
            "emoji": source["emoji"],
            "hashtag": source["hashtag"],
            "details": details,
            "pdfs": pdf_links
        })

    return items


# ================= 10. ZERO-DISK RAM WATERMARK & SEND =================
def download_and_send_pdf(item, label, pdf_url):
    try:
        log_status(f"[*] Downloading PDF in RAM: {pdf_url}")
        pdf_bytes = fetch_url(pdf_url, is_pdf=True)
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            log_status(f"[!] Invalid PDF download: {pdf_url}")
            return False

        watermarked_bytes = watermark_pdf_in_ram(pdf_bytes)

        if item["short_tag"] == "JobNotification":
            doc_type_display = "Official Gazette Notification PDF"
        elif "question" in label.lower():
            doc_type_display = "Question Paper PDF"
        elif "answer" in label.lower() or item["short_tag"] == "OMR":
            doc_type_display = "OMR Answer Key PDF"
        elif item["short_tag"] == "RankList":
            doc_type_display = "Ranked List PDF"
        else:
            doc_type_display = "Short List PDF"

        formatted_body, extracted_post_name = format_structured_details(item, doc_type_display)
        custom_filename = build_clean_filename(extracted_post_name, item["short_tag"], label)

        file_id = make_file_id(pdf_url)
        save_pdf_entry(file_id, pdf_url, custom_filename, f"{extracted_post_name} ({doc_type_display})")

        caption = (
            f"{item['emoji']} <b>KERALA PSC {item['category']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{formatted_body}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📲 <b>Telegram:</b> <code>@topkeralapsc</code>\n"
            f"🔗 <b>Join Channel:</b> https://t.me/topkeralapsc\n\n"
            f"{item['hashtag']}"
        )

        markup = InlineKeyboardMarkup(row_width=1)
        btn_unlock_clean = InlineKeyboardButton(
            text="❤️ React & Download PDF (No Watermark)",
            url=f"https://t.me/{BOT_USERNAME}?start=dl_{file_id}"
        )
        share_text = quote("🔥 Join @topkeralapsc for Instant Kerala PSC Rank Lists, Question Papers, Answer Keys & Job Notifications!")
        btn_share = InlineKeyboardButton(
            text="📢 Share @topkeralapsc with Friends",
            url=f"https://t.me/share/url?url={quote(CHANNEL_URL)}&text={share_text}"
        )
        markup.add(btn_unlock_clean, btn_share)

        doc_stream = io.BytesIO(watermarked_bytes)
        doc_stream.name = custom_filename

        bot.send_document(
            chat_id=CHAT_ID,
            document=doc_stream,
            visible_file_name=custom_filename,
            caption=caption,
            parse_mode="HTML",
            reply_markup=markup
        )

        log_status(f"[+] Posted from RAM: {custom_filename}")
        time.sleep(3)
        return True

    except Exception as e:
        log_status(f"[!] Error sending PDF: {e}")
        return False


def run_scraper_cycle(force_seed=False):
    if force_seed:
        log_status("[*] Force Seed triggered! Clearing memory to post fresh sample updates now...")
        MEMORY_POSTED_LINKS.clear()

    is_first_run = len(MEMORY_POSTED_LINKS) == 0
    total_sent = 0
    log_status(f"[*] Starting scrape cycle (first_run={is_first_run})...")

    live_notifications = scrape_notifications_and_send_reminders()
    notif_sent = 0
    for item in live_notifications:
        if notif_sent >= MAX_NOTIFICATIONS_PER_RUN:
            break
        for label, pdf_url in item["pdfs"]:
            if pdf_url not in MEMORY_POSTED_LINKS:
                if download_and_send_pdf(item, label, pdf_url):
                    save_posted_link(pdf_url)
                    notif_sent += 1
                    total_sent += 1

    for source in SOURCES:
        items = scrape_table_items(source)
        log_status(f"[*] {source['name']}: Found {len(items)} items.")
        limit = SEED_LIMIT_PER_CATEGORY if is_first_run else 5
        for item in reversed(items[:limit]):
            for label, pdf_url in item["pdfs"]:
                if pdf_url not in MEMORY_POSTED_LINKS:
                    if download_and_send_pdf(item, label, pdf_url):
                        save_posted_link(pdf_url)
                        total_sent += 1

        for item in items[limit:]:
            for _, pdf_url in item["pdfs"]:
                if pdf_url not in MEMORY_POSTED_LINKS:
                    save_posted_link(pdf_url)

    BOT_STATUS["last_scrape_time"] = get_ist_now().strftime("%Y-%m-%d %I:%M:%S %p IST")
    BOT_STATUS["total_posted_this_session"] += total_sent
    log_status(f"[*] Scrape cycle complete! Total new PDFs sent: {total_sent}")

    if total_sent > 0:
        push_file_to_github_api(HISTORY_FILE, "Sync posted_links.txt [skip ci]")
        push_file_to_github_api(PDF_MAP_FILE, "Sync posted_data.json [skip ci]")


# ================= 11. SINGLE-INSTANCE SYSTEM LOCK & RENDER ENDPOINTS =================
@app.route("/")
def keep_alive():
    ensure_background_threads_started()
    return jsonify({
        "status": "Alive & Listening 24/7",
        "bot_username": f"@{BOT_USERNAME}",
        "target_channel": CHAT_ID,
        "started_at": BOT_STATUS["started_at"],
        "last_scrape_time": BOT_STATUS["last_scrape_time"],
        "total_posted_this_session": BOT_STATUS["total_posted_this_session"],
        "tracked_links_count": len(MEMORY_POSTED_LINKS),
        "tracked_pdfs_count": len(MEMORY_PDF_MAP),
        "last_log": BOT_STATUS["last_log"],
        "force_post_url": "Visit /post_now in your browser to force-post the latest updates immediately!"
    }), 200


@app.route("/post_now")
def trigger_force_post():
    ensure_background_threads_started()
    threading.Thread(target=run_scraper_cycle, kwargs={"force_seed": True}, daemon=True).start()
    return (
        "<h2>🚀 Force-Post Triggered!</h2>"
        "<p>The bot is now scraping and posting the latest watermarked PDFs to <b>@topkeralapsc</b>.</p>"
        "<p>Check your Telegram channel in 15–30 seconds!</p>"
    ), 200


def background_scraper_loop():
    time.sleep(10)
    while True:
        try:
            run_scraper_cycle(force_seed=False)
        except Exception as e:
            log_status(f"[!] Scraper loop error: {e}")
        time.sleep(SCRAPE_INTERVAL_SECONDS)


def start_bot_polling():
    # Wait 20 seconds after Render port opens so the old deploy container shuts down completely first!
    log_status(f"[*] Waiting 20s for old Render container to terminate before polling @{BOT_USERNAME}...")
    time.sleep(20)
    log_status(f"[*] Starting 24/7 Instant Listener for @{BOT_USERNAME} (Single-Instance Locked)...")
    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(
                timeout=20,
                long_polling_timeout=10,
                allowed_updates=["message", "callback_query"]
            )
        except Exception as e:
            log_status(f"[!] Polling retry in 10s: {e}")
            time.sleep(10)


def ensure_background_threads_started():
    """Uses an OS file lock (/tmp/psc_bot.lock) so ONLY ONE worker/thread can ever poll Telegram!"""
    global LOCK_FILE_HANDLE
    if BOT_STATUS["threads_started"]:
        return

    try:
        LOCK_FILE_HANDLE = open("/tmp/psc_bot_single_instance.lock", "w")
        fcntl.flock(LOCK_FILE_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        # Another worker in the same container already holds the lock! Do not start a duplicate poller.
        print("[*] Another worker already holds the Telegram polling lock. Skipping duplicate thread.")
        BOT_STATUS["threads_started"] = True
        return

    BOT_STATUS["threads_started"] = True
    BOT_STATUS["started_at"] = get_ist_now().strftime("%Y-%m-%d %I:%M:%S %p IST")
    init_storage()
    threading.Thread(target=start_bot_polling, daemon=True).start()
    threading.Thread(target=background_scraper_loop, daemon=True).start()


if os.environ.get("RENDER") or os.environ.get("PORT"):
    ensure_background_threads_started()

if __name__ == "__main__":
    if os.environ.get("RENDER") or os.environ.get("PORT"):
        ensure_background_threads_started()
        port = int(os.environ.get("PORT", 10000))
        app.run(host="0.0.0.0", port=port, use_reloader=False)
    else:
        init_storage()
        run_scraper_cycle()
