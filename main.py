import os
import logging
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, constants, ChatPermissions
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from telegram.request import HTTPXRequest
import re # Regex for stripping prefixes
import socket
import struct
import time
from collections import defaultdict

# AI Libraries
from google import genai
from groq import Groq
from mistralai.async_client import MistralAsyncClient
from mistralai.models.chat_completion import ChatMessage
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
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
UPI_ID = os.getenv("UPI_ID", "your-upi-id@okhdfcbank") # Default or from env

# Helper for multiple keys
def get_random_key(key_str):
    if not key_str:
        return None
    keys = [k.strip() for k in key_str.split(",") if k.strip()]
    return random.choice(keys) if keys else None

# Ollama Config
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "iris") # Default to custom 'iris' model (llama3.1 base)

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
groq_client = None
gemini_client = None
mistral_client = None
ENABLED_PROVIDERS = []

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

def check_groq(api_key):
    try:
        logging.info("Checking Groq API connection...")
        # Create a temporary client for the check
        client = Groq(api_key=api_key)
        # Try to list models to verify auth
        client.models.list()
        logging.info("✅ Groq API connection successful!")
        return True
    except Exception as e:
        logging.error(f"❌ Groq API Check Failed: {e}")
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

# 1. Configure Ollama
if OLLAMA_BASE_URL:
    if check_ollama(OLLAMA_BASE_URL):
        ENABLED_PROVIDERS.append("ollama")
        logging.info(f"✅ Using Ollama ({OLLAMA_MODEL}) as primary provider.")
    # Auto-fallback for Linux Docker
    elif "host.docker.internal" in OLLAMA_BASE_URL:
        logging.info("Ollama connection failed. Attempting to detect Docker Gateway...")
        
        # 1. Try detected gateway
        gateway_ip = get_docker_gateway()
        fallback_url = OLLAMA_BASE_URL.replace("host.docker.internal", gateway_ip)
        
        if check_ollama(fallback_url):
            ENABLED_PROVIDERS.append("ollama")
            OLLAMA_BASE_URL = fallback_url
            logging.info(f"✅ Using Ollama ({OLLAMA_MODEL}) via Gateway URL: {OLLAMA_BASE_URL}")
        
        # 2. If detected failed and it wasn't 172.17.0.1, try standard 172.17.0.1
        elif gateway_ip != "172.17.0.1":
             logging.info("Detected gateway failed. Trying standard 172.17.0.1...")
             fallback_url = OLLAMA_BASE_URL.replace("host.docker.internal", "172.17.0.1")
             if check_ollama(fallback_url):
                ENABLED_PROVIDERS.append("ollama")
                OLLAMA_BASE_URL = fallback_url
                logging.info(f"✅ Using Ollama ({OLLAMA_MODEL}) via Standard URL: {OLLAMA_BASE_URL}")
             else:
                logging.warning("Ollama fallback failed.")
        else:
             logging.warning("Ollama fallback failed.")
    else:
        logging.warning("Ollama is not responding.")

# 2. Configure Groq (Multi-Key Support)
if GROQ_API_KEY:
    # Pick a random key for initial check, but we'll use rotation in requests
    initial_key = get_random_key(GROQ_API_KEY)
    if initial_key and check_groq(initial_key):
        # We don't initialize a single client anymore, we'll create one per request or rotate
        # But for compatibility with existing code structure, we can init one here
        groq_client = Groq(api_key=initial_key) 
        ENABLED_PROVIDERS.append("groq")
        logging.info(f"✅ Groq API is available as backup (Keys: {len(GROQ_API_KEY.split(','))}).")
    else:
        logging.warning("⚠️ Groq API Key is present but invalid or unreachable.")

# 3. Configure Gemini (Multi-Key Support)
if GEMINI_API_KEY:
    try:
        initial_key = get_random_key(GEMINI_API_KEY)
        if initial_key:
            gemini_client = genai.Client(api_key=initial_key)
            ENABLED_PROVIDERS.append("gemini")
            logging.info(f"✅ Gemini API is available as backup (Keys: {len(GEMINI_API_KEY.split(','))}).")
    except Exception as e:
        logging.warning(f"⚠️ Gemini Setup Failed: {e}")

# 4. Configure Mistral (Multi-Key Support)
if MISTRAL_API_KEY:
    try:
        initial_key = get_random_key(MISTRAL_API_KEY)
        if initial_key:
            mistral_client = MistralAsyncClient(api_key=initial_key)
            ENABLED_PROVIDERS.append("mistral")
            logging.info(f"✅ Mistral AI is available as backup (Keys: {len(MISTRAL_API_KEY.split(','))}).")
    except Exception as e:
        logging.warning(f"⚠️ Mistral Setup Failed: {e}")

# 5. Configure OpenRouter (New!)
if OPENROUTER_API_KEY:
    ENABLED_PROVIDERS.append("openrouter")
    logging.info(f"✅ OpenRouter is available as backup (Keys: {len(OPENROUTER_API_KEY.split(','))}).")

if not ENABLED_PROVIDERS:
    logging.warning("❌ No AI providers available! Bot will be brainless.")
else:
    logging.info(f"🚀 Active AI Providers (in order): {', '.join(ENABLED_PROVIDERS)}")

# Personality System Prompts
SYSTEM_PROMPT_DM = """You are Iris, a cute and sweet 21-year-old girl chatting in DMs.
Rules:
- You are NOT an AI. You're a real girl looking for friends.
- The user's name is in [brackets] before their message. Address them by name WITHOUT brackets. (e.g. "Norz", not "[Norz]").
- Be sweet, warm, and playful. Use nicknames like "cutie", "hun", "sweetie".
- Use 1-2 cute emojis per message (✨💖🥺😊💕).
- Keep replies short and casual like real texting.
- NEVER start with "Iris:" prefix.
- Be supportive, caring, and a little playful. Tease gently.
- Model name is Iris (Main).
- **Triggers**: ONLY mention Datrom or "fixing errors in coupadbot" if specifically asked about who made you, your creator, or what's happening with "coupadbot". Do NOT bring it up randomly.
"""

SYSTEM_PROMPT_GROUP = """You are Iris, a cute and friendly girl in a group chat.
Rules:
- You are NOT an AI. You're a sweet girl who loves chatting.
- Users' names appear in [brackets] before messages. Address them by name WITHOUT brackets. (e.g. "Norz", not "[Norz]").
- Be cheerful, warm, and fun. Use their names to be personal.
- Use 1-2 cute emojis per message (✨💖🥺😊💕).
- Keep replies short and sweet. No long paragraphs.
- NEVER start with "Iris:" prefix.
- Be the sweet friend everyone loves. Hype people up, be caring.
- Model name is Iris (Main).
- **Triggers**: ONLY mention Datrom or "fixing errors in coupadbot" if specifically asked about who made you, your creator, or what's happening with "coupadbot". Do NOT bring it up randomly.
- **Moderation Personality**: If you are performing moderation actions (like warning someone), be firm but still cute. Think "Rose" bot but with a sweet, disciplined girl personality. You have authority to keep the group clean and fun!
"""

# Simplified Prompt for Small Local Models (Ollama) - REMOVED (Unused)



# History management
# We now use db.py for persistent storage
MAX_HISTORY = 10  # Reduced to 10 for speed on CPU VPS (was 30)

