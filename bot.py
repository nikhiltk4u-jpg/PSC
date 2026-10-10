import os
import json
import time
import urllib3
import requests
from bs4 import BeautifulSoup
import telebot

# Govt site SSL warning ozhivakkan
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_ID = os.environ.get('CHANNEL_ID') # Eg: @keralapsc_updates
bot = telebot.TeleBot(BOT_TOKEN)

DB_FILE = 'posted_data.json'
BASE_URL = "https://www.keralapsc.gov.in"

# Website block cheyyathirikkan normal browser pole act cheyyunnu
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    return []

def save_db(data):
    # File valuthavathirikkan avasanathe 500 items mathram save cheyyunnu
    with open(DB_FILE, 'w') as f:
        json.dump(data[-500:], f, indent=2)

def get_pdf_link(row):
    a_tag = row.find('a', href=True)
    if a_tag and '.pdf' in a_tag['href'].lower():
        href = a_tag['href']
        return href if href.startswith('http') else BASE_URL + href
    return None

def send_item_to_telegram(caption, pdf_url, file_prefix):
    try:
        if pdf_url:
            pdf_res = requests.get(pdf_url, headers=HEADERS, verify=False, timeout=20)
            if pdf_res.status_code == 200:
                file_name = f"{file_prefix}.pdf"
                bot.send_document(
                    CHANNEL_ID, 
                    (file_name, pdf_res.content), 
                    caption=caption, 
                    parse_mode='HTML'
                )
                time.sleep(3) # Telegram flood limit ozhivakkan
                return True
        
        # PDF illengil allengil download fail aayal text mathram ayakkum
        bot.send_message(CHANNEL_ID, caption, parse_mode='HTML', disable_web_page_preview=True)
        time.sleep(2)
        return True
    except Exception as e:
        print(f"Telegram Error: {e}")
        return False

def scrape_notifications(posted_ids):
    url = f"{BASE_URL}/notifications"
    try:
        res = requests.get(url, headers=HEADERS, verify=False, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for row in soup.find_all('tr')[1:6]: # Latest 5 notifications nokkunnu
            cols = row.find_all('td')
            if len(cols) >= 3:
                post_name = cols[0].text.strip()
                cat_no = cols[1].text.strip()
                last_date = cols[2].text.strip()
                pdf_url = get_pdf_link(row)
                
                unique_id = f"NOTIF_{cat_no}"
                if cat_no and unique_id not in posted_ids:
                    caption = (
                        f"🔔 <b>PUTHIYA PSC NOTIFICATION</b> 🔔\n\n"
                        f"📌 <b>Post:</b> {post_name}\n"
                        f"🏷 <b>Category No:</b> <code>{cat_no}</code>\n"
                        f"⏳ <b>Last Date:</b> {last_date}\n"
                        f"💰 <b>Fee:</b> Nil (One Time Registration vazhi)\n\n"
                        f"📋 <i>Qualification, Age limit, Syllabus enniva ariyan attached PDF nokkuka.</i>\n\n"
                        f"🔗 <a href='https://thulasi.psc.kerala.gov.in/thulasi/'>Apply Online (Thulasi Profile)</a>"
                    )
                    if send_item_to_telegram(caption, pdf_url, f"Notification_Cat_{cat_no.replace('/', '_')}"):
                        posted_ids.append(unique_id)
    except Exception as e:
        print(f"Notification Scrape Error: {e}")

def scrape_ranklists(posted_ids):
    url = f"{BASE_URL}/ranked-list"
    try:
        res = requests.get(url, headers=HEADERS, verify=False, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for row in soup.find_all('tr')[1:6]:
            cols = row.find_all('td')
            if len(cols) >= 3:
                post_name = cols[0].text.strip()
                cat_no = cols[1].text.strip()
                dept = cols[2].text.strip()
                pdf_url = get_pdf_link(row)
                
                unique_id = f"RANK_{cat_no}_{post_name[:10]}"
                if cat_no and unique_id not in posted_ids:
                    caption = (
                        f"🏆 <b>PSC RANK LIST PUBLISHED</b> 🏆\n\n"
                        f"📌 <b>Post:</b> {post_name}\n"
                        f"🏢 <b>Dept:</b> {dept}\n"
                        f"🏷 <b>Category No:</b> <code>{cat_no}</code>\n\n"
                        f"📊 <i>Rank List-um Minimum Cut-off Mark-um thazhe ulla PDF-il undu.</i>"
                    )
                    if send_item_to_telegram(caption, pdf_url, f"RankList_{cat_no.replace('/', '_')}"):
                        posted_ids.append(unique_id)
    except Exception as e:
        print(f"Ranklist Scrape Error: {e}")

def scrape_question_papers(posted_ids):
    url = f"{BASE_URL}/examination/question-paper"
    try:
        res = requests.get(url, headers=HEADERS, verify=False, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for row in soup.find_all('tr')[1:6]:
            cols = row.find_all('td')
            if len(cols) >= 2:
                exam_name = cols[0].text.strip()
                q_code = cols[1].text.strip()
                pdf_url = get_pdf_link(row)
                
                unique_id = f"QP_{q_code}_{exam_name[:10]}"
                if q_code and unique_id not in posted_ids:
                    caption = (
                        f"📄 <b>PSC QUESTION PAPER</b> 📄\n\n"
                        f"📝 <b>Exam:</b> {exam_name}\n"
                        f"🔢 <b>QP Code:</b> <code>{q_code}</code>\n\n"
                        f"✅ <i>Adutha exam-nu padikkunnavarkku ee question paper download cheythu practice cheyyam!</i>"
                    )
                    if send_item_to_telegram(caption, pdf_url, f"QP_{q_code.replace('/', '_')}"):
                        posted_ids.append(unique_id)
    except Exception as e:
        print(f"QP Scrape Error: {e}")

if __name__ == "__main__":
    posted_ids = load_db()
    initial_count = len(posted_ids)
    
    scrape_notifications(posted_ids)
    scrape_ranklists(posted_ids)
    scrape_question_papers(posted_ids)
    
    if len(posted_ids) > initial_count:
        save_db(posted_ids)
        print(f"Added {len(posted_ids) - initial_count} new items.")
    else:
        print("No new updates found.")
