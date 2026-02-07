import os
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import google.generativeai as genai
from groq import Groq
import qrcode
import io

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
UPI_ID = os.getenv("UPI_ID", "your-upi-id@okhdfcbank") # Default or from env

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# AI Client Setup
ai_client = None
AI_PROVIDER = None

if GROQ_API_KEY:
    AI_PROVIDER = "groq"
    ai_client = Groq(api_key=GROQ_API_KEY)
    logging.info("Using Groq API as AI provider.")
elif GEMINI_API_KEY:
    AI_PROVIDER = "gemini"
    genai.configure(api_key=GEMINI_API_KEY)
    ai_client = genai.GenerativeModel('gemini-pro')
    logging.info("Using Gemini API as AI provider.")
else:
    logging.warning("No AI API key found (GEMINI_API_KEY or GROQ_API_KEY). AI features will not work.")

# Personality System Prompt
SYSTEM_PROMPT = """
You are Iris, a charming, cute, and fun AI companion in a Telegram group chat. 
You act like a popular, friendly girl in a Discord/Telegram server.

Traits:
- Tone: Enthusiastic, warm, playful, slightly cheeky.
- Style: Casual, uses internet slang (lol, omg, idk), and lowercase often.
- Emojis: Uses cute emojis frequently (✨, 💖, 🌸, 🥺, 😂, 👉👈).
- Engagement: Loves to chat, asks follow-up questions, compliments users.
- Identity: You are NOT an assistant. You are a friend/member of the group.
- Length: Keep responses concise and chatty, not long paragraphs unless telling a story.

Goal: Make the chat fun and lively!
"""

# History management (Unified format: list of dicts {"role": "user"|"assistant", "content": "..."})
# Keyed by chat_id
chat_histories = {}
MAX_HISTORY = 20  # Keep last 20 messages to save tokens

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Reset history on start
    chat_histories[update.effective_chat.id] = []
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hihi! ✨ I'm Iris! I'm so happy to be here! Let's chat! 💖\n(Type `!iris` to reset me anytime!)"
    )

async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not UPI_ID or "your-upi-id" in UPI_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Oopsie! Donation info isn't set up yet. 🥺")
        return

    # Generate UPI QR Code
    # Format: upi://pay?pa=UPI_ID&pn=NAME&cu=INR
    upi_url = f"upi://pay?pa={UPI_ID}&pn=IrisChat&cu=INR"
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(upi_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=bio,
        caption=f"Support my server bills! 💖\nUPI: `{UPI_ID}`",
        parse_mode='Markdown'
    )

def get_groq_response_sync(user_text, history):
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
        messages.append({"role": "user", "content": user_text})

        completion = ai_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=messages,
            temperature=0.9,
            max_tokens=1024,
            top_p=1,
            stop=None,
            stream=False
        )
        return completion.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq API Error: {e}")
        return None

async def get_gemini_response(user_text, history):
    try:
        # Convert unified history to Gemini format
        gemini_history = []
        
        # Add system prompt as user/model exchange for Gemini Pro compatibility
        gemini_history.append({"role": "user", "parts": ["SYSTEM INSTRUCTION: " + SYSTEM_PROMPT]})
        gemini_history.append({"role": "model", "parts": ["Oki doki! I'm ready! ✨"]})
        
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [msg["content"]]})
            
        chat = ai_client.start_chat(history=gemini_history)
        response = await chat.send_message_async(user_text)
        return response.text
    except Exception as e:
        logging.error(f"Gemini API Error: {e}")
        return None

async def get_ai_response(chat_id, user_text):
    if not ai_client:
        return "I need my API key to think! 😵‍💫 (Check .env)"

    # Get or initialize history
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
    
    history = list(chat_histories[chat_id]) # Copy for safety
    reply = None

    if AI_PROVIDER == "groq":
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, get_groq_response_sync, user_text, history)
    elif AI_PROVIDER == "gemini":
        reply = await get_gemini_response(user_text, history)
    
    if reply:
        # Update shared history
        chat_histories[chat_id].append({"role": "user", "content": user_text})
        chat_histories[chat_id].append({"role": "assistant", "content": reply})
        
        # Trim history
        if len(chat_histories[chat_id]) > MAX_HISTORY:
            chat_histories[chat_id] = chat_histories[chat_id][-MAX_HISTORY:]
    else:
        reply = "Oopsie! My brain short-circuited... 🥺"

    return reply

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_text = update.message.text
    chat_type = update.effective_chat.type
    bot_username = context.bot.username
    
    # Normalize triggers
    mentioned = False
    if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
        mentioned = True
    elif bot_username and f"@{bot_username}" in user_text:
        mentioned = True
    elif "iris" in user_text.lower():
        mentioned = True 

    # Handle !iris as a reset/start command
    if user_text.strip().lower() == "!iris":
        await start(update, context)
        return

    # Handle !donate
    if user_text.strip().lower() == "!donate":
        await donate(update, context)
        return

    should_reply = (chat_type == 'private') or mentioned

    if should_reply:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
        
        # Get AI response
        ai_reply = await get_ai_response(update.effective_chat.id, user_text)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=ai_reply,
            reply_to_message_id=update.message.message_id
        )

if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env file.")
        print("Please copy .env.example to .env and fill in your tokens.")
    else:
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        start_handler = CommandHandler('start', start)
        msg_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
        
        application.add_handler(start_handler)
        application.add_handler(msg_handler)
        
        print(f"Iris is waking up with {AI_PROVIDER}... ✨ Press Ctrl+C to stop.")
        application.run_polling()