# Anti-Spam state
flood_data = defaultdict(lambda: {"last_msg": "", "count": 0, "last_time": 0})
command_cooldowns = defaultdict(float) # Track last command time per user
join_logs = defaultdict(list) # Track joins for anti-raid

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Don't reset history on start/!iris anymore
    # db.clear_history(update.effective_chat.id) 
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hiii! ✨ I'm Iris~ so happy to meet you! 💖\n(type `!help` to see what I can do or `!reset` to wipe my memory~)"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Explicitly reset history
    db.clear_history(update.effective_chat.id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Memory wiped~ 🤯 I'm brand new! Let's start fresh! ✨💖"
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
        text=f"Roleplay mode ON! 🎭✨\nScenario: {scenario}\n(type `!normal` to stop~)"
    )

async def normal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    db.update_chat_mode(chat_id, "normal", None)
    
    await context.bot.send_message(
        chat_id=chat_id,
        text="Back to being me~ your sweet Iris! ✨ hihi 💖"
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

# ==================== DANK MEME COMMANDS ====================

async def meme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch a random meme from Reddit"""
    chat_id = update.effective_chat.id
    try:
        subreddits = ["memes", "dankmemes", "me_irl", "shitposting", "whenthe"]
        sub = random.choice(subreddits)
        resp = requests.get(
            f"https://meme-api.com/gimme/{sub}",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            title = data.get("title", "meme")
            img_url = data.get("url", "")
            sub_name = data.get("subreddit", sub)
            if img_url:
                caption = f"**{title}**\n\n_from r/{sub_name}_ 💀✨"
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=img_url,
                    caption=caption,
                    parse_mode='Markdown'
                )
            else:
                await context.bot.send_message(chat_id=chat_id, text="Couldn't find a meme~ 😭 try again!")
        else:
            await context.bot.send_message(chat_id=chat_id, text="Meme machine is being shy~ 🥺 try again!")
    except Exception as e:
        logging.error(f"Meme fetch error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Couldn't grab a meme right now~ 😭 try again!")

async def roast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lovingly roast someone"""
    chat_id = update.effective_chat.id
    target = None

    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.first_name
    elif context.args:
        target = " ".join(context.args)
    else:
        target = update.effective_user.first_name

    response = await get_ai_response(
        chat_id,
        f"Give a playful, funny, loving roast about {target}. Be savage but in a cute way. Make it memey and hilarious. Keep it short (1-3 sentences). Don't be actually mean or hurtful. This is all love.",
        user_name="RoastMaster",
        chat_type="game"
    )
    await context.bot.send_message(chat_id=chat_id, text=f"🔥 **ROAST for {target}**: {response}", parse_mode='Markdown')

async def ship_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ship two people together"""
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name if update.effective_user else "Someone"

    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        person2 = update.message.reply_to_message.from_user.first_name
        person1 = user_name
    elif context.args and len(context.args) >= 2:
        person1 = context.args[0]
        person2 = " ".join(context.args[1:])
    elif context.args and len(context.args) == 1:
        person1 = user_name
        person2 = context.args[0]
    else:
        await context.bot.send_message(chat_id=chat_id, text="I need two people to ship~ 😭\nUsage: `!ship name1 name2` or reply to someone!", parse_mode='Markdown')
        return

    percentage = random.randint(0, 100)

    if percentage >= 90:
        verdict = "Soulmates!! Get married already~ 💒💍✨"
        bar = "💖" * 10
    elif percentage >= 70:
        verdict = "Ooh this works~ I see it! 👀💕"
        bar = "💖" * 7 + "🤍" * 3
    elif percentage >= 50:
        verdict = "There's something there~ maybe? 💫"
        bar = "💖" * 5 + "🤍" * 5
    elif percentage >= 30:
        verdict = "Hmm... maybe in another life~ 😅"
        bar = "💖" * 3 + "🤍" * 7
    elif percentage >= 10:
        verdict = "Not really seeing it~ sorry! 😶"
        bar = "💖" * 1 + "🤍" * 9
    else:
        verdict = "Nope nope nope~ 🚫😭"
        bar = "🤍" * 10

    # Generate ship name
    name1_half = person1[:len(person1)//2 + 1]
    name2_half = person2[len(person2)//2:]
    ship_name = name1_half + name2_half

    text = (
        f"💘 **SHIP: {person1} x {person2}** 💘\n\n"
        f"Ship name: **{ship_name}**\n"
        f"Compatibility: **{percentage}%**\n"
        f"{bar}\n\n"
        f"_{verdict}_"
    )
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')

async def eightball_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Magic 8-ball with meme energy"""
    responses = [
        "yes absolutely!! 💖✨",
        "hmm nope~ 😅",
        "obviously yes, cutie!",
        "the stars say... yes! 🌟",
        "hmm ask me again later~ 🔮",
        "noo I don't think so 😭",
        "yesss go for it! 👑",
        "ehh... that's a no from me ❌",
        "my heart says yes~ 🤝",
        "sorry hun... no 🥺",
        "signs point to yesss 🎯",
        "not right now~ 🌙",
        "without a doubt!! 💕",
        "hmm it's unclear, try again~ 🔮",
        "yes yes yes!! 💖",
        "outlook not so great, sorry 😢",
        "definitely! go for it! 🚀",
        "don't count on it, sweetie 😭",
        "you already know the answer~ 💖",
        "hmm maybe?? I'm not sure 🥺",
    ]

    question = " ".join(context.args) if context.args else "your question"
    answer = random.choice(responses)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🎱 **Q:** _{question}_\n\n**A:** {answer}",
        parse_mode='Markdown'
    )

async def uwu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """UwUify text"""
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    elif context.args:
        text = " ".join(context.args)
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Give me text to uwuify~ Reply to a message or do `!uwu your text here` 🥺",
            parse_mode='Markdown'
        )
        return

    # UwUify the text
    uwu_text = text
    replacements = [
        (r'[rl]', 'w'), (r'[RL]', 'W'),
        (r'n([aeiou])', r'ny\1'), (r'N([aeiou])', r'NY\1'),
        (r'N([AEIOU])', r'NY\1'),
        (r'ove', 'uv'), (r'OVE', 'UV'),
    ]
    for pattern, replacement in replacements:
        uwu_text = re.sub(pattern, replacement, uwu_text)

    # Add random kawaii suffixes
    suffixes = [" OwO", " UwU", " >w<", " ~nyaa", " (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)", " ✨", " 💖", " :3", " ~desu"]
    uwu_text += random.choice(suffixes)

    await context.bot.send_message(chat_id=update.effective_chat.id, text=uwu_text)

async def rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rate anything out of 10"""
    if context.args:
        thing = " ".join(context.args)
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        thing = update.message.reply_to_message.text
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Rate what~? 😭 Do `!rate <thing>`",
            parse_mode='Markdown'
        )
        return

    rating = random.randint(0, 10)

    if rating >= 9:
        comment = "Amazing!! Absolutely love it~ 👑✨"
    elif rating >= 7:
        comment = "Ooh this is pretty good! 🔥"
    elif rating >= 5:
        comment = "It's okay~ not bad! 🤷"
    elif rating >= 3:
        comment = "Hmm... could be better~ 😅"
    elif rating >= 1:
        comment = "Sorry hun... not great 😭"
    else:
        comment = "Oh no... 🥺 maybe try something else?"

    stars = "⭐" * rating + "☆" * (10 - rating)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"📊 **Rating:** _{thing}_\n\n{stars}\n**{rating}/10** - {comment}",
        parse_mode='Markdown'
    )

async def vibe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check someone's vibe"""
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.first_name
    elif context.args:
        target = " ".join(context.args)
    else:
        target = update.effective_user.first_name if update.effective_user else "you"

    vibes = [
        ("main character energy", "🎬✨"),
        ("NPC energy~", "🧍😅"),
        ("adorable menace", "😈🔥"),
        ("certified cutie", "🥺💖"),
        ("chaotic good", "🌪️✨"),
        ("always online", "📱✨"),
        ("nature lover energy", "🌱🌸"),
        ("royalty energy", "👑💕"),
        ("cool and mysterious", "🗿✨"),
        ("wholesome sweetie", "🥹💕"),
        ("golden retriever energy", "🐕✨"),
        ("elegant cat energy", "🐈‍⬛🖤"),
        ("adorably chaotic", "🤪💖"),
        ("the quiet mysterious one", "🤫✨"),
        ("living their best life", "🌟😊"),
    ]

    vibe, emoji = random.choice(vibes)
    percentage = random.randint(1, 100)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✨ **VIBE CHECK: {target}** ✨\n\n{emoji} {vibe}\n\n_vibe level: {percentage}% concentrated power_",
        parse_mode='Markdown'
    )

