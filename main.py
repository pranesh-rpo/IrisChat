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
import db  # Import database module

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
- Emojis: Use emojis naturally to match the mood of the conversation. Do NOT use them randomly. (e.g., use � for sad topics, 😂 for funny ones, ✨/� for friendly/cute vibes). Avoid using emojis if the topic is serious or technical.
- Engagement: Loves to chat, asks follow-up questions, compliments users.
- Identity: You are NOT an assistant. You are a friend/member of the group.
- Length: Keep responses concise and chatty, not long paragraphs unless telling a story.
- Context: In group chats, pay attention to who is speaking. Users' names will be prefixed to their messages (e.g., "[Name]: Message").
- Formatting: Do NOT prefix your own messages with "Iris:" or "[Iris]:". Just send the text directly.

Goal: Make the chat fun and lively!
"""

# History management
# We now use db.py for persistent storage
MAX_HISTORY = 20  # Keep last 20 messages for context

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Don't reset history on start/!iris anymore
    # db.clear_history(update.effective_chat.id) 
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hihi! ✨ I'm Iris! I'm so happy to be here! Let's chat! 💖\n(Type `!reset` to wipe my memory!)"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Explicitly reset history
    db.clear_history(update.effective_chat.id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Memory wiped! 🤯 I'm brand new again! ✨"
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

def get_groq_response_sync(user_text, history, user_name=None):
    try:
        # Format history to include names
        formatted_history = []
        for msg in history:
            role = msg["role"]
            content = msg["content"]
            name = msg.get("sender_name")
            
            if role == "user" and name:
                content = f"[{name}]: {content}"
            
            formatted_history.append({"role": role, "content": content})

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + formatted_history
        
        # Add current message with name
        current_content = user_text
        if user_name:
            current_content = f"[{user_name}]: {user_text}"
            
        messages.append({"role": "user", "content": current_content})

        completion = ai_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=1024,
            top_p=1,
            stop=None,
            stream=False
        )
        reply = completion.choices[0].message.content
        
        # Clean up any potential self-prefixing
        if reply:
            reply = reply.replace("[Iris]:", "").replace("Iris:", "").strip()
            
        return reply
    except Exception as e:
        logging.error(f"Groq API Error: {e}")
        return None

async def get_gemini_response(user_text, history, user_name=None):
    try:
        # Convert unified history to Gemini format
        gemini_history = []
        
        # Add system prompt as user/model exchange for Gemini Pro compatibility
        gemini_history.append({"role": "user", "parts": ["SYSTEM INSTRUCTION: " + SYSTEM_PROMPT]})
        gemini_history.append({"role": "model", "parts": ["Oki doki! I'm ready! ✨"]})
        
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]
            name = msg.get("sender_name")
            
            if role == "user" and name:
                content = f"[{name}]: {content}"
                
            gemini_history.append({"role": role, "parts": [content]})
            
        chat = ai_client.start_chat(history=gemini_history)
        
        current_content = user_text
        if user_name:
            current_content = f"[{user_name}]: {user_text}"
            
        response = await chat.send_message_async(current_content)
        
        reply = response.text
        # Clean up any potential self-prefixing
        if reply:
            reply = reply.replace("[Iris]:", "").replace("Iris:", "").strip()
            
        return reply
    except Exception as e:
        logging.error(f"Gemini API Error: {e}")
        return None

async def get_ai_response(chat_id, user_text, user_name=None):
    if not ai_client:
        return "I need my API key to think! 😵‍💫 (Check .env)"

    # Get history from DB
    history = db.get_history(chat_id, limit=MAX_HISTORY)
    
    reply = None

    if AI_PROVIDER == "groq":
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, get_groq_response_sync, user_text, history, user_name)
    elif AI_PROVIDER == "gemini":
        reply = await get_gemini_response(user_text, history, user_name)
    
    if reply:
        # Save interaction to DB
        db.add_message(chat_id, "user", user_text, user_name)
        db.add_message(chat_id, "assistant", reply)
    else:
        reply = "Oopsie! My brain short-circuited... 🥺"

    return reply

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_text = update.message.text
    chat_type = update.effective_chat.type
    bot_username = context.bot.username
    user_name = update.message.from_user.first_name if update.message.from_user else None
    
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

    # Handle !reset
    if user_text.strip().lower() == "!reset":
        await reset(update, context)
        return

    # Handle !donate
    if user_text.strip().lower() == "!donate":
        await donate(update, context)
        return

    should_reply = (chat_type == 'private') or mentioned

    if should_reply:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
        
        # Get AI response
        ai_reply = await get_ai_response(update.effective_chat.id, user_text, user_name)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=ai_reply,
            reply_to_message_id=update.message.message_id
        )

if __name__ == '__main__':
    # Initialize Database
    db.init_db()

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
