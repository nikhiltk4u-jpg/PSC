import os
import sys
import time
import urllib3
import requests
from bs4 import BeautifulSoup
import telebot
import fitz  # PyMuPDF
from urllib.parse import urljoin, quote

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= CONFIGURATION =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

# Force @topkeralapsc if CHAT_ID secret is missing or formatted as a URL
raw_chat_id = os.environ.get("CHAT_ID", "@topkeralapsc").strip()
if "t.me/" in raw_chat_id:
    CHAT_ID = "@" + raw_chat_id.split("t.me/")[-1].replace("/", "")
elif not raw_chat_id.startswith("@") and not raw_chat_id.startswith("-"):
    CHAT_ID = "@" + raw_chat_id
else:
    CHAT_ID = raw_chat_id

CHANNEL_LINK = "t.me/topkeralapsc"
CHANNEL_URL = "https://t.me/topkeralapsc"
HISTORY_FILE = "posted_links.txt"

# Force seeding if FORCE_SEED is True (Set to False after your channel has initial posts)
FORCE_SEED = True
SEED_LIMIT_PER_CATEGORY = 2

if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("❌ FATAL ERROR: BOT_TOKEN is missing! Check your GitHub Secrets.")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9"
}

BASE_URL = "https://www.keralapsc.gov.in"

SOURCES = [
    {
        "name": "LATEST UPDATES (RANK LIST / SHORT LIST)",
        "emoji": "🏆",
        "url": "https://www.keralapsc.gov.in/latest",
        "hashtag": "#KeralaPSC #RankList #ShortList"
    },
    {
        "name": "RANKED LIST / MARK LIST",
        "emoji": "📊",
        "url": "https://www.keralapsc.gov.in/rankedlist",
        "hashtag": "#RankList #KeralaPSC"
    },
    {
        "name": "QUESTION PAPER & OMR ANSWER KEY",
        "emoji": "📝",
        "url": "https://www.keralapsc.gov.in/answerkey_omrexams",
        "hashtag": "#QuestionPaper #AnswerKey #KeralaPSC"
    },
    {
        "name": "SHORT LIST",
        "emoji": "📋",
        "url": "https://www.keralapsc.gov.in/shortlists",
        "hashtag": "#ShortList #KeralaPSC"
    }
]


# ================= 1. VERIFY TELEGRAM CONNECTION FIRST =================
def verify_telegram_connection():
    print(f"[*] Testing connection to Telegram channel: {CHAT_ID}")
    try:
        me = bot.get_me()
        print(f"[+] Bot authenticated successfully as: @{me.username}")
        # Verify chat exists and bot has access
        chat = bot.get_chat(CHAT_ID)
        print(f"[+] Channel found: {chat.title} ({CHAT_ID})")
        return True
    except Exception as e:
        print(f"❌ TELEGRAM ERROR: Cannot access {CHAT_ID} -> {e}")
        print("👉 Make sure:")
        print("   1. Your BOT_TOKEN secret in GitHub is correct.")
        print("   2. Your bot is added as an ADMINISTRATOR in @topkeralapsc with 'Post Messages' permission.")
        sys.exit(1)


# ================= 2. FETCH WITH PROXY FALLBACK (BYPASS NIC BLOCK) =================
def fetch_url(url, is_pdf=False):
    """Tries direct request first; if GitHub IP is blocked by NIC, uses proxy fallback."""
    try:
        r = requests.get(url, headers=HEADERS, verify=False, timeout=20)
        if r.status_code == 200 and len(r.content) > 500:
            return r.content if is_pdf else r.text
    except Exception as e:
        print(f"[!] Direct connection to {url} timed out ({e}). Trying proxy fallback...")

    # Fallback proxy for GitHub Actions US IPs blocked by keralapsc.gov.in
    try:
        proxy_url = f"https://api.allorigins.win/raw?url={quote(url, safe='')}"
        r = requests.get(proxy_url, headers=HEADERS, timeout=30)
        if r.status_code == 200 and len(r.content) > 500:
            print(f"[+] Proxy fetch succeeded for {url}")
            return r.content if is_pdf else r.text
    except Exception as e:
        print(f"[!] Proxy fallback also failed for {url}: {e}")

    return None


