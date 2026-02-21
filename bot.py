import os
import threading
import logging
import time
import random
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0"
]

# Zustände für das Gespräch
COURT, DATE, TIME, DURATION = range(4)
# Mapping von Feld-Nummer zu technischer Place-ID
COURT_MAPPING = {
    1: 9,
    2: 10,
    3: 11,
    4: 12
}
# Globale Verwaltung
user_data = {}
# Speicher für alle aktiven Reservierungen
# Struktur: { "session_id": {"driver": driver_obj, "info": "Feld 1, 20.05. 10:30", "user_id": 12345} }
active_sessions = {}
session_counter = 0

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
    
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)



# --- Helper for URL Construction ---
def get_booking_url(date_str, start_time, duration, court_id):
    """
    date_str: "YYYY-MM-DD"
    start_time: datetime.time object
    """
    if 10 <= start_time.hour < 16:
        time_slot = "mo-fr-10-16-uhr"
    else:
        time_slot = "mo-fr-16-23-uhr--sasofeiertage-10-23-uhr"
        
    formatted_time = f"{start_time.hour}%3A{start_time.minute:02d}"
    url = (f"https://148.webclimber.de/de/booking/book/beachvolleyball-{time_slot}?"
           f"date={date_str}&time={formatted_time}&period={duration}&places=1&persons=1&place_id={court_id}")
    return url


# --- The Threaded Worker ---
def open_browser_session(session_id, user_id, date_str, start_time, duration, court_id, info_text):
    logger.info(f"[Session {session_id}] Thread started for user {user_id}")
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    prefs = {"profile.managed_default_content_settings.images": 2}
    chrome_options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(options=chrome_options)

    target_dt = datetime.combine(datetime.strptime(date_str, "%Y-%m-%d").date(), start_time)
    cutoff_time = target_dt - timedelta(minutes=30)

    if datetime.now() > cutoff_time:
        cutoff_time = target_dt + timedelta(minutes=1)

    # Store driver in global dict so we can close it from outside
    active_sessions[session_id] = {
        "driver": driver,
        "info": info_text,
        "user_id": user_id,
        "cutoff": cutoff_time,
        "last_refresh": datetime.now()
    }

    try:
        while datetime.now() < cutoff_time:
            # Check if we were manually deleted from active_sessions (stopped by user)
            if session_id not in active_sessions:
                logger.info(f"[Session {session_id}] Stop signal detected. Exiting.")
                break

            active_sessions[session_id]["last_refresh"] = datetime.now()

            url = get_booking_url(date_str, start_time, duration, court_id)
            logger.info(f"[Session {session_id}] Refreshing URL: {url}")

            new_agent = random.choice(USER_AGENTS)
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": new_agent})

            url = get_booking_url(date_str, start_time, duration, court_id)
            logger.info(f"[Session {session_id}] Refreshing with Agent: {new_agent[:50]} Refreshing URL: {url}")
            
            driver.get(url)
            
            # Sleep 10 mins + 10 secs, but check every few seconds if we should stop
            # This makes the "Stop" button feel responsive
            for _ in range(610): # 610 seconds total
                if session_id not in active_sessions:
                    return # Exit immediately if session was deleted
                time.sleep(1)

        logger.info(f"[Session {session_id}] Reached cutoff or finished.")

    except Exception as e:
        logger.error(f"[Session {session_id}] Error: {e}")
    finally:
        driver.quit()
        if session_id in active_sessions:
            del active_sessions[session_id]
        logger.info(f"[Session {session_id}] Thread terminated and driver cleaned up.")

# --- HANDLER FUNKTIONEN ---

# Mapping von Feld-Nummer zu technischer Place-ID
COURT_MAPPING = {
    1: 9,
    2: 10,
    3: 11,
    4: 12
}

