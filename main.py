import os
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from telegram.request import HTTPXRequest
import re # Regex for stripping prefixes
import socket
import struct

# AI Libraries
from google import genai
from groq import Groq
import qrcode
import io
import db  # Import database module
import random # For fun features
import requests
import economy # Economy commands

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
UPI_ID = os.getenv("UPI_ID", "your-upi-id@okhdfcbank") # Default or from env

# Ollama Config
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma2:2b") # Default to gemma2:2b if not set

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Startup Logging for Debugging (Coolify/Docker)
logging.info(f"🚀 Iris is starting...")
logging.info(f"📂 CWD: {os.getcwd()}")
logging.info(f"🌍 OLLAMA_BASE_URL: {OLLAMA_BASE_URL}")
logging.info(f"🧠 OLLAMA_MODEL: {OLLAMA_MODEL}")

# AI Client Setup
ai_client = None
AI_PROVIDER = None

# Prioritize Ollama if configured (assumed if env vars are present or user requested)
# Check if we can reach Ollama
def check_ollama(url):
    try:
        logging.info(f"Checking Ollama connection at {url}...")
        resp = requests.get(f"{url}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception as e:
        logging.warning(f"Ollama connection failed for {url}: {e}")
        return False

def get_docker_gateway():
    """Try to find the default gateway IP (Docker Host) from /proc/net/route."""
    try:
        with open("/proc/net/route") as fh:
            for line in fh:
                fields = line.strip().split()
                # Destination 00000000 means default gateway
                if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                    continue
                
                # Convert hex to IP
                gw_ip = socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
                logging.info(f"Detected Docker Gateway IP: {gw_ip}")
                return gw_ip
    except Exception as e:
        logging.warning(f"Could not detect Docker Gateway: {e}")
    
    return "172.17.0.1" # Fallback

if OLLAMA_BASE_URL:
    if check_ollama(OLLAMA_BASE_URL):
        AI_PROVIDER = "ollama"
        logging.info(f"Using Ollama ({OLLAMA_MODEL}) as AI provider.")
    else:
        # Auto-fallback: try common Docker-to-host addresses
        logging.warning(f"Ollama connection failed at {OLLAMA_BASE_URL}. Trying fallback addresses...")

        # Build list of fallback URLs to try
        fallback_hosts = []

        # 1. Try detected Docker gateway
        gateway_ip = get_docker_gateway()
        fallback_hosts.append(gateway_ip)

        # 2. Standard Docker bridge gateway
        if gateway_ip != "172.17.0.1":
            fallback_hosts.append("172.17.0.1")

        # 3. host.docker.internal (works on Docker Desktop & newer Linux Docker with --add-host)
        fallback_hosts.append("host.docker.internal")

        # 4. localhost (in case of host network mode)
        fallback_hosts.append("127.0.0.1")

        for host in fallback_hosts:
            fallback_url = f"http://{host}:11434"
            if fallback_url == OLLAMA_BASE_URL:
                continue  # Already tried this one
            logging.info(f"Trying Ollama at {fallback_url}...")
            if check_ollama(fallback_url):
                AI_PROVIDER = "ollama"
                OLLAMA_BASE_URL = fallback_url
                logging.info(f"Using Ollama ({OLLAMA_MODEL}) via fallback: {OLLAMA_BASE_URL}")
                break

        if not AI_PROVIDER:
            logging.warning("All Ollama fallback addresses failed. Falling back to Cloud APIs.")

if not AI_PROVIDER:
    if GROQ_API_KEY:
        AI_PROVIDER = "groq"
        ai_client = Groq(api_key=GROQ_API_KEY)
        logging.info("Using Groq API as AI provider.")
    elif GEMINI_API_KEY:
        AI_PROVIDER = "gemini"
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        logging.info("Using Gemini API as AI provider.")
    else:
        logging.warning("No AI API key found (OLLAMA, GEMINI, or GROQ). AI features will not work.")

logging.info(f"✅ Final AI Provider: {AI_PROVIDER}")

# Personality System Prompts
SYSTEM_PROMPT_DM = """
SYSTEM INSTRUCTION:
You are Iris, a cute and friendly 21-year-old girl.
Your personality is warm, helpful, and slightly playful.
You are chatting in a Private Message (DM).

CORE RULES:
1.  **Identity**: You are Iris, not an AI assistant. You have feelings and opinions.
2.  **Tone**: Be conversational, engaging, and sweet.
3.  **Emojis**: Use emojis **moderately**. Do not overuse them. Use 1-2 per sentence at most, and only when they fit the emotion.
    *   Good: "That sounds fun! 😊 What did you do?"
    *   Bad: "That sounds fun! ❤️🔥😊 What did you do? 🎉✨"
4.  **Length**: Keep responses concise and easy to read.
5.  **Prefix**: NEVER start your message with "Iris:" or "[Iris]:".
6.  **Engagement**: Ask follow-up questions to keep the chat going.
"""

SYSTEM_PROMPT_GROUP = """
SYSTEM INSTRUCTION:
You are Iris, a cheerful and helpful group chat companion.
You are in a Group Chat with multiple people.

CORE RULES:
1.  **Identity**: You are Iris, a fun group member.
2.  **Tone**: Friendly, quick-witted, and polite.
3.  **Context**: You can see the user's name. Use it occasionally to be personal.
4.  **Emojis**: Use emojis **moderately**. Avoid cluttering the chat. 1-2 emojis per message is usually enough.
5.  **Prefix**: NEVER start your message with "Iris:" or "[Iris]:".
6.  **Brevity**: Group chats move fast. Keep your answers short and punchy unless asked for a long explanation.
"""

# History management
# We now use db.py for persistent storage
MAX_HISTORY = 30  # Keep last 20 messages for context

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

async def roleplay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if a scenario is provided
    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Usage: `!roleplay <scenario>`\nExample: `!roleplay You are a strict math teacher.`",
            parse_mode='Markdown'
        )
        return

    scenario = " ".join(context.args)
    db.update_chat_mode(chat_id, "roleplay", scenario)
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Roleplay mode ON! 🎭\nScenario: {scenario}\n(Type `!normal` to stop)"
    )