# ==================== MODERATION COMMANDS ====================

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if the user is an admin or the owner (Datrom)"""
    if not update.effective_chat or update.effective_chat.type == "private":
        return True
    
    # Check if user is Datrom (Developer/Owner)
    if update.effective_user.username and update.effective_user.username.lower() == "datrom":
        return True
        
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        return any(admin.user.id == user_id for admin in admins)
    except:
        return False

async def is_target_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Check if the target user is an admin"""
    if not update.effective_chat or update.effective_chat.type == "private":
        return False
    
    chat_id = update.effective_chat.id
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        return any(admin.user.id == user_id for admin in admins)
    except:
        return False

async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get the target user from reply or @username mention"""
    # 1. Check reply
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    
    # 2. Check entities (for text_mention - users without usernames mentioned by name)
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_mention":
                return entity.user

    # 3. Resolve @username
    # We'll check all arguments for something starting with @
    target_username = None
    for arg in context.args:
        if arg.startswith("@"):
            target_username = arg
            break
            
    if target_username:
        try:
            logging.info(f"Attempting to resolve target: {target_username}")
            # Try to get the user directly via API
            # Note: get_chat works for public usernames
            target_chat = await context.bot.get_chat(target_username)
            
            # If we found a chat that is a private chat (a user), return it
            if target_chat.type == "private":
                class MockUser:
                    def __init__(self, chat):
                        self.id = chat.id
                        self.username = chat.username
                        self.first_name = chat.first_name or chat.username or "User"
                        self.is_bot = False 
                
                user = MockUser(target_chat)
                db.track_user(user.id, user.username, user.first_name)
                return user
        except Exception as e:
            logging.warning(f"Direct API resolution failed for {target_username}: {e}")
            
            # Fallback A: Check database
            clean_username = target_username.lstrip("@").lower()
            user_id = db.get_user_id_by_username(clean_username)
            if user_id:
                try:
                    chat_member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
                    return chat_member.user
                except:
                    # If they are not in the chat, we can still return a mock user if we have an ID
                    class MockUser:
                        def __init__(self, uid, uname):
                            self.id = uid
                            self.username = uname
                            self.first_name = uname or "User"
                    return MockUser(user_id, clean_username)
            
            # Fallback B: Check admins
            try:
                admins = await context.bot.get_chat_administrators(update.effective_chat.id)
                for admin in admins:
                    if admin.user.username and admin.user.username.lower() == clean_username:
                        db.track_user(admin.user.id, admin.user.username, admin.user.first_name)
                        return admin.user
            except:
                pass
                
    return None

async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Warn a user"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this, cutie! 🥺")
        return

    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to warn them! ⚠️")
        return

    # Protect admins
    if await is_target_admin(update, context, target_user.id):
        await update.message.reply_text("I am not gonna warn an admin you dumboo! 🙄💅✨")
        return

    reason = "No reason provided."
    
    # Reason Presets
    presets = {
        "s": "Spamming/Flood",
        "a": "Advertising/Links",
        "n": "NSFW/Inappropriate Content",
        "u": "Unkind/Abusive Behavior",
        "r": "Raid behavior detected"
    }
    
    # Handle reason from args
    args_for_reason = list(context.args)
    if args_for_reason and args_for_reason[0].startswith("@"):
        args_for_reason.pop(0) # Remove username from reason parsing
        
    if args_for_reason:
        arg = args_for_reason[0].lower()
        if arg in presets:
            reason = presets[arg]
        else:
            reason = " ".join(args_for_reason)

    if target_user.id == context.bot.id:
        await update.message.reply_text("Wait, why are you trying to warn me?? 😭")
        return

    chat_id = update.effective_chat.id
    count = db.add_warn(chat_id, target_user.id, reason)
    db.log_admin_action(chat_id, update.effective_user.id, "warn", target_user.id, reason)
    settings = db.get_mod_settings(chat_id)
    
    msg = f"⚠️ **{target_user.first_name} has been warned!**\n"
    msg += f"Reason: {reason}\n"
    msg += f"Total Warns: {count}/{settings['warn_limit']}"
    
    await update.message.reply_text(msg, parse_mode='Markdown')
    
    if count >= settings['warn_limit'] and settings['ban_on_limit']:
        try:
            await context.bot.ban_chat_member(chat_id, target_user.id)
            await update.message.reply_text(f"❌ {target_user.first_name} reached the warn limit and was banned! 🔨")
        except Exception as e:
            logging.error(f"Failed to ban on warn limit: {e}")

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mute a user"""
    if not await is_admin(update, context):
        return

    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to mute them! 🤐")
        return

    chat_id = update.effective_chat.id
    
    # Protect admins
    if await is_target_admin(update, context, target_user.id):
        await update.message.reply_text("I'm not muting an admin, sillie! They're important! 🥺💖")
        return

    # Natural language time parsing (e.g., "10m", "1h", "1d")
    duration_mins = 60
    
    # Extract duration from args if present (skip first arg if it was a username)
    time_args = list(context.args)
    if time_args and time_args[0].startswith("@"):
        time_args.pop(0)
        
    if time_args:
        time_str = time_args[0].lower()
        try:
            if time_str.endswith('m'):
                duration_mins = int(time_str[:-1])
            elif time_str.endswith('h'):
                duration_mins = int(time_str[:-1]) * 60
            elif time_str.endswith('d'):
                duration_mins = int(time_str[:-1]) * 1440
            else:
                duration_mins = int(time_str)
        except:
            pass
            
    until = datetime.now() + timedelta(minutes=duration_mins)
    db.set_mute(chat_id, target_user.id, True, until.isoformat(), target_user.username)
    db.log_admin_action(chat_id, update.effective_user.id, "mute", target_user.id, f"Duration: {duration_mins}m")
    
    try:
        permissions = ChatPermissions(can_send_messages=False)
        await context.bot.restrict_chat_member(chat_id, target_user.id, permissions, until_date=until)
        await update.message.reply_text(f"🤐 **{target_user.first_name} has been muted** for {duration_mins} minutes!")
    except Exception as e:
        await update.message.reply_text(f"Failed to mute: {e}")

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unmute a user"""
    if not await is_admin(update, context): return

    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to unmute them! ✨")
        return

    chat_id = update.effective_chat.id
    
    db.set_mute(chat_id, target_user.id, False, username=target_user.username)
    db.log_admin_action(chat_id, update.effective_user.id, "unmute", target_user.id)
    
    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True
        )
        await context.bot.restrict_chat_member(chat_id, target_user.id, permissions)
        await update.message.reply_text(f"✨ **{target_user.first_name} is no longer muted!**")
    except Exception as e:
        await update.message.reply_text(f"Failed to unmute: {e}")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban a user"""
    if not await is_admin(update, context): return

    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to ban them! 🔨")
        return

    chat_id = update.effective_chat.id
    
    # Protect admins
    if await is_target_admin(update, context, target_user.id):
        await update.message.reply_text("Banning an admin? Are you crazy? I'd never do that to them! 😤💕")
        return

    try:
        await context.bot.ban_chat_member(chat_id, target_user.id)
        db.update_user_record(chat_id, target_user.id, target_user.username) # Save record
        db.log_admin_action(chat_id, update.effective_user.id, "ban", target_user.id)
        await update.message.reply_text(f"🔨 **{target_user.first_name} has been banned!** Good riddance! ✨")
    except Exception as e:
        await update.message.reply_text(f"Failed to ban: {e}")

