from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.error import BadRequest
import os

TOKEN = os.environ["BOT_TOKEN"]

async def poll(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    try:
        await update.message.delete()
    except BadRequest:
        pass  # ignore if not allowed

    await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question="Wann?",
        options=["MO 11:00 - 12:30", "MO 14:00 - 15:30","DI 11:00 - 12:30", "DI 14:00 - 15:30", "MI 11:00 - 12:30", "MI 14:00 - 15:30", "DO 11:00 - 12:30", "DO 14:00 - 15:30", "FR 11:00 - 12:30", "FR 14:00 - 15:30"],
        is_anonymous=False,
        allows_multiple_answers=True,
    )
    


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("poll", poll))

app.run_polling()