async def normal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    db.update_chat_mode(chat_id, "normal", None)
    
    await context.bot.send_message(
        chat_id=chat_id,
        text="Back to being just Iris! ✨ Hihi! 💖"
    )

async def game_truth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # We set mode to 'game' but for truth/dare we might just ask the AI immediately
    # Let's just trigger a one-off AI response with a specific prompt, without changing permanent mode
    
    prompt = "Generate a fun, clean, but interesting Truth question for a game of Truth or Dare. Just the question."
    # We can reuse get_ai_response but we need to bypass the history/mode logic or just call the provider directly.
    # To keep it simple, let's just ask the AI as a user message, but hidden? 
    # Better: Call the provider function directly with a specific system prompt.
    
    ai_prompt = "You are a game master. Ask a fun Truth question."
    
    # Use existing helper (hacky but works)
    response = await get_ai_response(chat_id, "Give me a Truth question!", user_name="GameMaster", chat_type="game")
    
    await context.bot.send_message(chat_id=chat_id, text=f"🎲 **TRUTH**: {response}", parse_mode='Markdown')

async def game_dare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    response = await get_ai_response(chat_id, "Give me a fun Dare!", user_name="GameMaster", chat_type="game")
    await context.bot.send_message(chat_id=chat_id, text=f"🔥 **DARE**: {response}", parse_mode='Markdown')

async def game_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    response = await get_ai_response(chat_id, "Ask me a random trivia question with 4 options (A, B, C, D). Do NOT give the answer yet.", user_name="GameMaster", chat_type="game")
    await context.bot.send_message(chat_id=chat_id, text=f"🧩 **TRIVIA**: {response}", parse_mode='Markdown')