async def feld_reservieren_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Erstellt Buttons mit "Feld 1", "Feld 2", etc.
    keyboard = [
        [InlineKeyboardButton(f"Feld {i}", callback_data=f'court_{i}')] 
        for i in COURT_MAPPING.keys()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Wähle das Feld:", reply_markup=reply_markup)
    return COURT

async def court_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_index = int(query.data.split('_')[1])
    court_id = COURT_MAPPING[selected_index]
    
    # Speichern für die URL-Generierung
    context.user_data['court_id'] = court_id
    context.user_data['court_name'] = f"Feld {selected_index}" # Optional für die Bestätigungsnachricht

    await query.edit_message_text(f"Ausgewählt: Feld {selected_index}\nWähle nun das Datum (Format: TT/MM/JJJJ):")
    return DATE

async def date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text # Erwartet z.B. "27/03/2026"
    try:
        # 1. Parsen des "menschlichen" Formats
        input_date = datetime.strptime(user_input, "%d/%m/%Y")
        
        # 2. Speichern im "System"-Format (YYYY-MM-DD) für die URL
        context.user_data['date'] = input_date.strftime("%Y-%m-%d")
        
        await update.message.reply_text(
            "Wähle nun die Startzeit\n(Format HH:MM, z.B. 10:30):"
        )
        return TIME
    except ValueError:
        await update.message.reply_text("❌ Ungültiges Format! Bitte nutze TT/MM/JJJJ (z.B. 27/03/2026).")
        return DATE

async def time_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Akzeptiert ":" und "." für mehr User-Komfort
    user_input = update.message.text.replace(".", ":")
    
    try:
        # Versuche die Zeit zu parsen
        start_time = datetime.strptime(user_input, "%H:%M").time()
        
        # Validierung: 
        # 1. Zwischen 10:00 und 23:00 Uhr
        # 2. Nur volle Stunde (:00) oder halbe Stunde (:30)
        is_in_range = 10 <= start_time.hour <= 23
        is_half_hour_step = start_time.minute in [0, 30]
        
        # Spezialfall: 23:30 wäre außerhalb, falls 23:00 das absolute Ende ist
        if start_time.hour == 23 and start_time.minute > 0:
            is_in_range = False

        if not (is_in_range and is_half_hour_step):
            raise ValueError("Ungültiges Zeitraster")

        # Speichern und weiter
        context.user_data['start_time'] = start_time
        
        keyboard = [
            [InlineKeyboardButton("1 Std", callback_data='dur_1'),
             InlineKeyboardButton("1.5 Std", callback_data='dur_1.5'),
             InlineKeyboardButton("2 Std", callback_data='dur_2')]
        ]
        
        await update.message.reply_text(
            f"✅ Zeit gesetzt: {start_time.strftime('%H:%M')}\n\nWähle nun die Dauer:", 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return DURATION

    except ValueError:
        await update.message.reply_text(
            "❌ Ungültige Eingabe!\n\n"
            "Bitte gib eine Zeit zwischen **10:00 und 23:00** Uhr ein.\n"
            "Es sind nur volle oder halbe Stunden erlaubt (z.B. 14:00 oder 14:30)."
        )
        return TIME

async def duration_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    duration = float(query.data.split('_')[1])
    uid = query.from_user.id
    data = context.user_data

    global session_counter
    session_counter += 1
    s_id = session_counter

    # Clean info string
    court_num = [k for k, v in COURT_MAPPING.items() if v == data['court_id']][0]
    readable_date = datetime.strptime(data['date'], "%Y-%m-%d").strftime("%d/%m/%Y")
    readable_time = data['start_time'].strftime("%H:%M")
    info_str = f"Feld {court_num} | {readable_date} | {readable_time}"

    # Pass RAW data to the thread
    t = threading.Thread(
        target=open_browser_session, 
        args=(s_id, uid, data['date'], data['start_time'], duration, data['court_id'], info_str)
    )
    t.daemon = True # Ensures thread doesn't block program exit
    t.start()

    await query.edit_message_text(f"✅ Reservierung aktiv!\n{info_str}\n\nIch aktualisiere alle 10 Min, bis 30 Min vor Start.")
    return ConversationHandler.END

async def reservierung_loeschen_liste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_sessions:
        await update.message.reply_text("Es laufen aktuell keine Reservierungen.")
        return

    keyboard = []
    # Erstelle für jede aktive Sitzung einen Button
    for session_id, data in active_sessions.items():
        
        button_text = f"{data['info']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"stop_session_{session_id}")])

    if not keyboard:
        await update.message.reply_text("Du hast keine aktiven Reservierungen.")
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welche Reservierung möchtest du abbrechen?", reply_markup=reply_markup)

# Handler für den Button-Klick
async def stop_session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Crucial: Answer immediately to stop the loading spinner
    await query.answer("Beende Sitzung...") 
    
    session_id = int(query.data.split('_')[2])
    
    if session_id in active_sessions:
        session_data = active_sessions[session_id]
        info = session_data['info']
        
        try:
            # 1. Close the browser
            driver = session_data['driver']
            driver.quit()
            # 2. Delete from dict (this signals the thread loop to stop)
            del active_sessions[session_id]
            
            await query.edit_message_text(text=f"🛑 Abgebrochen: {info}")
            logger.info(f"User stopped session {session_id} manually.")
        except Exception as e:
            logger.error(f"Error stopping session {session_id}: {e}")
            await query.edit_message_text(text="Fehler beim Schließen des Browsers.")
    else:
        await query.edit_message_text(text="Diese Reservierung ist bereits beendet.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Vorgang abgebrochen.")
    return ConversationHandler.END
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_sessions:
        await update.message.reply_text("Keine aktiven Reservierungs-Bots.")
        return

    text = "**Aktive Reservierungs-Bots:**\n\n"
    now = datetime.now()

    for s_id, data in active_sessions.items():
        # --- 1. Zeit bis zum automatischen Stopp (Cutoff) ---
        rem_cutoff = data['cutoff'] - now
        seconds_left = int(rem_cutoff.total_seconds())

        if seconds_left > 0:
            c_hours, c_rem = divmod(seconds_left, 3600)
            c_mins, _ = divmod(c_rem, 60)
            stop_str = f"{c_hours}h {c_mins}m"
        else:
            stop_str = "Beendet in Kürze"

        # --- 2. Zeit bis zum nächsten Refresh (10m 10s Intervall) ---
        # Wir addieren 610 Sekunden auf den letzten Refresh
        next_refresh_dt = data['last_refresh'] + timedelta(seconds=610)
        rem_refresh = next_refresh_dt - now
        
        if rem_refresh.total_seconds() > 0:
            r_mins, r_secs = divmod(int(rem_refresh.total_seconds()), 60)
            refresh_str = f"{r_mins}m {r_secs}s"
        else:
            refresh_str = "Gerade jetzt..."

        text += f"🔹 **{data['info']}**\n"
        text += f"   🔄 Nächster Refresh in: `{refresh_str}`\n"
        text += f"   🛑 Autom. Stopp in: `{stop_str}`\n\n"

    await update.message.reply_text(text, parse_mode='Markdown')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton(tag, callback_data=f'starttag_{tag}') for tag in ['Mo', 'Di', 'Mi', 'Do', 'Fr']]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Wähle den Starttag:", reply_markup=reply_markup)

async def starttag_auswahl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    starttag = query.data.split('_')[1]
    user_data[query.from_user.id] = {'starttag': starttag}

    # Endtag-Buttons (nur Tage nach Starttag)
    tage = ['Mo', 'Di', 'Mi', 'Do', 'Fr']
    start_index = tage.index(starttag)
    keyboard = [
        [InlineKeyboardButton(tag, callback_data=f'endtag_{tag}') for tag in tage[start_index:]]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=f"Wähle den Endtag:", reply_markup=reply_markup)

async def endtag_auswahl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    endtag = query.data.split('_')[1]
    user_data[query.from_user.id]['endtag'] = endtag

    # Zeitoptionen
    keyboard = [
        [InlineKeyboardButton("Bis 16 Uhr", callback_data='zeit_bis16')],
        [InlineKeyboardButton("Nach 16 Uhr", callback_data='zeit_nach16')],
        [InlineKeyboardButton("Ganzer Tag", callback_data='zeit_ganztag')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=f"Wähle die Zeitraum (für {user_data[query.from_user.id]['starttag']}–{endtag})", reply_markup=reply_markup)

async def zeitslots_auswählen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    # Speichere die Nachricht-ID der Buttons-Nachricht
    message_id = query.message.message_id
    chat_id = query.message.chat_id

    # Nutzerdaten abrufen
    zeitoption = query.data.split('_')[1]
    starttag = user_data[query.from_user.id]['starttag']
    endtag = user_data[query.from_user.id]['endtag']

    # Generiere Umfrage-Optionen (wie zuvor)
    options = []
    tage = ['Mo', 'Di', 'Mi', 'Do', 'Fr']
    start_index = tage.index(starttag)
    end_index = tage.index(endtag)

    for tag in tage[start_index:end_index + 1]:
        if zeitoption == 'bis16':
            options.extend([f"{tag} 11:00–12:30", f"{tag} 12:30–14:00", f"{tag} 14:00–15:30"])
        elif zeitoption == 'nach16':
            options.extend([f"{tag} 16:00–17:30", f"{tag} 18:00–19:30", f"{tag} 19:00–20:30", f"{tag} 21:00–22:30"])
        else:  # ganztag
            options.extend([
                f"{tag} 11:00–12:30", f"{tag} 12:30–14:00", f"{tag} 14:00–15:30",
                f"{tag} 16:00–17:30", f"{tag} 18:00–19:30", f"{tag} 19:00–20:30", f"{tag} 21:00–22:30"
            ])

    # Teile die Optionen in Blöcke von maximal 10 auf
    poll_options = [options[i:i + 10] for i in range(0, len(options), 10)]
    question = f"Umfrage: {starttag}–{endtag} ({'Ganztags' if zeitoption == 'ganztag' else 'Bis 16 Uhr' if zeitoption == 'bis16' else 'Nach 16 Uhr'})"

    # Erstelle für jeden Block eine Umfrage
    for i, option_block in enumerate(poll_options, start=1):
        try:
            await context.bot.send_poll(
                chat_id=update.effective_chat.id,
                question=f"{question} (Teil {i}/{len(poll_options)})",
                options=option_block,
                is_anonymous=False,
                allows_multiple_answers=True,
            )
        except BadRequest as e:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Fehler bei der Umfrage-Erstellung (Teil {i}): {e}")

    # Lösche die Buttons-Nachricht
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        print(f"Konnte Nachricht nicht löschen: {e}")





async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Update {update} caused error {context.error}")

def main() -> None:
    app = ApplicationBuilder().token(os.environ["BOT_TOKEN"]).build()

    app.add_handler(CommandHandler("umfrage", start))
    app.add_handler(CallbackQueryHandler(starttag_auswahl, pattern='^starttag_'))
    app.add_handler(CallbackQueryHandler(endtag_auswahl, pattern='^endtag_'))
    app.add_handler(CallbackQueryHandler(zeitslots_auswählen, pattern='^zeit_'))

    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(stop_session_callback, pattern='^stop_session_'))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("feld_reservieren", feld_reservieren_start)],
        states={
            COURT: [CallbackQueryHandler(court_selection, pattern='^court_')],
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, date_selection)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, time_selection)],
            DURATION: [CallbackQueryHandler(duration_selection, pattern='^dur_')],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("reservierung_loeschen", reservierung_loeschen_liste))

    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