# ================= 3. PDF WATERMARKING =================
def add_watermark_to_pdf(input_pdf_path, output_pdf_path):
    try:
        doc = fitz.open(input_pdf_path)
        for page in doc:
            rect = page.rect

            # Top Banner
            top_box = fitz.Rect(20, 5, rect.width - 20, 23)
            page.draw_rect(top_box, color=(0.0, 0.53, 0.8), fill=(0.90, 0.96, 1.0))
            page.insert_text(
                fitz.Point(28, 17),
                "TELEGRAM CHANNEL: @topkeralapsc  |  Click to Join: https://t.me/topkeralapsc",
                fontsize=8.5,
                fontname="helv",
                color=(0.0, 0.35, 0.65)
            )
            page.insert_link({"kind": fitz.LINK_URI, "from": top_box, "uri": CHANNEL_URL})

            # Bottom Banner
            bottom_box = fitz.Rect(20, rect.height - 25, rect.width - 20, rect.height - 6)
            page.draw_rect(bottom_box, color=(0.0, 0.53, 0.8), fill=(0.0, 0.53, 0.8))
            page.insert_text(
                fitz.Point(28, rect.height - 12),
                "JOIN TELEGRAM FOR KERALA PSC UPDATES: https://t.me/topkeralapsc (CLICK HERE)",
                fontsize=8.5,
                fontname="helv",
                color=(1.0, 1.0, 1.0)
            )
            page.insert_link({"kind": fitz.LINK_URI, "from": bottom_box, "uri": CHANNEL_URL})

            # Center Diagonal Watermark
            center_point = fitz.Point(rect.width / 5, rect.height / 1.7)
            page.insert_text(
                center_point,
                "Telegram: @topkeralapsc\nt.me/topkeralapsc",
                fontsize=26,
                fontname="helv",
                color=(0.82, 0.82, 0.82),
                rotate=45,
                overlay=False
            )

        doc.save(output_pdf_path)
        doc.close()
        return True
    except Exception as e:
        print(f"[!] Watermark error: {e}")
        return False


# ================= 4. CREATE SAMPLE PDF IF KERALAPSC SERVER IS DOWN =================
def send_demo_sample_pdf():
    """Generates and sends a real sample watermarked PDF so you can immediately verify the design."""
    print("[*] Generating sample Kerala PSC PDF to verify channel & watermark...")
    raw_pdf = "sample_raw.pdf"
    watermarked_pdf = "sample_watermarked.pdf"

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        fitz.Point(50, 80),
        "KERALA PUBLIC SERVICE COMMISSION\n"
        "SAMPLE NOTIFICATION / RANK LIST PREVIEW\n\n"
        "This is a live test document generated by your bot to confirm that:\n"
        "1. Your Telegram Bot is properly connected to @topkeralapsc\n"
        "2. The top & bottom clickable Telegram banners work properly\n"
        "3. The diagonal watermark and custom filename are active.",
        fontsize=12,
        fontname="helv"
    )
    doc.save(raw_pdf)
    doc.close()

    add_watermark_to_pdf(raw_pdf, watermarked_pdf)
    custom_filename = "PSC_Sample_Preview__Telegram_@topkeralapsc_(t.me-topkeralapsc).pdf"

    caption = (
        "🏆 <b>KERALA PSC BOT LIVE TEST PREVIEW</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>Details:</b> Sample PDF generated to verify watermark layout, clickable links, and filename formatting.\n\n"
        "📄 <b>Document:</b> Watermarked Preview PDF\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📲 <b>Telegram Search:</b> <code>@topkeralapsc</code>\n"
        "🔗 <b>Join Channel:</b> https://t.me/topkeralapsc\n\n"
        "#KeralaPSC #RankList #QuestionPaper"
    )

    with open(watermarked_pdf, "rb") as f:
        bot.send_document(
            chat_id=CHAT_ID,
            document=f,
            visible_file_name=custom_filename,
            caption=caption,
            parse_mode="HTML"
        )
    print("[+] Demo sample PDF successfully posted to channel!")
    for f in [raw_pdf, watermarked_pdf]:
        if os.path.exists(f):
            os.remove(f)