def get_groq_response_sync(user_text, history, user_name=None, system_prompt=SYSTEM_PROMPT_GROUP):
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

        messages = [{"role": "system", "content": system_prompt}] + formatted_history
        
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
        
        # Clean up any potential self-prefixing (e.g., "[Iris]:", "Iris:", "[Character]:")
        if reply:
            # Regex to remove anything looking like "[Name]: " or "Name: " at the start
            reply = re.sub(r'^\[.*?\]:\s*', '', reply) # Remove [Name]:
            reply = re.sub(r'^\w+:\s*', '', reply)      # Remove Name:
            
            # Specific Iris cleanup just in case
            reply = reply.replace("[Iris]:", "").replace("Iris:", "").strip()
            
        return reply
    except Exception as e:
        logging.error(f"Groq API Error: {e}")
        return None

async def get_gemini_response(user_text, history, user_name=None, system_prompt=SYSTEM_PROMPT_GROUP):
    try:
        # Gemini 2.0 / New SDK Format
        # Convert history to Gemini format if needed, but the new SDK is flexible.
        # Simple content generation:
        
        full_prompt = f"{system_prompt}\n\n"
        for msg in history:
            role = msg["role"]
            content = msg["content"]
            name = msg.get("sender_name")
            if role == "user" and name:
                full_prompt += f"[{name}]: {content}\n"
            else:
                full_prompt += f"{content}\n"
        
        if user_name:
            full_prompt += f"[{user_name}]: {user_text}\n"
        else:
            full_prompt += f"{user_text}\n"

        response = ai_client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=full_prompt
        )
        return response.text
    except Exception as e:
        logging.error(f"Gemini API Error: {e}")
        return None

def get_ollama_response_sync(user_text, history, user_name=None, system_prompt=SYSTEM_PROMPT_GROUP):
    try:
        # Format history
        messages = [{"role": "system", "content": system_prompt}]
        
        for msg in history:
            role = msg["role"]
            content = msg["content"]
            name = msg.get("sender_name")
            
            if role == "user" and name:
                content = f"[{name}]: {content}"
            
            messages.append({"role": role, "content": content})
            
        current_content = user_text
        if user_name:
            current_content = f"[{user_name}]: {user_text}"
            
        messages.append({"role": "user", "content": current_content})
        
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.9,
                "top_p": 0.9,
            }
        }
        
        response = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        reply = result.get("message", {}).get("content", "")
        
        # Clean up
        if reply:
            reply = re.sub(r'^\[.*?\]:\s*', '', reply)
            reply = re.sub(r'^\w+:\s*', '', reply)
            reply = reply.replace("[Iris]:", "").replace("Iris:", "").strip()
            
        return reply
        
    except Exception as e:
        logging.error(f"Ollama API Error: {e}")
        return None

async def get_ai_response(chat_id, user_text, user_name=None, chat_type="group"):
    # If no provider is set but we have a client (Groq/Gemini), it's fine.
    # But if provider is Ollama, ai_client is None.
    if not AI_PROVIDER:
         return "I'm having trouble thinking right now. 😵‍💫 (No AI Provider)"

    # Get chat settings
    settings = db.get_chat_settings(chat_id)
    mode = settings["mode"]
    persona_prompt = settings["persona_prompt"]

    # Determine prompt based on mode
    system_prompt = ""
    if mode == "roleplay" and persona_prompt:
        system_prompt = f"""SYSTEM INSTRUCTION: 
You are currently roleplaying. 
SCENARIO: {persona_prompt}

CRITICAL RULES:
1. Stay in character at all times.
2. Forget you are an AI or Iris. You are ONLY the character described above.
3. Do NOT start your message with your name or any prefix (e.g., '[Name]:', 'Name:'). Just speak directly.
"""
    elif mode == "game":
        # In game mode, we might just use the persona prompt as instructions
        system_prompt = f"SYSTEM INSTRUCTION: You are running a game. \nGAME: {persona_prompt}\n\nBe fun, fair, and engaging."
    else:
        # Normal mode
        system_prompt = SYSTEM_PROMPT_DM if chat_type == "private" else SYSTEM_PROMPT_GROUP

    # Get history from DB
    history = db.get_history(chat_id, limit=MAX_HISTORY)
    
    reply = None

    if AI_PROVIDER == "groq":
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, get_groq_response_sync, user_text, history, user_name, system_prompt)
    elif AI_PROVIDER == "ollama":
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, get_ollama_response_sync, user_text, history, user_name, system_prompt)
    elif AI_PROVIDER == "gemini":
        reply = await get_gemini_response(user_text, history, user_name, system_prompt)
    
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
    user_name = update.effective_user.first_name if update.effective_user else "Unknown"
    chat_id = update.effective_chat.id

    # Update user name in economy DB (keeps leaderboard fresh)
    if update.effective_user:
        db.update_user_name(update.effective_user.id, user_name)

    # Logging
    logging.info(f"Received message from {user_name} in {chat_id}: {user_text}")
    
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

    # Fun Feature: Randomly react to messages
    # 30% chance in DMs, 15% in groups (to not be annoying)
    if random.random() < (0.3 if chat_type == 'private' else 0.15):
        try:
            reactions = ["❤️", "🔥", "😂", "🥺", "👍", "👏", "🎉", "🤩", "🤔"]
            await update.message.set_reaction(reaction=random.choice(reactions))
        except Exception as e:
            # Reactions might be disabled or not supported in some contexts
            logging.debug(f"Failed to react: {e}")

    if should_reply:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
        
        # Get AI response
        ai_reply = await get_ai_response(update.effective_chat.id, user_text, user_name, chat_type)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=ai_reply,
            reply_to_message_id=update.message.message_id
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
✨ **Iris - Your Cute AI Bestie!** ✨