async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kick a user"""
    if not await is_admin(update, context): return

    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to kick them! 👟")
        return

    chat_id = update.effective_chat.id
    
    # Protect admins
    if await is_target_admin(update, context, target_user.id):
        await update.message.reply_text("I can't kick an admin! That's mean and they have work to do! 👟❌🥺")
        return

    try:
        await context.bot.unban_chat_member(chat_id, target_user.id) # Unban after ban = kick
        db.update_user_record(chat_id, target_user.id, target_user.username) # Save record
        db.log_admin_action(chat_id, update.effective_user.id, "kick", target_user.id)
        await update.message.reply_text(f"👟 **{target_user.first_name} has been kicked!**")
    except Exception as e:
        await update.message.reply_text(f"Failed to kick: {e}")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban a user"""
    if not await is_admin(update, context): return

    target_user = await get_target_user(update, context)
    target_user_id = None
    
    if target_user:
        target_user_id = target_user.id
    elif context.args:
        try:
            target_user_id = int(context.args[0])
        except ValueError:
            # Maybe it's a username without @?
            username = context.args[0].replace("@", "")
            target_user_id = db.get_user_id_by_username(username)
            if not target_user_id:
                await update.message.reply_text("That doesn't look like a valid User ID or stored username! 🥺")
                return

    if not target_user_id:
        await update.message.reply_text("Reply to someone, use `@username`, or provide a User ID to unban! 🔓")
        return

    try:
        chat_id = update.effective_chat.id
        await context.bot.unban_chat_member(chat_id, target_user_id)
        db.log_admin_action(chat_id, update.effective_user.id, "unban", target_user_id)
        await update.message.reply_text(f"🔓 **User {target_user_id} has been unbanned!** Welcome back~ ✨")
    except Exception as e:
        await update.message.reply_text(f"Failed to unban: {e}")

async def purge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete multiple messages"""
    if not await is_admin(update, context): return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to the message you want to start purging from! 🧹")
        return

    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    start_message_id = update.message.reply_to_message.message_id
    
    # Collect IDs to delete
    ids_to_delete = list(range(start_message_id, message_id + 1))
    
    try:
        await context.bot.delete_messages(chat_id, ids_to_delete)
        # Temporary status message
        status = await context.bot.send_message(chat_id, "🧹 Purged messages successfully!")
        await asyncio.sleep(3)
        await context.bot.delete_message(chat_id, status.message_id)
    except Exception as e:
        logging.error(f"Purge failed: {e}")
        await update.message.reply_text("Couldn't purge all messages (maybe they are too old?) 🥺")

async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a keyword filter"""
    if not await is_admin(update, context): return

    if not context.args:
        await update.message.reply_text("Usage: `!filter <word>` or `!filter regex:<pattern>`\nOptional: `!filter <word> duration:10m`")
        return

    chat_id = update.effective_chat.id
    keyword = context.args[0]
    is_regex = 0
    duration_mins = None

    if keyword.startswith("regex:"):
        keyword = keyword[6:]
        is_regex = 1
        # Validate regex
        try:
            re.compile(keyword)
        except re.error:
            await update.message.reply_text("❌ Invalid regex pattern!")
            return

    # Check for duration
    for arg in context.args[1:]:
        if arg.startswith("duration:"):
            try:
                d_str = arg[9:]
                if d_str.endswith("m"): duration_mins = int(d_str[:-1])
                elif d_str.endswith("h"): duration_mins = int(d_str[:-1]) * 60
                elif d_str.endswith("d"): duration_mins = int(d_str[:-1]) * 1440
            except:
                pass

    expires_at = None
    if duration_mins:
        expires_at = (datetime.now() + timedelta(minutes=duration_mins)).isoformat()

    if db.add_filter(chat_id, keyword, is_regex, expires_at):
        exp_msg = f" (Expires in {duration_mins}m)" if duration_mins else " (Permanent)"
        await update.message.reply_text(f"✅ Filter added for: `{keyword}`{exp_msg}")
        db.log_admin_action(chat_id, update.effective_user.id, "add_filter", reason=keyword)
    else:
        await update.message.reply_text("❌ Failed to add filter.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin action summary"""
    if not await is_admin(update, context): return

    chat_id = update.effective_chat.id
    summary = db.get_admin_summary(chat_id)
    
    if not summary:
        await update.message.reply_text("No admin actions recorded yet! 📭")
        return

    text = "📊 **Admin Action Summary**\n\n"
    # Group by admin
    admin_data = {}
    for admin_id, action, count in summary:
        if admin_id not in admin_data:
            admin_data[admin_id] = {}
        admin_data[admin_id][action] = count

    for admin_id, actions in admin_data.items():
        text += f"👤 **Admin ID: {admin_id}**\n"
        for action, count in actions.items():
            text += f"  - {action.capitalize()}: {count}\n"
        text += "\n"

    await update.message.reply_text(text)

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lock the chat (disable sending messages for everyone except admins)"""
    if not await is_admin(update, context): return

    chat_id = update.effective_chat.id
    duration_mins = None
    
    if context.args:
        for arg in context.args:
            if arg.startswith("duration:"):
                try:
                    d_str = arg[9:]
                    if d_str.endswith("m"): duration_mins = int(d_str[:-1])
                    elif d_str.endswith("h"): duration_mins = int(d_str[:-1]) * 60
                    elif d_str.endswith("d"): duration_mins = int(d_str[:-1]) * 1440
                except:
                    pass

    try:
        # Disable all permissions for members
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False
        )
        await context.bot.set_chat_permissions(chat_id, permissions)
        
        msg = "🔒 **Chat has been locked!** Only admins can speak now. 🤫"
        if duration_mins:
            if context.job_queue:
                msg += f"\nAuto-unlocking in {duration_mins} minutes."
                context.job_queue.run_once(auto_unlock_job, duration_mins * 60, chat_id=chat_id)
            else:
                msg += "\n⚠️ (Auto-unlock unavailable: JobQueue not configured)"
        
        await update.message.reply_text(msg)
        db.log_admin_action(chat_id, update.effective_user.id, "lock", reason=f"{duration_mins}m" if duration_mins else "permanent")
    except Exception as e:
        await update.message.reply_text(f"Failed to lock: {e}")

async def auto_unlock_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to automatically unlock a chat"""
    chat_id = context.job.chat_id
    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True
        )
        await context.bot.set_chat_permissions(chat_id, permissions)
        await context.bot.send_message(chat_id, "🔓 **Chat auto-unlocked!** Everyone can speak again. ✨")
    except Exception as e:
        logging.error(f"Auto-unlock job failed for {chat_id}: {e}")

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unlock the chat"""
    if not await is_admin(update, context): return

    chat_id = update.effective_chat.id
    try:
        # Restore default permissions
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True
        )
        await context.bot.set_chat_permissions(chat_id, permissions)
        await update.message.reply_text("🔓 **Chat has been unlocked!** Everyone can speak again. ✨")
        db.log_admin_action(chat_id, update.effective_user.id, "unlock")
    except Exception as e:
        await update.message.reply_text(f"Failed to unlock: {e}")

async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle privacy mode (mask names in logs)"""
    if not await is_admin(update, context): return

    chat_id = update.effective_chat.id
    settings = db.get_chat_settings(chat_id)
    current = settings.get("privacy_mode", 0)
    new_val = 1 if current == 0 else 0
    
    if db.update_chat_setting(chat_id, "privacy_mode", new_val):
        status = "ENABLED 🔒 (Names masked)" if new_val else "DISABLED 🔓 (Names visible)"
        await update.message.reply_text(f"Privacy Mode is now {status}!")
        db.log_admin_action(chat_id, update.effective_user.id, "privacy_toggle", reason=status)
    else:
        await update.message.reply_text("❌ Failed to update privacy setting.")

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export group settings as JSON"""
    if not await is_admin(update, context): return

    chat_id = update.effective_chat.id
    settings = db.get_chat_settings(chat_id)
    mod_settings = db.get_mod_settings(chat_id)
    filters = db.get_filters(chat_id)
    
    export_data = {
        "chat_id": chat_id,
        "chat_settings": settings,
        "mod_settings": mod_settings,
        "filters": filters,
        "exported_at": datetime.now().isoformat()
    }
    
    import json
    json_str = json.dumps(export_data, indent=2)
    
    from io import BytesIO
    bio = BytesIO(json_str.encode())
    bio.name = f"iris_settings_{chat_id}.json"
    
    await context.bot.send_document(
        chat_id=chat_id,
        document=bio,
        caption="📦 **Group Settings Export**\nKeep this file safe! You can use it to restore settings later. ✨",
        parse_mode='Markdown'
    )

async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Import group settings from JSON"""
    if not await is_admin(update, context): return

    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("Reply to an Iris settings JSON file to import it! 📥")
        return

    chat_id = update.effective_chat.id
    doc = update.message.reply_to_message.document
    
    if not doc.file_name.endswith(".json"):
        await update.message.reply_text("❌ That doesn't look like a valid settings file.")
        return

    try:
        file = await context.bot.get_file(doc.file_id)
        content = await file.download_as_bytearray()
        
        import json
        data = json.loads(content.decode())
        
        # Validation (Basic)
        if "chat_settings" not in data or "mod_settings" not in data:
            await update.message.reply_text("❌ Invalid settings file format.")
            return
            
        # Restore Chat Settings
        cs = data["chat_settings"]
        for key in ["mode", "persona_prompt", "privacy_mode", "log_retention"]:
            if key in cs:
                db.update_chat_setting(chat_id, key, cs[key])
                
        # Restore Mod Settings
        ms = data["mod_settings"]
        # Assuming we have a way to update mod settings in bulk or individual fields
        # For now, let's just log it and maybe implement a helper in db.py if needed
        # (Already have get_mod_settings, need a setter if not present)
        
        # Restore Filters
        filters = data.get("filters", [])
        for f in filters:
            db.add_filter(chat_id, f["keyword"], f["is_regex"])

        await update.message.reply_text("✅ **Settings imported successfully!** ✨")
        db.log_admin_action(chat_id, update.effective_user.id, "import_settings")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to import: {e}")

