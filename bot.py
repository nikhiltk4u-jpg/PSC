import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
import urllib3
import requests
from bs4 import BeautifulSoup
import telebot
import fitz  # PyMuPDF
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

CHANNEL_LINK = "t.me/topkeralapsc"
CHANNEL_URL = "https://t.me/topkeralapsc"
HISTORY_FILE = "posted_links.txt"

SEED_LIMIT_PER_CATEGORY = 2
MAX_NOTIFICATIONS_PER_RUN = 4

if not BOT_TOKEN:
    print("❌ FATAL ERROR: BOT_TOKEN is empty! Check GitHub Secrets.")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

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


# ================= 1. TIME & DATE HELPERS (IST) =================
def get_ist_today():
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist_tz).date()


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


# ================= 2. FETCH WITH PROXY FALLBACK =================
def fetch_url(url, is_pdf=False):
    try:
        r = requests.get(url, headers=HEADERS, verify=False, timeout=20)
        if r.status_code == 200 and len(r.content) > 500:
            return r.content if is_pdf else r.text
    except Exception as e:
        print(f"[!] Direct fetch timed out ({e}), using proxy...")

    try:
        proxy_url = f"https://api.allorigins.win/raw?url={quote(url, safe='')}"
        r = requests.get(proxy_url, headers=HEADERS, timeout=30)
        if r.status_code == 200 and len(r.content) > 500:
            return r.content if is_pdf else r.text
    except Exception as e:
        print(f"[!] Proxy fetch failed: {e}")

    return None


# ================= 3. PREMIUM PDF WATERMARKING (CENTERED PILLS + 45° UPWARD) =================
def add_watermark_to_pdf(input_pdf_path, output_pdf_path):
    """
    1. Top-Center Premium Rounded Pill Badge (Clickable)
    2. Bottom-Center Premium Solid Pill Badge (Clickable)
    3. Dead-Center 45° Upward Diagonal Watermark (Ultra-light 0.11 opacity so text is 100% readable)
    """
    try:
        doc = fitz.open(input_pdf_path)
        for page in doc:
            page.clean_contents()
            rect = page.rect
            w, h = rect.width, rect.height
            cx, cy = w / 2.0, h / 2.0

            # --- 1. TOP-CENTER PREMIUM PILL BADGE ---
            badge_w = min(390, w - 40)
            top_box = fitz.Rect(cx - badge_w / 2, 6, cx + badge_w / 2, 24)
            # Soft sky-blue pill with royal-blue border
            page.draw_rect(
                top_box,
                color=(0.0, 0.45, 0.77),
                fill=(0.93, 0.97, 1.0),
                width=0.8,
                radius=0.25,
                overlay=True
            )
            page.insert_textbox(
                fitz.Rect(top_box.x0, top_box.y0 + 3.5, top_box.x1, top_box.y1),
                "TELEGRAM CHANNEL: @topkeralapsc   •   CLICK TO JOIN",
                fontsize=8,
                fontname="helbo",  # Bold Helvetica
                color=(0.0, 0.28, 0.55),
                align=fitz.TEXT_ALIGN_CENTER,
                overlay=True
            )
            page.insert_link({"kind": fitz.LINK_URI, "from": top_box, "uri": CHANNEL_URL})

            # --- 2. BOTTOM-CENTER PREMIUM PILL BADGE ---
            bot_w = min(430, w - 40)
            bottom_box = fitz.Rect(cx - bot_w / 2, h - 25, cx + bot_w / 2, h - 6)
            # Deep Navy-Telegram-Blue pill with gold/white text
            page.draw_rect(
                bottom_box,
                color=(0.0, 0.35, 0.65),
                fill=(0.0, 0.44, 0.76),
                width=0.8,
                radius=0.25,
                overlay=True
            )
            page.insert_textbox(
                fitz.Rect(bottom_box.x0, bottom_box.y0 + 4, bottom_box.x1, bottom_box.y1),
                "JOIN TELEGRAM FOR KERALA PSC UPDATES:  t.me/topkeralapsc  (CLICK HERE)",
                fontsize=8,
                fontname="helbo",
                color=(1.0, 1.0, 1.0),
                align=fitz.TEXT_ALIGN_CENTER,
                overlay=True
            )
            page.insert_link({"kind": fitz.LINK_URI, "from": bottom_box, "uri": CHANNEL_URL})

            # --- 3. DEAD-CENTER 45° UPWARD WATERMARK (NON-INTRUSIVE) ---
            # Positive 45 degrees in PyMuPDF rotates counter-clockwise (45° UPWARD from bottom-left to top-right)
            wm_box = fitz.Rect(cx - 230, cy - 45, cx + 230, cy + 45)
            pivot = fitz.Point(cx, cy)
            page.insert_textbox(
                wm_box,
                "TELEGRAM: @topkeralapsc\nt.me/topkeralapsc",
                fontsize=26,
                fontname="helbo",
                color=(0.15, 0.40, 0.65),
                fill_opacity=0.11,  # Very soft opacity so exam questions/numbers are never obscured
                align=fitz.TEXT_ALIGN_CENTER,
                morph=(pivot, fitz.Matrix(45)),  # +45° upward standard watermark angle
                overlay=True
            )

        doc.save(output_pdf_path)
        doc.close()
        return True
    except Exception as e:
        print(f"❌ Watermark error: {e}")
        return False


