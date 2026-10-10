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


# ================= 1. TIME & DATE HELPERS (IST) =================
def get_ist_today():
    """Returns today's date in Indian Standard Time (UTC+5:30)."""
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist_tz).date()


def get_days_until_deadline(date_str):
    """
    Parses a Kerala PSC date string (e.g. '04-11-2026') and returns the number of days left:
      > 1 : Still open (multiple days left)
      1   : Tomorrow is the Last Date!
      0   : Today is the Last Date!
      < 0 : Expired
    """
    date_match = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})", date_str)
    if not date_match:
        return 999
    try:
        day, month, year = map(int, date_match.groups())
        deadline_date = datetime(year, month, day).date()
        today_ist = get_ist_today()
        return (deadline_date - today_ist).days
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


# ================= 3. GUARANTEED PDF WATERMARKING =================
def add_watermark_to_pdf(input_pdf_path, output_pdf_path):
    try:
        doc = fitz.open(input_pdf_path)
        for page in doc:
            page.clean_contents()
            rect = page.rect
            w, h = rect.width, rect.height

            # 1. Top Telegram Banner
            top_box = fitz.Rect(15, 4, w - 15, 22)
            page.draw_rect(top_box, color=(0.0, 0.47, 0.78), fill=(0.91, 0.96, 1.0), overlay=True)
            page.insert_text(
                fitz.Point(25, 16),
                "TELEGRAM: @topkeralapsc  |  Click to Join: https://t.me/topkeralapsc",
                fontsize=8.5,
                fontname="helv",
                color=(0.0, 0.32, 0.60),
                overlay=True
            )
            page.insert_link({"kind": fitz.LINK_URI, "from": top_box, "uri": CHANNEL_URL})

            # 2. Bottom Telegram Banner
            bottom_box = fitz.Rect(15, h - 24, w - 15, h - 5)
            page.draw_rect(bottom_box, color=(0.0, 0.47, 0.78), fill=(0.0, 0.47, 0.78), overlay=True)
            page.insert_text(
                fitz.Point(25, h - 11),
                "JOIN TELEGRAM CHANNEL: @topkeralapsc (https://t.me/topkeralapsc) - CLICK HERE",
                fontsize=8.5,
                fontname="helv",
                color=(1.0, 1.0, 1.0),
                overlay=True
            )
            page.insert_link({"kind": fitz.LINK_URI, "from": bottom_box, "uri": CHANNEL_URL})

            # 3. 45-Degree Diagonal Watermark
            pivot = fitz.Point(w * 0.22, h * 0.62)
            page.insert_text(
                pivot,
                "Telegram: @topkeralapsc\nhttps://t.me/topkeralapsc",
                fontsize=28,
                fontname="helv",
                color=(0.10, 0.45, 0.75),
                fill_opacity=0.22,
                morph=(pivot, fitz.Matrix(-45)),
                overlay=True
            )

        doc.save(output_pdf_path)
        doc.close()
        return True
    except Exception as e:
        print(f"❌ Watermark error: {e}")
        return False


# ================= 4. SMART EXAM NAME EXTRACTOR FOR FILENAME =================
def build_clean_filename(item, label):
    details = item["details"]

    cat_match = re.search(r"(?:Cat\.?\s*No\.?|Category\s*(?:No|Code)\s*:?)\s*(\d+\s*/\s*\d{4})", details, re.IGNORECASE)
    cat_str = ""
    if cat_match:
        cat_str = "_Cat_" + re.sub(r"\s+", "", cat_match.group(1)).replace("/", "_")

    parts = [p.strip() for p in details.split("|") if p.strip()]
    exam_name = parts[0] if parts else "Kerala_PSC"

    if len(parts) > 1 and (exam_name[:4].isdigit() or len(exam_name) < 12):
        exam_name = f"{parts[1]}_{parts[0]}"

    exam_name = exam_name.split("-")[0].split("(")[0].strip()
    clean_exam = re.sub(r"[^A-Za-z0-9]+", "_", exam_name).strip("_")
    clean_exam = "_".join(w.capitalize() for w in clean_exam.split("_") if w)[:20].rstrip("_")

    if not clean_exam:
        clean_exam = "PSC"

    label_up = label.upper()
    if item["short_tag"] == "JobNotification":
        doc_tag = "Notification"
    elif "QUESTION" in label_up:
        doc_tag = "QP"
    elif "ANSWER" in label_up or item["short_tag"] == "OMR":
        doc_tag = "AnswerKey"
    else:
        doc_tag = item["short_tag"]

    return f"{clean_exam}{cat_str}_{doc_tag}_Telegram_@topkeralapsc.pdf"


# ================= 5. LIVE JOB NOTIFICATIONS + LAST DATE REMINDER ALERTS =================
def clean_text(text):
    return " ".join(text.split())


