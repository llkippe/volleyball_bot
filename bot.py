import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.error import BadRequest

# Globale Variable für Nutzerdaten
user_data = {}

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
            options.extend([f"{tag} 11:00–12:30", f"{tag} 14:00–15:30"])
        elif zeitoption == 'nach16':
            options.extend([f"{tag} 16:00–17:30", f"{tag} 18:00–19:30", f"{tag} 19:00–20:30", f"{tag} 21:00–22:30"])
        else:  # ganztag
            options.extend([
                f"{tag} 11:00–12:30", f"{tag} 14:00–15:30",
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

    app.add_handler(CommandHandler("umfrage_erstellen", start))
    app.add_handler(CallbackQueryHandler(starttag_auswahl, pattern='^starttag_'))
    app.add_handler(CallbackQueryHandler(endtag_auswahl, pattern='^endtag_'))
    app.add_handler(CallbackQueryHandler(zeitslots_auswählen, pattern='^zeit_'))

    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
