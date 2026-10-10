# ================= UPGRADED PDF WATERMARKING =================
def add_watermark_to_pdf(input_pdf_path, output_pdf_path):
    """Adds a prominent clickable Telegram banner (top & bottom) and clear diagonal watermark."""
    try:
        doc = fitz.open(input_pdf_path)
        for page in doc:
            rect = page.rect
            
            # --- 1. TOP TELEGRAM BANNER (Clickable Blue Box) ---
            top_box = fitz.Rect(20, 5, rect.width - 20, 23)
            # Draw a light Telegram-blue background strip at the top
            page.draw_rect(top_box, color=(0.0, 0.53, 0.8), fill=(0.90, 0.96, 1.0))
            
            top_text = "TELEGRAM CHANNEL: @topkeralapsc  |  Click to Join: https://t.me/topkeralapsc"
            page.insert_text(
                fitz.Point(30, 17),
                top_text,
                fontsize=8.5,
                fontname="helv",
                color=(0.0, 0.35, 0.65)
            )
            page.insert_link({
                "kind": fitz.LINK_URI,
                "from": top_box,
                "uri": CHANNEL_URL
            })

            # --- 2. BOTTOM TELEGRAM BANNER (Clickable Solid Blue Bar) ---
            bottom_box = fitz.Rect(20, rect.height - 25, rect.width - 20, rect.height - 6)
            page.draw_rect(bottom_box, color=(0.0, 0.53, 0.8), fill=(0.0, 0.53, 0.8))
            
            footer_text = "JOIN TELEGRAM FOR KERALA PSC UPDATES: https://t.me/topkeralapsc (CLICK HERE)"
            page.insert_text(
                fitz.Point(30, rect.height - 12),
                footer_text,
                fontsize=8.5,
                fontname="helv",
                color=(1.0, 1.0, 1.0)  # White text on Telegram blue bar
            )
            page.insert_link({
                "kind": fitz.LINK_URI,
                "from": bottom_box,
                "uri": CHANNEL_URL
            })

            # --- 3. CENTER DIAGONAL WATERMARK (Explicitly says Telegram) ---
            center_point = fitz.Point(rect.width / 5, rect.height / 1.7)
            watermark_text = "Telegram: @topkeralapsc\nt.me/topkeralapsc"
            page.insert_text(
                center_point,
                watermark_text,
                fontsize=28,
                fontname="helv",
                color=(0.82, 0.82, 0.82),  # Subtle light grey
                rotate=45,
                overlay=False
            )

        doc.save(output_pdf_path)
        doc.close()
        return True
    except Exception as e:
        print(f"[!] Watermark error: {e}")
        return False


# ================= UPGRADED FILENAME & SENDER =================
def download_and_send_pdf(item, label, pdf_url):
    """Downloads PDF, watermarks it, and sends it with a clear Telegram filename."""
    raw_file = "temp_raw.pdf"
    watermarked_file = "temp_watermarked.pdf"

    try:
        print(f"[*] Downloading PDF: {pdf_url}")
        r = requests.get(pdf_url, headers=HEADERS, verify=False, timeout=30)
        if r.status_code != 200:
            print(f"[!] Failed to download PDF: {r.status_code}")
            return False

        with open(raw_file, "wb") as f:
            f.write(r.content)

        # Apply watermark
        watermarked_ok = add_watermark_to_pdf(raw_file, watermarked_file)
        file_to_send = watermarked_file if watermarked_ok else raw_file

        # Identify the document type for a clear filename
        cat_upper = item["category"].upper()
        if "QUESTION" in label.upper():
            doc_prefix = "PSC_Question_Paper"
        elif "ANSWER" in label.upper() or "ANSWER" in cat_upper:
            doc_prefix = "PSC_Answer_Key"
        elif "RANK" in cat_upper:
            doc_prefix = "PSC_Rank_List"
        elif "SHORT" in cat_upper:
            doc_prefix = "PSC_Short_List"
        else:
            doc_prefix = "Kerala_PSC_Notification"

        # Explicitly include 'Telegram_@topkeralapsc' and 't.me-topkeralapsc' in filename
        custom_filename = f"{doc_prefix}__Telegram_@topkeralapsc_(t.me-topkeralapsc).pdf"

        # Format Telegram Caption
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
        print(f"[!] Error sending to Telegram: {e}")
        return False

    finally:
        for f in [raw_file, watermarked_file]:
            if os.path.exists(f):
                os.remove(f)