def scrape_notifications_and_send_reminders(posted_links):
    """
    1. Checks /notifications for open Gazettes.
    2. Sends a 1-Day-Before or Final-Day warning alert if days_left == 1 or 0!
    3. Returns individual Job Notification PDFs for active Gazettes.
    """
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

        # Skip expired notifications
        if days_left < 0:
            continue

        a_tag = row.find("a", href=True)
        if a_tag:
            gazette_url = urljoin(BASE_URL, a_tag["href"].strip())
            active_gazettes.append({
                "gazette_title": title_text,
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

                    details_text = (
                        f"{post_title} | "
                        f"Gazette: {gaz['gazette_title']} | "
                        f"🗓 <b>Last Date to Apply: {gaz['last_date']}</b>"
                    )

                    active_notifications.append({
                        "category": "NEW JOB NOTIFICATION (APPLY NOW)",
                        "short_tag": "JobNotification",
                        "emoji": "📢",
                        "hashtag": "#KeralaPSCNotification #PSCJobs #ApplyNow #KeralaPSC",
                        "details": details_text,
                        "last_date": gaz["last_date"],
                        "pdfs": [(post_title, pdf_url)]
                    })

        # --- CHECK IF DEADLINE IS TOMORROW (1 DAY LEFT) OR TODAY (0 DAYS LEFT) ---
        days_left = gaz["days_left"]
        if days_left in (0, 1):
            reminder_key = f"REMINDER_{days_left}DAY_{gaz['url']}"
            if reminder_key not in posted_links:
                send_deadline_warning_alert(gaz, post_names_list, days_left)
                save_posted_link(reminder_key)
                posted_links.add(reminder_key)

    return active_notifications


def send_deadline_warning_alert(gaz, post_names_list, days_left):
    """Sends an urgent 1-Day-Before or Final-Day application closing alert to the channel."""
    if days_left == 1:
        header = "⚠️ <b>KERALA PSC LAST DATE REMINDER: 1 DAY LEFT!</b> ⚠️"
        urgency_line = "⏳ <b>Hurry Up! TOMORROW is the last date to apply for these Kerala PSC posts:</b>"
    else:
        header = "🚨 <b>FINAL CALL: KERALA PSC APPLICATION CLOSES TODAY!</b> 🚨"
        urgency_line = "⏰ <b> Applications close TONIGHT at 12:00 Midnight! Apply immediately:</b>"

    posts_preview = "\n".join(post_names_list[:12]) if post_names_list else f"• {gaz['cat_range']}"
    if len(post_names_list) > 12:
        posts_preview += f"\n<i>...and {len(post_names_list) - 12} more posts!</i>"

    alert_msg = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{urgency_line}\n\n"
        f"📋 <b>Gazette:</b> {gaz['gazette_title']}\n"
        f"🔢 <b>Categories:</b> {gaz['cat_range']}\n"
        f"🗓 <b>Last Date:</b> <u><b>{gaz['last_date']} (12:00 Midnight)</b></u>\n\n"
        f"📌 <b>Included Posts:</b>\n{posts_preview}\n\n"
        f"🖥 <b>Apply Now (Thulasi Login):</b>\n"
        f"👉 https://thulasi.psc.kerala.gov.in/thulasi/\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📲 <b>Share with friends! Join:</b> @topkeralapsc\n"
        f"🔗 https://t.me/topkeralapsc\n\n"
        f"#KeralaPSC #LastDateAlert #PSCJobs #Thulasi"
    )

    try:
        bot.send_message(
            chat_id=CHAT_ID,
            text=alert_msg,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        print(f"[+] Sent {days_left}-Day Last Date Reminder for {gaz['gazette_title']}!")
        time.sleep(2)
    except Exception as e:
        print(f"[!] Failed to send deadline reminder: {e}")


# ================= 6. STANDARD TABLE SCRAPER =================
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

        cols = [clean_text(td.get_text()) for td in row.find_all(["td", "div"]) if clean_text(td.get_text())]
        details = " | ".join(cols[:4]) if cols else clean_text(row.get_text())
        details = details.replace("Download", "").strip(" |")
        if len(details) > 400:
            details = details[:400] + "..."

        items.append({
            "category": source["name"],
            "short_tag": source["short_tag"],
            "emoji": source["emoji"],
            "hashtag": source["hashtag"],
            "details": details,
            "pdfs": pdf_links
        })

    return items


# ================= 7. DOWNLOAD, WATERMARK & SEND =================
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

        custom_filename = build_clean_filename(item, label)

        if item["short_tag"] == "JobNotification":
            doc_type_display = "Official Gazette Notification PDF"
            apply_line = "🖥 <b>Apply Online:</b> <a href='https://thulasi.psc.kerala.gov.in/thulasi/'>Kerala PSC Thulasi Portal</a>\n"
        else:
            doc_type_display = "Question Paper" if "question" in label.lower() else (
                "Answer Key" if item["short_tag"] == "OMR" else item["short_tag"]
            )
            apply_line = ""

        caption = (
            f"{item['emoji']} <b>KERALA PSC {item['category']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Details:</b> {item['details']}\n\n"
            f"📄 <b>Document:</b> {doc_type_display}\n"
            f"{apply_line}"
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

    # --- PART A: LIVE JOB NOTIFICATIONS + AUTOMATIC 1-DAY & FINAL-DAY REMINDERS ---
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