# ================= 5. SCRAPER & SENDER =================
def clean_text(text):
    return " ".join(text.split())


def scrape_table_items(source):
    items = []
    html = fetch_url(source["url"], is_pdf=False)
    if not html:
        print(f"[!] Could not load HTML from {source['url']}")
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
            "emoji": source["emoji"],
            "hashtag": source["hashtag"],
            "details": details,
            "pdfs": pdf_links
        })

    return items


def download_and_send_pdf(item, label, pdf_url):
    raw_file = "temp_raw.pdf"
    watermarked_file = "temp_watermarked.pdf"

    try:
        print(f"[*] Downloading PDF: {pdf_url}")
        pdf_bytes = fetch_url(pdf_url, is_pdf=True)
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            print(f"[!] Invalid or blocked PDF download: {pdf_url}")
            return False

        with open(raw_file, "wb") as f:
            f.write(pdf_bytes)

        watermarked_ok = add_watermark_to_pdf(raw_file, watermarked_file)
        file_to_send = watermarked_file if watermarked_ok else raw_file

        cat_upper = item["category"].upper()
        if "QUESTION" in label.upper():
            doc_prefix = "PSC_Question_Paper"
        elif "ANSWER" in label.upper() or "ANSWER" in cat_upper:
            doc_prefix = "PSC_Answer_Key"
        elif "RANK" in cat_upper:
            doc_prefix = "PSC_Rank_List"
        else:
            doc_prefix = "Kerala_PSC_Update"

        custom_filename = f"{doc_prefix}__Telegram_@topkeralapsc_(t.me-topkeralapsc).pdf"

        caption = (
            f"{item['emoji']} <b>KERALA PSC {item['category']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Details:</b> {item['details']}\n\n"
            f"📄 <b>Document:</b> {label}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📲 <b>Telegram Search:</b> <code>@topkeralapsc</code>\n"
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

        print(f"[+] Successfully posted: {custom_filename}")
        time.sleep(3)
        return True

    except Exception as e:
        print(f"[!] Error sending PDF to Telegram: {e}")
        return False

    finally:
        for f in [raw_file, watermarked_file]:
            if os.path.exists(f):
                os.remove(f)


def load_posted_links():
    if FORCE_SEED or not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_posted_link(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{link}\n")


def main():
    # Step 1: Verify bot can talk to @topkeralapsc (fails loud if token/admin is wrong)
    verify_telegram_connection()

    posted_links = load_posted_links()
    total_sent = 0

    for source in SOURCES:
        print(f"[*] Scraping {source['name']} ({source['url']})...")
        items = scrape_table_items(source)
        print(f"    -> Found {len(items)} items with PDFs.")

        for item in reversed(items[:SEED_LIMIT_PER_CATEGORY]):
            for label, pdf_url in item["pdfs"]:
                if pdf_url not in posted_links:
                    if download_and_send_pdf(item, label, pdf_url):
                        save_posted_link(pdf_url)
                        posted_links.add(pdf_url)
                        total_sent += 1

    # Step 3: If keralapsc.gov.in blocked GitHub's IP completely, send a generated sample PDF
    # so you can still see the exact watermarked PDF and post layout in your channel!
    if total_sent == 0:
        print("[!] 0 live PDFs fetched (Kerala PSC server likely blocked GitHub US IP). Sending live Demo PDF...")
        send_demo_sample_pdf()

    print(f"[*] Run complete! Total live PDFs sent: {total_sent}")


if __name__ == "__main__":
    main()