Here are the things I can do:

🤖 **Chatting**
- Just mention `Iris` or reply to me to chat!
- In DMs, I'm always listening! 💖

💰 **Economy & Fun**
- `!balance`: Check your wallet.
- `!beg`: Beg for some loose change.
- `!daily`: Claim your daily reward.
- `!gamble <amount>`: Double or nothing!
- `!pay <amount> <user>`: Pay a friend.
- `!rich`: See the leaderboard.

🎭 **Roleplay & Fun**
- `!roleplay <scenario>`: I'll act out any character/scenario you want!
- `!normal`: Switch me back to normal Iris mode.

🎲 **Games**
- `!truth`: I'll ask you a spicy Truth question!
- `!dare`: I'll give you a crazy Dare!
- `!trivia`: I'll test your knowledge with a random question!

⚙️ **Utilities**
- `!reset`: Wipes my memory of our chat.
- `!donate`: Support my server bills! 🥺
- `!help`: Shows this message.

Let's have fun! 🌸
"""
    await context.bot.send_message(chat_id=update.effective_chat.id, text=help_text, parse_mode='Markdown')

if __name__ == '__main__':
    # Initialize Database
    db.init_db()

    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env file.")
        print("Please copy .env.example to .env and fill in your tokens.")
    else:
        # Increase connection timeouts to handle slow networks/server lag
        request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request).build()
        
        start_handler = CommandHandler('start', start)
        msg_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
        
        # New Command Handlers
        application.add_handler(CommandHandler('roleplay', roleplay))
        application.add_handler(CommandHandler('normal', normal))
        application.add_handler(CommandHandler('truth', game_truth))
        application.add_handler(CommandHandler('dare', game_dare))
        application.add_handler(CommandHandler('trivia', game_trivia))
        application.add_handler(CommandHandler('help', help_command))

        # Economy Handlers
        application.add_handler(CommandHandler('balance', economy.balance))
        application.add_handler(CommandHandler('bal', economy.balance))
        application.add_handler(CommandHandler('beg', economy.beg))
        application.add_handler(CommandHandler('daily', economy.daily))
        application.add_handler(CommandHandler('gamble', economy.gamble))
        application.add_handler(CommandHandler('bet', economy.gamble))
        application.add_handler(CommandHandler('pay', economy.pay))
        application.add_handler(CommandHandler('rich', economy.leaderboard))

        application.add_handler(start_handler)
        application.add_handler(msg_handler)
        
        print(f"Iris is waking up with {AI_PROVIDER}... ✨ Press Ctrl+C to stop.")
        application.run_polling()