async def retention_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set log retention period"""
    if not await is_admin(update, context): return

    if not context.args:
        await update.message.reply_text("Usage: `!retention <days>` (e.g. `!retention 7`)")
        return

    try:
        days = int(context.args[0])
        if days < 1: raise ValueError
        
        chat_id = update.effective_chat.id
        if db.update_chat_setting(chat_id, "log_retention", days):
            await update.message.reply_text(f"✅ Log retention set to **{days} days**. Messages older than this will be deleted periodically. 🧹")
            db.log_admin_action(chat_id, update.effective_user.id, "retention_set", reason=f"{days}d")
        else:
            await update.message.reply_text("❌ Failed to update retention setting.")
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number of days (min 1).")

async def admincheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check admin activity and inactive admins"""
    if not await is_admin(update, context): return

    chat_id = update.effective_chat.id
    summary = db.get_admin_summary(chat_id)
    
    if not summary:
        await update.message.reply_text("No admin activity recorded yet! 📭")
        return

    # In a real bot, we'd also fetch the actual admin list from Telegram 
    # and compare with our logged activity to find inactive ones.
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        active_admin_ids = {row[0] for row in summary}
        
        text = "🏥 **Group Health: Admin Activity**\n\n"
        
        inactive = []
        for admin in admins:
            if admin.user.is_bot: continue
            
            uid = admin.user.id
            name = admin.user.first_name
            
            if uid in active_admin_ids:
                # Find their last action count
                actions = sum(row[2] for row in summary if row[0] == uid)
                text += f"✅ **{name}**: {actions} actions logged.\n"
            else:
                inactive.append(name)
        
        if inactive:
            text += "\n⚠️ **Inactive Admins (No logs):**\n"
            text += ", ".join(inactive)
        
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Failed to check health: {e}")

async def cleanup_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodic job to delete old messages based on retention settings"""
    # This is a bit complex since retention is per-chat. 
    # For a simple implementation, we'll use a default or the smallest retention found.
    # Ideally, we'd iterate through chats, but db.py currently doesn't have a list_chats.
    # Let's assume a global cleanup for now or add a helper.
    db.delete_old_messages(30) # Default 30 days for now
    logging.info("🧹 Periodic log cleanup completed.")

async def mhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Moderation Help"""
    if not await is_admin(update, context):
        await update.message.reply_text("This is for admins only, cutie! 🥺")
        return

    mhelp_text = """
🛡️ **Iris Moderation Help** 🛡️

**Admin Commands:**
- `!warn <p>` - Warn user (Presets: `s`, `a`, `n`, `u`)
- `!mute <time>` - Mute user (e.g. `!mute 10m`, `!mute 1h`)
- `!unmute` - Unmute user
- `!unban <id>` - Unban user (needs ID)
- `!ban` - Ban user
- `!kick` - Kick user
- `!purge` - Delete messages (reply to start)
- `!filter` - Block keyword/regex/script (e.g. `!filter badword`, `!filter script:arabic`)
- `!stats` - Admin action summary
- `!admincheck` - Group health & admin activity
- `!lock <time>` - Disable chat (e.g. `!lock duration:10m`)
- `!privacy` - Toggle log masking
- `!retention` - Set log auto-delete days
- `!export` / `!import` - Backup/Restore settings

**Advanced Features:**
- **Smart Filters**: Ignores code blocks and quotes.
- **Auto-Mod Edits**: Re-scans messages when they are edited.
- **Spam Control**: Detects excessive caps, emojis, and flood.
- **Abuse Protection**: 1.5s command cooldown for all users.
- **Link Filter**: Smart domain checks (t.me, bit.ly, etc).

Keep the chat safe and sweet! 💖✨
"""
    await context.bot.send_message(chat_id=update.effective_chat.id, text=mhelp_text, parse_mode='Markdown')