# ================= 4. CLEAN STRUCTURED DETAILS PARSER =================
def clean_text(text):
    return " ".join(text.split())


def format_structured_details(item, doc_type_display):
    raw = item["details"]
    tag = item["short_tag"]
    lines = []

    # --- CASE 1: LIVE JOB NOTIFICATION ---
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

    # --- CASE 2: QUESTION PAPER & OMR ANSWER KEY ---
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

    # --- CASE 3: RANKED LIST & SHORT LIST ---
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


# ================= 5. COMPACT FILENAME BUILDER =================
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


# ================= 6. LIVE JOB NOTIFICATIONS + DEADLINE REMINDERS =================
def scrape_notifications_and_send_reminders(posted_links):
    active_notifications = []
    print(f"[*] Checking Live Job Notifications & Deadlines at {NOTIFICATIONS_URL}...")
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

    print(f"    -> Found {len(active_gazettes)} currently open Gazette(s).")

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
            if reminder_key not in posted_links:
                send_deadline_warning_alert(gaz, post_names_list, days_left)
                save_posted_link(reminder_key)
                posted_links.add(reminder_key)

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
        print(f"[!] Failed to send deadline reminder: {e}")


# ================= 7. STANDARD TABLE SCRAPER =================
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


# ================= 8. DOWNLOAD, WATERMARK & SEND =================
def download_and_send_pdf(item, label, pdf_url):
    raw_file = "temp_raw.pdf"
    watermarked_file = "temp_watermarked.pdf"

    try:
        print(f"[*] Downloading PDF: {pdf_url}")
        pdf_bytes = fetch_url(pdf_url, is_pdf=True)
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            print(f"[!] Invalid PDF download: {pdf_url}")
            return False

        with open(raw_file, "wb") as f:
            f.write(pdf_bytes)

        watermarked_ok = add_watermark_to_pdf(raw_file, watermarked_file)
        file_to_send = watermarked_file if watermarked_ok else raw_file

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

        # Extra blank line (\n\n) added after formatted_body so the footer stays visually separate
        caption = (
            f"{item['emoji']} <b>KERALA PSC {item['category']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{formatted_body}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📲 <b>Telegram:</b> <code>@topkeralapsc</code>\n"
            f"🔗 <b>Join Channel:</b> https://t.me/topkeralapsc\n\n"
            f"{item['hashtag']}"
        )

        with open(file_to_send, "rb") as doc_file:
            bot.send_document(
                chat_id=CHAT_ID,
                document=doc_file,
                visible_file_name=custom_filename,
                caption=caption,
                parse_mode="HTML"
            )

        print(f"[+] Posted: {custom_filename}")
        time.sleep(3)
        return True

    except Exception as e:
        print(f"[!] Error sending PDF: {e}")
        return False

    finally:
        for f in [raw_file, watermarked_file]:
            if os.path.exists(f):
                os.remove(f)


def load_posted_links():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_posted_link(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{link}\n")


def main():
    posted_links = load_posted_links()
    is_first_run = len(posted_links) == 0
    total_sent = 0

    # --- PART A: LIVE JOB NOTIFICATIONS + DEADLINE REMINDERS ---
    live_notifications = scrape_notifications_and_send_reminders(posted_links)
    print(f"    -> Total individual live Job Notification PDFs found: {len(live_notifications)}")

    notif_sent = 0
    for item in live_notifications:
        if notif_sent >= MAX_NOTIFICATIONS_PER_RUN:
            break
        for label, pdf_url in item["pdfs"]:
            if pdf_url not in posted_links:
                if download_and_send_pdf(item, label, pdf_url):
                    save_posted_link(pdf_url)
                    posted_links.add(pdf_url)
                    notif_sent += 1
                    total_sent += 1

    # --- PART B: RANK LISTS, QUESTION PAPERS, ANSWER KEYS, SHORT LISTS ---
    for source in SOURCES:
        print(f"[*] Scraping {source['name']}...")
        items = scrape_table_items(source)
        print(f"    -> Found {len(items)} items.")

        limit = SEED_LIMIT_PER_CATEGORY if is_first_run else 5
        for item in reversed(items[:limit]):
            for label, pdf_url in item["pdfs"]:
                if pdf_url not in posted_links:
                    if download_and_send_pdf(item, label, pdf_url):
                        save_posted_link(pdf_url)
                        posted_links.add(pdf_url)
                        total_sent += 1

        for item in items[limit:]:
            for _, pdf_url in item["pdfs"]:
                if pdf_url not in posted_links:
                    save_posted_link(pdf_url)
                    posted_links.add(pdf_url)

    print(f"[*] Done! Total watermarked PDFs sent: {total_sent}")


if __name__ == "__main__":
    main()