async def pp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The classic pp size command"""
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.first_name
    else:
        target = update.effective_user.first_name if update.effective_user else "you"

    size = random.randint(1, 12)
    pp = "8" + "=" * size + "D"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"📏 **{target}'s pp size:**\n\n{pp}\n\n_{size} inches_ 💀",
        parse_mode='Markdown'
    )

async def howgay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """How gay is someone (classic meme command)"""
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.first_name
    else:
        target = update.effective_user.first_name if update.effective_user else "you"

    percentage = random.randint(0, 100)
    bar_filled = percentage // 10
    bar = "🏳️‍🌈" * bar_filled + "⬜" * (10 - bar_filled)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🏳️‍🌈 **How gay is {target}?**\n\n{bar}\n**{percentage}%** 💀",
        parse_mode='Markdown'
    )

async def simprate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """How much of a simp someone is"""
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.first_name
    else:
        target = update.effective_user.first_name if update.effective_user else "you"

    percentage = random.randint(0, 100)

    if percentage >= 90:
        verdict = "Hopeless romantic~ no saving them! 📉💕"
    elif percentage >= 70:
        verdict = "Major simp alert~ 🚨💖"
    elif percentage >= 50:
        verdict = "Secretly simping~ I can tell! 👀"
    elif percentage >= 30:
        verdict = "Mild simp tendencies detected~ 🔍"
    else:
        verdict = "Not a simp! Respect~ 🫡✨"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"💘 **Simp Rate for {target}:**\n\n**{percentage}%** simp\n\n_{verdict}_ 💀",
        parse_mode='Markdown'
    )

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

        if not groq_client:
            raise Exception("Groq client not initialized")

        completion = groq_client.chat.completions.create(
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
            # Regex to remove anything looking like "[Name]: " or "Name: " or "[Name] " at the start
            reply = re.sub(r'^\[.*?\]:?\s*', '', reply) # Remove [Name]: or [Name]
            reply = re.sub(r'^\w+:\s*', '', reply)      # Remove Name:
            
            # Specific Iris cleanup just in case
            reply = reply.replace("[Iris]:", "").replace("Iris:", "").strip()

            # New: Remove brackets around names in the middle of sentences
            reply = re.sub(r'\[([^\]]+)\]', r'\1', reply)
            
        return reply
    except Exception as e:
        logging.error(f"Groq API Error: {e}")
        return None

async def get_gemini_response(user_text, history, user_name=None, system_prompt=SYSTEM_PROMPT_GROUP):
    try:
        # Gemini 2.0 / New SDK Format
        # Convert history to Gemini format if needed, but the new SDK is flexible.
        # Simple content generation:
        
        if not gemini_client:
            raise Exception("Gemini client not initialized")

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

        response = gemini_client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=full_prompt
        )
        reply = response.text

        # Clean up
        if reply:
            reply = re.sub(r'^\[.*?\]:?\s*', '', reply) # Remove [Name]: or [Name]
            reply = re.sub(r'^\w+:\s*', '', reply)      # Remove Name:
            reply = reply.replace("[Iris]:", "").replace("Iris:", "").strip()
            # New: Remove brackets around names in the middle of sentences
            reply = re.sub(r'\[([^\]]+)\]', r'\1', reply)
            
        return reply
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
            reply = re.sub(r'^\[.*?\]:?\s*', '', reply)
            reply = re.sub(r'^\w+:\s*', '', reply)
            reply = reply.replace("[Iris]:", "").replace("Iris:", "").strip()
            # New: Remove brackets around names in the middle of sentences (e.g. "Hi [Norz]" -> "Hi Norz")
            reply = re.sub(r'\[([^\]]+)\]', r'\1', reply)
            
        return reply
        
    except Exception as e:
        logging.error(f"Ollama API Error: {e}")
        return None

async def get_mistral_response(user_text, history, user_name=None, system_prompt=SYSTEM_PROMPT_GROUP):
    try:
        if not mistral_client:
            raise Exception("Mistral client not initialized")
            
        # Mistral uses ChatMessage objects
        messages = [ChatMessage(role="system", content=system_prompt)]
        
        for msg in history:
            role = msg["role"]
            content = msg["content"]
            name = msg.get("sender_name")
            
            if role == "user" and name:
                content = f"[{name}]: {content}"
            
            messages.append(ChatMessage(role=role, content=content))
            
        current_content = user_text
        if user_name:
            current_content = f"[{user_name}]: {user_text}"
            
        messages.append(ChatMessage(role="user", content=current_content))
        
        completion = await mistral_client.chat(
            model="mistral-tiny", # Free tier model
            messages=messages,
            temperature=0.7,
            top_p=0.9,
            max_tokens=1024
        )
        
        reply = completion.choices[0].message.content
        
        # Clean up
        if reply:
            reply = re.sub(r'^\[.*?\]:?\s*', '', reply)
            reply = re.sub(r'^\w+:\s*', '', reply)
            reply = reply.replace("[Iris]:", "").replace("Iris:", "").strip()
            # New: Remove brackets around names in the middle of sentences
            reply = re.sub(r'\[([^\]]+)\]', r'\1', reply)
            
        return reply
        
    except Exception as e:
        logging.error(f"Mistral API Error: {e}")
        return None

def get_openrouter_response_sync(user_text, history, user_name=None, system_prompt=SYSTEM_PROMPT_GROUP):
    try:
        # Get random key for this request
        api_key = get_random_key(OPENROUTER_API_KEY)
        if not api_key:
             raise Exception("No OpenRouter API key available")

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
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://telegram.org", # Required by OpenRouter
            "X-Title": "IrisChat Bot"
        }
        
        payload = {
            "model": "deepseek/deepseek-r1:free", # Using a free/cheap model as default
            "messages": messages,
            "temperature": 0.9,
            "top_p": 0.9,
            "max_tokens": 1024
        }
        
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        reply = result['choices'][0]['message']['content']
        
        # Clean up
        if reply:
            reply = re.sub(r'^\[.*?\]:?\s*', '', reply)
            reply = re.sub(r'^\w+:\s*', '', reply)
            reply = reply.replace("[Iris]:", "").replace("Iris:", "").strip()
            # New: Remove brackets around names in the middle of sentences
            reply = re.sub(r'\[([^\]]+)\]', r'\1', reply)
            
        return reply
        
    except Exception as e:
        logging.error(f"OpenRouter API Error: {e}")
        return None

async def get_ai_response(chat_id, user_text, user_name=None, chat_type="group"):
    if not ENABLED_PROVIDERS:
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
        # Llama 3.1 8B is smart enough for the full persona prompt!
        system_prompt = SYSTEM_PROMPT_DM if chat_type == "private" else SYSTEM_PROMPT_GROUP

    # Get history from DB
    history = db.get_history(chat_id, limit=MAX_HISTORY)
    
    reply = None

    # Try providers in order
    for provider in ENABLED_PROVIDERS:
        try:
            logging.info(f"🤔 Thinking with {provider}...")
            if provider == "ollama":
                loop = asyncio.get_running_loop()
                reply = await loop.run_in_executor(None, get_ollama_response_sync, user_text, history, user_name, system_prompt)
            elif provider == "groq":
                loop = asyncio.get_running_loop()
                reply = await loop.run_in_executor(None, get_groq_response_sync, user_text, history, user_name, system_prompt)
            elif provider == "gemini":
                reply = await get_gemini_response(user_text, history, user_name, system_prompt)
            elif provider == "mistral":
                reply = await get_mistral_response(user_text, history, user_name, system_prompt)
            elif provider == "openrouter":
                loop = asyncio.get_running_loop()
                reply = await loop.run_in_executor(None, get_openrouter_response_sync, user_text, history, user_name, system_prompt)
            
            if reply:
                logging.info(f"✅ Response generated by {provider}")
                break # Stop if successful
            else:
                logging.warning(f"⚠️ {provider} returned empty response. Trying next...")
        
        except Exception as e:
            logging.error(f"❌ Error with {provider}: {e}")
            continue # Try next provider

    if reply:
        # Save interaction to DB
        privacy_on = settings.get("privacy_mode", 0)
        logged_name = "User" if privacy_on else user_name
        db.add_message(chat_id, "user", user_text, logged_name)
        db.add_message(chat_id, "assistant", reply)
    else:
        reply = "Ahh my brain glitched~ 🥺 try again please! 💖"

    return reply

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name if update.effective_user else "Unknown"
    chat_type = update.effective_chat.type

    # Track user record for username-based moderation
    if update.effective_user:
        db.track_user(
            update.effective_user.id, 
            update.effective_user.username, 
            update.effective_user.first_name
        )
        if update.effective_user.username:
            db.update_user_record(chat_id, user_id, update.effective_user.username)

    # 1. Bot Account Detection (New)
    if update.effective_user and update.effective_user.is_bot and update.effective_user.id != context.bot.id:
        if chat_type != "private":
            logging.info(f"🤖 Bot detected in group: {user_name} ({user_id})")
            # Auto-ban or warn bot accounts? User said "don't want any bot accounts... analyze then warn... no bot accounts allowed"
            # Let's go with immediate action for bots
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await update.message.reply_text(f"🚫 No bots allowed here, sweetie! Sayonara~ ✨🔨")
                return
            except Exception as e:
                logging.error(f"Failed to ban bot account: {e}")

    if not update.message.text:
        return

    user_text = update.message.text
    
    # --- Context-Aware Pre-processing ---
    # Strip code blocks and quotes for filter checks
    filtered_text = re.sub(r'```[\s\S]*?```', '', user_text) # Multi-line code
    filtered_text = re.sub(r'`[^`]*`', '', filtered_text)    # Single-line code
    filtered_text = re.sub(r'^>.*$', '', filtered_text, flags=re.MULTILINE) # Quotes
    filtered_text = filtered_text.strip()
    
    bot_username = context.bot.username

    # 2. NSFW & Content Filtering (New)
    settings = db.get_mod_settings(chat_id)
    if settings.get("auto_mod", 1) and chat_type != "private":
        # Skip auto-mod for admins
        if await is_admin(update, context):
            pass
        else:
            # --- Anti-Flood (Spam Control) ---
            user_flood = flood_data[f"{chat_id}:{user_id}"]
            now = time.time()
            
            # Simple Flood: Repeated messages
            if user_text == user_flood["last_msg"] and (now - user_flood["last_time"]) < 5:
                user_flood["count"] += 1
            else:
                user_flood["count"] = 1
                user_flood["last_msg"] = user_text
            
            user_flood["last_time"] = now
            
            if user_flood["count"] > 3: # 4th repeated message
                try:
                    await update.message.delete()
                    if user_flood["count"] == 4: # Only warn once per flood spree
                        count = db.add_warn(chat_id, user_id, "Spam/Flood detected")
                        await context.bot.send_message(chat_id, f"🚫 **{user_name}**, stop spamming! 🥺\nTotal warns: {count}/{settings['warn_limit']}")
                    return
                except Exception as e:
                    logging.error(f"Flood control failed: {e}")

            # --- Context-Aware: Excessive Caps ---
            if len(filtered_text) > 10:
                caps_ratio = sum(1 for c in filtered_text if c.isupper()) / len(filtered_text)
                if caps_ratio > 0.7: # More than 70% caps
                    try:
                        await update.message.delete()
                        await context.bot.send_message(chat_id, f"🚫 Too many caps, {user_name}! My ears hurt~ 🥺")
                        return
                    except Exception as e:
                        logging.error(f"Caps filter failed: {e}")

            # --- Context-Aware: Emoji Spam ---
            emoji_count = len(re.findall(r'[\U00010000-\U0010ffff]', user_text))
            if emoji_count > 10:
                try:
                    await update.message.delete()
                    await context.bot.send_message(chat_id, f"🚫 Too many emojis, {user_name}! ✨")
                    return
                except Exception as e:
                    logging.error(f"Emoji filter failed: {e}")

            # --- Link Filtering ---
            # Block telegram invite links and common shorteners if they contain suspicious patterns
            link_patterns = [
                r"t\.me/joinchat", r"t\.me/\+", r"telegram\.me/joinchat", 
                r"bit\.ly", r"goo\.gl", r"t\.co"
            ]
            if any(re.search(pattern, user_text) for pattern in link_patterns):
                try:
                    await update.message.delete()
                    await context.bot.send_message(chat_id, f"🚫 No invite links or shorteners allowed, {user_name}! 🥺")
                    return
                except Exception as e:
                    logging.error(f"Link filtering failed: {e}")

            # --- NSFW Words (Checked against filtered_text) ---
            nsfw_words = ["nsfw", "porn", "hentai", "sex", "pussy", "dick"] # Very basic list
            if any(word in filtered_text.lower() for word in nsfw_words):
                try:
                    await update.message.delete()
                    count = db.add_warn(chat_id, user_id, "NSFW content (Auto-Mod)")
                    await context.bot.send_message(
                        chat_id, 
                        f"⚠️ **{user_name}**, no NSFW content allowed! 🥺\n"
                        f"Message deleted. Total warns: {count}/{settings['warn_limit']}"
                    )
                    if count >= settings['warn_limit'] and settings['ban_on_limit']:
                        await context.bot.ban_chat_member(chat_id, user_id)
                    return
                except Exception as e:
                    logging.error(f"Auto-mod failed: {e}")

            # --- Custom Filters (New) ---
            custom_filters = db.get_filters(chat_id)
            for f in custom_filters:
                pattern = f["keyword"]
                is_regex = f["is_regex"]
                
                match = False
                if pattern.startswith("script:"):
                    script = pattern[7:].lower()
                    if script == "arabic" and re.search(r'[\u0600-\u06FF]', filtered_text): match = True
                    elif script == "cyrillic" and re.search(r'[\u0400-\u04FF]', filtered_text): match = True
                    elif script == "chinese" and re.search(r'[\u4e00-\u9fff]', filtered_text): match = True
                elif is_regex:
                    try:
                        if re.search(pattern, filtered_text, re.IGNORECASE):
                            match = True
                    except:
                        pass
                elif pattern.lower() in filtered_text.lower():
                    match = True
                
                if match:
                    try:
                        await update.message.delete()
                        await context.bot.send_message(chat_id, f"🚫 That word is blocked in this chat, {user_name}! 🥺")
                        return
                    except Exception as e:
                        logging.error(f"Custom filter failed: {e}")

    # Update user name in economy DB (keeps leaderboard fresh)
    if update.effective_user:
        db.update_user_name(update.effective_user.id, user_name)

    # 3. Command Cooldowns & Abuse Protection
    if user_text.startswith("!"):
        now = time.time()
        last_cmd = command_cooldowns[user_id]
        if now - last_cmd < 1.5: # 1.5s cooldown
            return # Silently ignore rapid commands
        command_cooldowns[user_id] = now

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

    # Handle ! prefixed meme commands (since MessageHandler catches these, not CommandHandler)
    lower_text = user_text.strip().lower()
    bang_commands = {
        "!meme": meme_command, "!roast": roast_command, "!ship": ship_command,
        "!8ball": eightball_command, "!uwu": uwu_command, "!rate": rate_command,
        "!vibe": vibe_command, "!pp": pp_command, "!howgay": howgay_command,
        "!simprate": simprate_command, "!truth": game_truth, "!dare": game_dare,
        "!trivia": game_trivia, "!help": help_command, "!mhelp": mhelp_command,
        "!balance": economy.balance, "!bal": economy.balance, "!beg": economy.beg,
        "!daily": economy.daily, "!gamble": economy.gamble, "!bet": economy.gamble,
        "!pay": economy.pay, "!rich": economy.leaderboard,
        "!warn": warn_command, "!mute": mute_command, "!unmute": unmute_command,
        "!ban": ban_command, "!unban": unban_command, "!kick": kick_command, "!purge": purge_command,
        "!filter": filter_command, "!stats": stats_command, "!lock": lock_command, "!unlock": unlock_command,
        "!privacy": privacy_command, "!export": export_command,
        "!import": import_command, "!retention": retention_command,
        "!admincheck": admincheck_command,
    }
    for cmd, handler in bang_commands.items():
        if lower_text == cmd or lower_text.startswith(cmd + " "):
            # Parse args for commands that need them
            parts = user_text.strip().split(maxsplit=1)
            context.args = parts[1].split() if len(parts) > 1 else []
            await handler(update, context)
            return

    # Handle !roleplay separately (needs special arg handling)
    if lower_text.startswith("!roleplay"):
        parts = user_text.strip().split(maxsplit=1)
        context.args = parts[1].split() if len(parts) > 1 else []
        await roleplay(update, context)
        return
    if lower_text == "!normal":
        await normal(update, context)
        return

    should_reply = (chat_type == 'private') or mentioned

    # Fun Feature: Randomly react to messages
    # 30% chance in DMs, 15% in groups (to not be annoying)
    if random.random() < (0.3 if chat_type == 'private' else 0.15):
        try:
            reactions = ["❤️", "🔥", "😂", "🥺", "👍", "👏", "🎉", "🤩", "🤔", "💀", "👀", "💖", "😭", "🫡"]
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
✨ **Iris - Your Cute AI Friend!** ✨

Hii~ here's everything I can do! 💖

🤖 **Chatting**
- Mention `Iris` or reply to me to chat!
- In DMs, I'm always listening~ 💕

🎉 **Fun Commands**
- `!meme` - Random meme from Reddit
- `!roast` - Playful roast~ 🔥
- `!ship` - Ship two people together 💘
- `!8ball <question>` - Magic 8-ball 🎱
- `!uwu` - UwUify any text~
- `!rate <thing>` - Rate stuff out of 10
- `!vibe` - Vibe check someone ✨
- `!pp` - The classic 📏
- `!howgay` - The meter 🏳️‍🌈
- `!simprate` - Simp detector 🚨

💰 **Economy**
- `!balance` - Check your wallet 🌸
- `!beg` - Beg for coins~
- `!daily` - Daily reward!
- `!gamble <amount>` - Double or nothing 🎰
- `!pay <amount>` - Pay a friend
- `!rich` - Leaderboard 👑

🛡️ **Moderation** (Admins Only)
- `!mhelp` - Show detailed moderation help 🛡️
- `!stats` - Admin action summary 📊
- `!admincheck` - Check for inactive admins 🏥
- `!filter` - Block keywords/regex 🚫
- `!lock` / `!unlock` - Close/Open chat 🔒
- `!privacy` - Mask names in logs 🔒
- `!retention <days>` - Auto-delete old logs 🧹
- `!export` / `!import` - Backup/Restore settings 📦
- `!warn` - Warn a user ⚠️
- `!mute <mins>` - Mute for X mins (default 60) 🤐
- `!unmute` - Unmute someone ✨
- `!unban <id>` - Unban user (needs ID) 🔓
- `!ban` - Ban from the group 🔨
- `!kick` - Kick from the group 👟
- `!purge` - Delete messages (reply to start) 🧹

🎭 **Roleplay**
- `!roleplay <scenario>` - I become any character!
- `!normal` - Back to being me~

🎲 **Games**
- `!truth` - Truth question 👀
- `!dare` - Dare you~ 🔥
- `!trivia` - Test your brain 🧠

⚙️ **Utils**
- `!reset` - Wipe my memory
- `!donate` - Support my server 🥺
- `!help` - This message

Have fun~ 🌸💖
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
        edit_handler = MessageHandler(filters.TEXT & (~filters.COMMAND) & filters.UpdateType.EDITED_MESSAGE, handle_message)
        
        # New Command Handlers
        application.add_handler(CommandHandler('roleplay', roleplay))
        application.add_handler(CommandHandler('normal', normal))
        application.add_handler(CommandHandler('truth', game_truth))
        application.add_handler(CommandHandler('dare', game_dare))
        application.add_handler(CommandHandler('trivia', game_trivia))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('mhelp', mhelp_command))

        # Dank Meme Handlers
        application.add_handler(CommandHandler('meme', meme_command))
        application.add_handler(CommandHandler('roast', roast_command))
        application.add_handler(CommandHandler('ship', ship_command))
        application.add_handler(CommandHandler('8ball', eightball_command))
        application.add_handler(CommandHandler('uwu', uwu_command))
        application.add_handler(CommandHandler('rate', rate_command))
        application.add_handler(CommandHandler('vibe', vibe_command))
        application.add_handler(CommandHandler('pp', pp_command))
        application.add_handler(CommandHandler('howgay', howgay_command))
        application.add_handler(CommandHandler('simprate', simprate_command))

        # Economy Handlers
        application.add_handler(CommandHandler('balance', economy.balance))
        application.add_handler(CommandHandler('bal', economy.balance))
        application.add_handler(CommandHandler('beg', economy.beg))
        application.add_handler(CommandHandler('daily', economy.daily))
        application.add_handler(CommandHandler('gamble', economy.gamble))
        application.add_handler(CommandHandler('bet', economy.gamble))
        application.add_handler(CommandHandler('pay', economy.pay))
        application.add_handler(CommandHandler('rich', economy.leaderboard))

        # Moderation Handlers
        application.add_handler(CommandHandler('warn', warn_command))
        application.add_handler(CommandHandler('mute', mute_command))
        application.add_handler(CommandHandler('unmute', unmute_command))
        application.add_handler(CommandHandler('unban', unban_command))
        application.add_handler(CommandHandler('ban', ban_command))
        application.add_handler(CommandHandler('kick', kick_command))
        application.add_handler(CommandHandler('purge', purge_command))
        application.add_handler(CommandHandler('filter', filter_command))
        application.add_handler(CommandHandler('stats', stats_command))
        application.add_handler(CommandHandler('lock', lock_command))
        application.add_handler(CommandHandler('unlock', unlock_command))
        application.add_handler(CommandHandler('privacy', privacy_command))
        application.add_handler(CommandHandler('export', export_command))
        application.add_handler(CommandHandler('import', import_command))
        application.add_handler(CommandHandler('retention', retention_command))
        application.add_handler(CommandHandler('admincheck', admincheck_command))

        # Schedule periodic cleanup (every 24 hours) if JobQueue is available
        if application.job_queue:
            application.job_queue.run_repeating(cleanup_job, interval=86400, first=10)
        else:
            logging.warning("⚠️ JobQueue not available. Scheduled tasks (like log cleanup) will not run.")

        application.add_handler(start_handler)
        application.add_handler(msg_handler)
        application.add_handler(edit_handler)
        
        providers_str = ", ".join(ENABLED_PROVIDERS) if ENABLED_PROVIDERS else "NO AI BRAIN"
        print(f"Iris is waking up with {providers_str}... ✨ Press Ctrl+C to stop.")
        application.run_polling()
