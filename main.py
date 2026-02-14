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

# Telethon for user account lookups
from telethon import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import UsernameNotOccupiedError, UsernameInvalidError

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
UPI_ID = os.getenv("UPI_ID", "your-upi-id@okhdfcbank") # Default or from env

# Telethon Configuration (Optional)
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")

# Global Telethon client (will be initialized if credentials are provided)
telethon_client = None

# Anti-flood tracking: {chat_id: {user_id: [timestamp1, timestamp2, ...]}}
flood_tracker = defaultdict(lambda: defaultdict(list))

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

async def is_user_in_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Check if a user is currently in the chat"""
    try:
        chat_member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        # Member statuses: creator, administrator, member, restricted, left, kicked
        return chat_member.status in ['creator', 'administrator', 'member', 'restricted']
    except Exception as e:
        logging.warning(f"Failed to check if user {user_id} is in chat: {e}")
        return False

async def resolve_username_with_telethon(username):
    """Use Telethon to resolve a username to a user ID and details"""
    global telethon_client
    
    if not telethon_client:
        return None
    
    try:
        # Clean username
        clean_username = username.lstrip("@")
        
        # Get user info via Telethon
        user_full = await telethon_client(GetFullUserRequest(clean_username))
        user = user_full.users[0]
        
        # Track this user in our database
        db.track_user(user.id, user.username, user.first_name)
        
        # Return a mock user object compatible with python-telegram-bot
        class MockUser:
            def __init__(self, tg_user):
                self.id = tg_user.id
                self.username = tg_user.username
                self.first_name = tg_user.first_name or tg_user.username or "User"
                self.last_name = getattr(tg_user, 'last_name', None)
                self.is_bot = getattr(tg_user, 'bot', False)
        
        logging.info(f"✅ Telethon resolved @{clean_username} -> User ID: {user.id}")
        return MockUser(user)
    
    except (UsernameNotOccupiedError, UsernameInvalidError):
        logging.warning(f"Telethon: Username @{username} not found")
        return None
    except Exception as e:
        logging.warning(f"Telethon lookup failed for @{username}: {e}")
        return None

async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get the target user from reply or @username mention or plain username"""
    # 1. Check reply
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        # Track the target user
        db.track_user(target.id, target.username, target.first_name)
        return target
    
    # 2. Check entities (for text_mention - users without usernames mentioned by name)
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_mention":
                target = entity.user
                db.track_user(target.id, target.username, target.first_name)
                return target

    # 3. Resolve username (with or without @)
    # We'll check all arguments for something that could be a username
    target_username = None
    if context.args:
        # First arg is likely the username
        potential_username = context.args[0]
        # Accept both @username and username formats
        if potential_username.startswith("@") or not potential_username.isdigit():
            target_username = potential_username
            
    if target_username:
        # Clean the username (remove @ if present)
        clean_username = target_username.lstrip("@").lower()
        
        # Try Telethon first (most reliable for username lookups)
        if telethon_client:
            telethon_user = await resolve_username_with_telethon(clean_username)
            if telethon_user:
                return telethon_user
        
        try:
            logging.info(f"Attempting to resolve target: {target_username}")
            # Try to get the user directly via Bot API (requires @ prefix)
            # Note: get_chat works for public usernames
            api_username = f"@{clean_username}" if not target_username.startswith("@") else target_username
            target_chat = await context.bot.get_chat(api_username)
            
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
            logging.warning(f"Bot API resolution failed for {target_username}: {e}")
            
            # Fallback A: Check database
            chat_id = update.effective_chat.id
            user_id = db.get_user_id_by_username(clean_username, chat_id)
            if user_id:
                try:
                    chat_member = await context.bot.get_chat_member(chat_id, user_id)
                    return chat_member.user
                except:
                    # If they are not in the chat, we can still return a mock user if we have an ID
                    class MockUser:
                        def __init__(self, uid, uname):
                            self.id = uid
                            self.username = uname
                            self.first_name = uname.capitalize() or "User"
                    return MockUser(user_id, clean_username)
            
            # Fallback B: Check chat members list
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

    # Track the admin user
    if update.effective_user:
        db.track_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)

    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to warn them! ⚠️")
        return

    # Track the target user
    db.track_user(target_user.id, target_user.username, target_user.first_name)

    # Check if user is in the group
    chat_id = update.effective_chat.id
    if not await is_user_in_chat(update, context, target_user.id):
        await update.message.reply_text(f"Umm... {target_user.first_name} isn't even in this group anymore, silly! 🥺\nThey must have left or been removed already~ ✨")
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
    if args_for_reason and (args_for_reason[0].startswith("@") or not args_for_reason[0].isdigit()):
        # First arg is likely a username, skip it for reason parsing
        args_for_reason.pop(0)
        
    if args_for_reason:
        arg = args_for_reason[0].lower()
        if arg in presets:
            reason = presets[arg]
        else:
            reason = " ".join(args_for_reason)

    if target_user.id == context.bot.id:
        await update.message.reply_text("Wait, why are you trying to warn me?? 😭")
        return

    count = db.add_warn(chat_id, target_user.id, reason, target_user.username)
    db.update_user_record(chat_id, target_user.id, target_user.username)
    db.log_admin_action(chat_id, update.effective_user.id, "warn", target_user.id, reason)
    settings = db.get_mod_settings(chat_id)
    
    msg = f"⚠️ **{target_user.first_name} has been warned!**\n"
    msg += f"Reason: {reason}\n"
    msg += f"Total Warns: {count}/{settings['warn_limit']}"
    
    await update.message.reply_text(msg, parse_mode='Markdown')
    
    # Check if user reached warn limit and execute configured action
    if count >= settings['warn_limit']:
        action = settings.get('warn_action', 'ban')
        
        if action == 'ban':
            try:
                await context.bot.ban_chat_member(chat_id, target_user.id)
                await update.message.reply_text(f"❌ **{target_user.first_name} reached the warn limit and was banned!** 🔨")
                db.log_admin_action(chat_id, update.effective_user.id, "auto_ban", target_user.id, "Warn limit reached")
            except Exception as e:
                logging.error(f"Failed to ban on warn limit: {e}")
                await update.message.reply_text(f"⚠️ Failed to ban user: {e}")
        
        elif action == 'kick':
            try:
                await context.bot.unban_chat_member(chat_id, target_user.id)
                await update.message.reply_text(f"👟 **{target_user.first_name} reached the warn limit and was kicked!**\nThey can rejoin if they behave~ ✨")
                db.log_admin_action(chat_id, update.effective_user.id, "auto_kick", target_user.id, "Warn limit reached")
            except Exception as e:
                logging.error(f"Failed to kick on warn limit: {e}")
                await update.message.reply_text(f"⚠️ Failed to kick user: {e}")
        
        elif action == 'mute':
            try:
                duration = settings.get('warn_action_duration', 60)
                until = datetime.now() + timedelta(minutes=duration)
                permissions = ChatPermissions(can_send_messages=False)
                await context.bot.restrict_chat_member(chat_id, target_user.id, permissions, until_date=until)
                await update.message.reply_text(f"🤐 **{target_user.first_name} reached the warn limit and was muted!**\nDuration: {duration} minutes")
                db.set_mute(chat_id, target_user.id, True, until.isoformat(), target_user.username)
                db.log_admin_action(chat_id, update.effective_user.id, "auto_mute", target_user.id, f"Warn limit reached ({duration}m)")
            except Exception as e:
                logging.error(f"Failed to mute on warn limit: {e}")
                await update.message.reply_text(f"⚠️ Failed to mute user: {e}")
        
        elif action == 'none':
            await update.message.reply_text(f"⚠️ **{target_user.first_name} reached the warn limit!**\nAdmins should take manual action. No automatic action is configured.")
        
        # Respect legacy ban_on_limit setting if warn_action is not explicitly set
        elif settings.get('ban_on_limit', 1):
            try:
                await context.bot.ban_chat_member(chat_id, target_user.id)
                await update.message.reply_text(f"❌ **{target_user.first_name} reached the warn limit and was banned!** 🔨")
                db.log_admin_action(chat_id, update.effective_user.id, "auto_ban", target_user.id, "Warn limit reached")
            except Exception as e:
                logging.error(f"Failed to ban on warn limit: {e}")

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mute a user"""
    if not await is_admin(update, context):
        return

    # Track the admin user
    if update.effective_user:
        db.track_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)

    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to mute them! 🤐")
        return

    # Track the target user
    db.track_user(target_user.id, target_user.username, target_user.first_name)

    chat_id = update.effective_chat.id
    
    # Check if user is in the group
    if not await is_user_in_chat(update, context, target_user.id):
        await update.message.reply_text(f"Umm... {target_user.first_name} isn't even in this group anymore, sweetie! 🥺\nCan't mute someone who's already gone~ 💫")
        return
    
    # Protect admins
    if await is_target_admin(update, context, target_user.id):
        await update.message.reply_text("I'm not muting an admin, sillie! They're important! 🥺💖")
        return

    # Natural language time parsing (e.g., "10m", "1h", "1d")
    duration_mins = 60
    
    # Extract duration from args if present (skip first arg if it was a username)
    time_args = list(context.args)
    if time_args and (time_args[0].startswith("@") or not time_args[0].isdigit()):
        # First arg is likely a username, skip it
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
    db.update_user_record(chat_id, target_user.id, target_user.username)
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

    # Track the admin user
    if update.effective_user:
        db.track_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)

    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to unmute them! ✨")
        return

    # Track the target user
    db.track_user(target_user.id, target_user.username, target_user.first_name)

    chat_id = update.effective_chat.id
    
    # Check if user is in the group (allow unmute even if they left, for admin convenience)
    # No check here - admins might want to unmute before unbanning
    
    db.set_mute(chat_id, target_user.id, False, username=target_user.username)
    db.update_user_record(chat_id, target_user.id, target_user.username)
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

    # Track the admin user
    if update.effective_user:
        db.track_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)

    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to ban them! 🔨")
        return

    # Track the target user
    db.track_user(target_user.id, target_user.username, target_user.first_name)

    chat_id = update.effective_chat.id
    
    # Check if user is in the group
    if not await is_user_in_chat(update, context, target_user.id):
        await update.message.reply_text(f"Ummm... {target_user.first_name} already left the group, babe! 🥺\nNo need to ban someone who's not even here~ 💕")
        return
    
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

    # Track the admin user
    if update.effective_user:
        db.track_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)

    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to kick them! 👟")
        return

    # Track the target user
    db.track_user(target_user.id, target_user.username, target_user.first_name)

    chat_id = update.effective_chat.id
    
    # Check if user is in the group
    if not await is_user_in_chat(update, context, target_user.id):
        await update.message.reply_text(f"Ehehe~ {target_user.first_name} isn't in the group anymore! 🥺\nThey already left, so no kicking needed~ 👟💫")
        return
    
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

    # Track the admin user
    if update.effective_user:
        db.track_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)

    target_user = await get_target_user(update, context)
    target_user_id = None
    chat_id = update.effective_chat.id
    
    if target_user:
        # Track the target user
        db.track_user(target_user.id, target_user.username, target_user.first_name)
        target_user_id = target_user.id
    elif context.args:
        try:
            target_user_id = int(context.args[0])
        except ValueError:
            # Maybe it's a username without @?
            username = context.args[0].replace("@", "")
            target_user_id = db.get_user_id_by_username(username, chat_id)
            if not target_user_id:
                await update.message.reply_text("That doesn't look like a valid User ID or stored username! 🥺")
                return

    if not target_user_id:
        await update.message.reply_text("Reply to someone, use `@username`, or provide a User ID to unban! 🔓")
        return

    try:
        await context.bot.unban_chat_member(chat_id, target_user_id)
        # Try to update user record if we have the target_user object with username
        if target_user and target_user.username:
            db.update_user_record(chat_id, target_user_id, target_user.username)
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

async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pin a message"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can pin messages, cutie! 🥺")
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to pin it! 📌")
        return
    
    chat_id = update.effective_chat.id
    message_id = update.message.reply_to_message.message_id
    
    # Check if silent pin (optional)
    notify = True
    if context.args and context.args[0].lower() in ['silent', 'quiet']:
        notify = False
    
    try:
        await context.bot.pin_chat_message(chat_id, message_id, disable_notification=not notify)
        db.log_admin_action(chat_id, update.effective_user.id, "pin", message_id)
        
        if notify:
            await update.message.reply_text("📌 **Message pinned!** Everyone will see this~ ✨")
        else:
            await update.message.reply_text("📌 **Message pinned silently!** No notifications sent~ 🤫")
    except Exception as e:
        await update.message.reply_text(f"Failed to pin message: {e}")

async def unpin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unpin a message or all messages"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can unpin messages, cutie! 🥺")
        return
    
    chat_id = update.effective_chat.id
    
    # Check if unpinning all
    if context.args and context.args[0].lower() == 'all':
        try:
            await context.bot.unpin_all_chat_messages(chat_id)
            db.log_admin_action(chat_id, update.effective_user.id, "unpin_all")
            await update.message.reply_text("📌 **All pinned messages removed!** Fresh start~ ✨")
        except Exception as e:
            await update.message.reply_text(f"Failed to unpin all: {e}")
        return
    
    # Unpin specific message (need reply) or most recent
    message_id = None
    if update.message.reply_to_message:
        message_id = update.message.reply_to_message.message_id
    
    try:
        if message_id:
            await context.bot.unpin_chat_message(chat_id, message_id)
        else:
            await context.bot.unpin_chat_message(chat_id)
        
        db.log_admin_action(chat_id, update.effective_user.id, "unpin", message_id)
        await update.message.reply_text("📌 **Message unpinned!** ✨")
    except Exception as e:
        await update.message.reply_text(f"Failed to unpin: {e}")

async def promote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Promote a user to admin"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can promote users, cutie! 🥺")
        return
    
    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to promote them! 👑")
        return
    
    chat_id = update.effective_chat.id
    
    # Custom title (optional)
    title = None
    if context.args and len(context.args) > 1:
        title = " ".join(context.args[1:])[:16]  # Telegram limit is 16 chars
    
    try:
        # Grant standard admin permissions
        await context.bot.promote_chat_member(
            chat_id,
            target_user.id,
            can_delete_messages=True,
            can_restrict_members=True,
            can_pin_messages=True,
            can_manage_chat=True
        )
        
        # Set custom title if provided
        if title:
            await context.bot.set_chat_administrator_custom_title(chat_id, target_user.id, title)
        
        db.log_admin_action(chat_id, update.effective_user.id, "promote", target_user.id, title or "")
        
        msg = f"👑 **{target_user.first_name} has been promoted to admin!**"
        if title:
            msg += f"\n**Title:** {title}"
        msg += "\n\nWelcome to the team~ 💕"
        
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Failed to promote: {e}")

async def demote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Demote an admin to regular user"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can demote users, cutie! 🥺")
        return
    
    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("Reply to someone or use `@username` to demote them! 👤")
        return
    
    chat_id = update.effective_chat.id
    
    try:
        await context.bot.promote_chat_member(
            chat_id,
            target_user.id,
            can_change_info=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_chat=False
        )
        
        db.log_admin_action(chat_id, update.effective_user.id, "demote", target_user.id)
        await update.message.reply_text(f"👤 **{target_user.first_name} has been demoted to regular member.**\nThey can still chat normally~ ✨")
    except Exception as e:
        await update.message.reply_text(f"Failed to demote: {e}")

async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send an announcement message"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can make announcements, cutie! 🥺")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `!announce <message>`\n\nExample: `!announce Meeting at 8 PM!`", parse_mode='Markdown')
        return
    
    chat_id = update.effective_chat.id
    announcement = " ".join(context.args)
    
    msg = f"📢 **ANNOUNCEMENT** 📢\n\n{announcement}\n\n_— From the admins_ 💕"
    
    try:
        sent_message = await context.bot.send_message(chat_id, msg, parse_mode='Markdown')
        # Auto-pin announcements
        await context.bot.pin_chat_message(chat_id, sent_message.message_id, disable_notification=False)
        
        db.log_admin_action(chat_id, update.effective_user.id, "announce", reason=announcement[:100])
        
        # Delete the command message
        try:
            await update.message.delete()
        except:
            pass
    except Exception as e:
        await update.message.reply_text(f"Failed to send announcement: {e}")

# ==================== WELCOME / GOODBYE / SLOWMODE ====================

async def setwelcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set a custom welcome message for new members."""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set welcome messages, cutie! 🥺")
        return

    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "Usage: `!setwelcome <message>`\n\n"
            "**Placeholders:**\n"
            "• `{name}` — Member's name\n"
            "• `{group}` — Group name\n"
            "• `{count}` — Member count\n\n"
            "Example: `!setwelcome Welcome {name} to {group}! You're member #{count}!`\n\n"
            "Use `!setwelcome off` to disable.",
            parse_mode='Markdown'
        )
        return

    if context.args[0].lower() == "off":
        db.update_chat_setting(chat_id, "welcome_msg", None)
        await update.message.reply_text("✅ Welcome messages disabled!")
        return

    welcome_text = " ".join(context.args)
    db.update_chat_setting(chat_id, "welcome_msg", welcome_text)
    await update.message.reply_text(f"✅ **Welcome message set!**\n\nPreview:\n{welcome_text}", parse_mode='Markdown')

async def setgoodbye_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set a custom goodbye message."""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set goodbye messages, cutie! 🥺")
        return

    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "Usage: `!setgoodbye <message>`\n\n"
            "**Placeholders:** `{name}`, `{group}`\n\n"
            "Use `!setgoodbye off` to disable.",
            parse_mode='Markdown'
        )
        return

    if context.args[0].lower() == "off":
        db.update_chat_setting(chat_id, "goodbye_msg", None)
        await update.message.reply_text("✅ Goodbye messages disabled!")
        return

    goodbye_text = " ".join(context.args)
    db.update_chat_setting(chat_id, "goodbye_msg", goodbye_text)
    await update.message.reply_text(f"✅ **Goodbye message set!**\n\nPreview:\n{goodbye_text}", parse_mode='Markdown')

async def welcome_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new members joining the group."""
    if not update.message or not update.message.new_chat_members:
        return

    chat_id = update.effective_chat.id
    chat = update.effective_chat

    welcome_msg = db.get_welcome_msg(chat_id)

    for member in update.message.new_chat_members:
        if member.is_bot:
            continue

        # Track the user
        db.track_user(member.id, member.username, member.first_name)

        if welcome_msg:
            try:
                member_count = await context.bot.get_chat_member_count(chat_id)
            except Exception:
                member_count = "?"

            text = welcome_msg.replace("{name}", member.first_name)
            text = text.replace("{group}", chat.title or "the group")
            text = text.replace("{count}", str(member_count))
        else:
            text = f"Welcome to the group, **{member.first_name}**! 💖✨\nHope you have a great time here~"

        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')

async def goodbye_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle members leaving the group."""
    if not update.message or not update.message.left_chat_member:
        return

    chat_id = update.effective_chat.id
    chat = update.effective_chat
    member = update.message.left_chat_member

    if member.is_bot:
        return

    goodbye_msg = db.get_goodbye_msg(chat_id)

    if goodbye_msg:
        text = goodbye_msg.replace("{name}", member.first_name)
        text = text.replace("{group}", chat.title or "the group")
    else:
        return  # No default goodbye — only send if configured

    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')

async def slowmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or disable slowmode."""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set slowmode, cutie! 🥺")
        return

    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "Usage: `!slowmode <seconds>`\n"
            "Example: `!slowmode 10` (10 second delay)\n"
            "Use `!slowmode off` or `!slowmode 0` to disable.",
            parse_mode='Markdown'
        )
        return

    arg = context.args[0].lower()

    if arg in ["off", "0"]:
        try:
            await context.bot.set_chat_slow_mode_delay(chat_id, 0)
            await update.message.reply_text("✅ Slowmode disabled! Everyone can chat freely~ ✨")
            db.log_admin_action(chat_id, update.effective_user.id, "slowmode", reason="off")
        except Exception as e:
            await update.message.reply_text(f"Failed to disable slowmode: {e}")
        return

    try:
        seconds = int(arg)
        if seconds < 0 or seconds > 3600:
            await update.message.reply_text("Slowmode must be between 0 and 3600 seconds! 🥺")
            return

        await context.bot.set_chat_slow_mode_delay(chat_id, seconds)
        await update.message.reply_text(f"✅ **Slowmode set to {seconds} seconds!** 🐌")
        db.log_admin_action(chat_id, update.effective_user.id, "slowmode", reason=f"{seconds}s")
    except ValueError:
        await update.message.reply_text("Please provide a valid number! 🥺")
    except Exception as e:
        await update.message.reply_text(f"Failed to set slowmode: {e}")

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display group rules"""
    chat_id = update.effective_chat.id
    rules = db.get_note(chat_id, "rules")
    
    if rules:
        await update.message.reply_text(f"📜 **Group Rules**\n\n{rules}", parse_mode='Markdown')
    else:
        await update.message.reply_text("📜 No rules set yet!\n\nAdmins can set rules with `!setrules`", parse_mode='Markdown')

async def setrules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set group rules (admin only)"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set rules, cutie! 🥺")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `!setrules <rules text>`\n\nExample: `!setrules 1. Be respectful\\n2. No spam\\n3. Have fun!`", parse_mode='Markdown')
        return
    
    chat_id = update.effective_chat.id
    rules_text = " ".join(context.args)
    
    if db.save_note(chat_id, "rules", rules_text, update.effective_user.id):
        await update.message.reply_text("✅ **Rules updated!**\nEveryone can see them with `!rules` 📜", parse_mode='Markdown')
        db.log_admin_action(chat_id, update.effective_user.id, "setrules")
    else:
        await update.message.reply_text("Failed to save rules! 😢")

async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get a saved note"""
    if not context.args:
        await update.message.reply_text("Usage: `!note <name>`\n\nExample: `!note welcome`\nSee all notes with `!notes`", parse_mode='Markdown')
        return
    
    chat_id = update.effective_chat.id
    note_name = context.args[0]
    note_content = db.get_note(chat_id, note_name)
    
    if note_content:
        await update.message.reply_text(f"📝 **{note_name}**\n\n{note_content}", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ Note `{note_name}` not found!\nSee all notes with `!notes`", parse_mode='Markdown')

async def notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all saved notes"""
    chat_id = update.effective_chat.id
    all_notes = db.get_all_notes(chat_id)
    
    if all_notes:
        note_list = "\n".join([f"• `{name}`" for name, _ in all_notes])
        msg = f"📝 **Saved Notes** ({len(all_notes)})\n\n{note_list}\n\n_Use `!note <name>` to view a note_"
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("📝 No notes saved yet!\n\nAdmins can save notes with `!savenote`", parse_mode='Markdown')

async def savenote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save a note (admin only)"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can save notes, cutie! 🥺")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `!savenote <name> <content>`\n\nExample: `!savenote welcome Welcome to our group!`", parse_mode='Markdown')
        return
    
    chat_id = update.effective_chat.id
    note_name = context.args[0]
    note_content = " ".join(context.args[1:])
    
    if db.save_note(chat_id, note_name, note_content, update.effective_user.id):
        await update.message.reply_text(f"✅ **Note saved!**\nUse `!note {note_name}` to view it 📝", parse_mode='Markdown')
        db.log_admin_action(chat_id, update.effective_user.id, "savenote", reason=note_name)
    else:
        await update.message.reply_text("Failed to save note! 😢")

async def delnote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a note (admin only)"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can delete notes, cutie! 🥺")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `!delnote <name>`\n\nExample: `!delnote welcome`", parse_mode='Markdown')
        return
    
    chat_id = update.effective_chat.id
    note_name = context.args[0]
    
    if db.delete_note(chat_id, note_name):
        await update.message.reply_text(f"✅ **Note `{note_name}` deleted!** 🗑️", parse_mode='Markdown')
        db.log_admin_action(chat_id, update.effective_user.id, "delnote", reason=note_name)
    else:
        await update.message.reply_text(f"❌ Note `{note_name}` not found!", parse_mode='Markdown')

async def groupstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show group statistics"""
    chat_id = update.effective_chat.id
    
    try:
        # Get chat info
        chat = await context.bot.get_chat(chat_id)
        member_count = await context.bot.get_chat_member_count(chat_id)
        admins = await context.bot.get_chat_administrators(chat_id)
        admin_count = len([a for a in admins if not a.user.is_bot])
        
        # Get database stats
        import sqlite3
        conn = sqlite3.connect(db.DB_FILE)
        cursor = conn.cursor()
        
        # Total messages logged
        cursor.execute('SELECT COUNT(*) FROM messages WHERE chat_id = ?', (chat_id,))
        total_messages = cursor.fetchone()[0]

        # Unique users (from sender_name)
        cursor.execute('SELECT COUNT(DISTINCT sender_name) FROM messages WHERE chat_id = ? AND sender_name IS NOT NULL', (chat_id,))
        unique_users = cursor.fetchone()[0]

        # Top 5 most active users (by sender_name since messages table doesn't have user_id)
        cursor.execute('''
            SELECT sender_name, COUNT(*) as msg_count
            FROM messages
            WHERE chat_id = ? AND sender_name IS NOT NULL
            GROUP BY sender_name
            ORDER BY msg_count DESC
            LIMIT 5
        ''', (chat_id,))
        top_users = cursor.fetchall()

        # Admin actions count
        cursor.execute('SELECT COUNT(*) FROM admin_actions WHERE chat_id = ?', (chat_id,))
        admin_actions = cursor.fetchone()[0]

        # Total warns
        cursor.execute('SELECT COALESCE(SUM(warns), 0) FROM moderation WHERE chat_id = ?', (chat_id,))
        total_warns = cursor.fetchone()[0]
        
        conn.close()
        
        # Build stats message
        msg = f"📊 **Group Statistics**\n\n"
        msg += f"**Group:** {chat.title}\n"
        msg += f"**Members:** {member_count}\n"
        msg += f"**Admins:** {admin_count}\n\n"
        
        msg += f"**Activity:**\n"
        msg += f"• Messages logged: {total_messages}\n"
        msg += f"• Unique chatters: {unique_users}\n"
        msg += f"• Admin actions: {admin_actions}\n"
        msg += f"• Total warnings: {total_warns}\n\n"
        
        if top_users:
            msg += f"**🏆 Top Chatters:**\n"
            for i, (name, msg_count) in enumerate(top_users, 1):
                msg += f"{i}. {name}: {msg_count} messages\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    
    except Exception as e:
        await update.message.reply_text(f"Failed to get stats: {e}")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Report a message to admins"""
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to report it! 🚨")
        return
    
    chat_id = update.effective_chat.id
    reporter = update.effective_user
    reported_message = update.message.reply_to_message
    reported_user = reported_message.from_user
    
    # Don't allow reporting admins
    if await is_target_admin(update, context, reported_user.id):
        await update.message.reply_text("You can't report an admin, silly! 🥺")
        return
    
    # Get reason (optional)
    reason = " ".join(context.args) if context.args else "No reason provided"
    
    # Notify admins
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        
        report_msg = (
            f"🚨 **NEW REPORT** 🚨\n\n"
            f"**Reported by:** {reporter.first_name} (@{reporter.username or 'no username'})\n"
            f"**Reported user:** {reported_user.first_name} (@{reported_user.username or 'no username'})\n"
            f"**Reason:** {reason}\n\n"
            f"_Message: \"{reported_message.text[:100] if reported_message.text else '[Media]'}\"_"
        )
        
        # Send to all admins via DM (if bot can)
        admin_count = 0
        for admin in admins:
            if admin.user.is_bot:
                continue
            try:
                await context.bot.send_message(admin.user.id, report_msg, parse_mode='Markdown')
                admin_count += 1
            except:
                # Admin hasn't started bot or blocked it
                pass
        
        # Also send in group (tagged to admins)
        await update.message.reply_text(
            f"✅ **Report submitted!**\n"
            f"Admins have been notified ({admin_count} reached via DM).\n"
            f"Thank you for keeping the group safe~ 💕"
        )
        
        db.log_admin_action(chat_id, reporter.id, "report", reported_user.id, reason[:100])
        
        # Delete the report command for privacy
        try:
            await update.message.delete()
        except:
            pass
    
    except Exception as e:
        await update.message.reply_text(f"Failed to submit report: {e}")

async def antiflood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configure anti-flood protection"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can configure anti-flood, cutie! 🥺")
        return
    
    chat_id = update.effective_chat.id
    
    if not context.args:
        # Show current settings
        settings = db.get_mod_settings(chat_id)
        enabled = settings.get('antiflood_enabled', 1)
        threshold = settings.get('antiflood_threshold', 5)
        timeframe = settings.get('antiflood_timeframe', 5)
        action = settings.get('antiflood_action', 'mute')
        
        status = "✅ Enabled" if enabled else "❌ Disabled"
        
        msg = f"🌊 **Anti-Flood Settings**\n\n"
        msg += f"**Status:** {status}\n"
        msg += f"**Threshold:** {threshold} messages\n"
        msg += f"**Timeframe:** {timeframe} seconds\n"
        msg += f"**Action:** {action.upper()}\n\n"
        msg += f"**Usage:**\n"
        msg += f"• `!antiflood on` - Enable anti-flood\n"
        msg += f"• `!antiflood off` - Disable anti-flood\n"
        msg += f"• `!antiflood set <msgs> <secs> <action>` - Configure\n"
        msg += f"  Example: `!antiflood set 7 10 warn`\n\n"
        msg += f"**Actions:** warn, mute, kick, ban"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        return
    
    arg = context.args[0].lower()
    
    if arg == "on":
        if db.set_antiflood(chat_id, enabled=True):
            await update.message.reply_text("✅ **Anti-flood protection enabled!**\nSpammers will be dealt with~ 🌊")
            db.log_admin_action(chat_id, update.effective_user.id, "antiflood", reason="enabled")
        else:
            await update.message.reply_text("Failed to enable anti-flood! 😢")
    
    elif arg == "off":
        if db.set_antiflood(chat_id, enabled=False):
            await update.message.reply_text("❌ **Anti-flood protection disabled!**\nBe careful with spammers~ 🥺")
            db.log_admin_action(chat_id, update.effective_user.id, "antiflood", reason="disabled")
        else:
            await update.message.reply_text("Failed to disable anti-flood! 😢")
    
    elif arg == "set":
        if len(context.args) < 4:
            await update.message.reply_text("Usage: `!antiflood set <messages> <seconds> <action>`\nExample: `!antiflood set 7 10 mute`", parse_mode='Markdown')
            return
        
        try:
            threshold = int(context.args[1])
            timeframe = int(context.args[2])
            action = context.args[3].lower()
            
            if threshold < 3 or threshold > 50:
                await update.message.reply_text("Threshold must be between 3 and 50 messages! 🥺")
                return
            
            if timeframe < 3 or timeframe > 60:
                await update.message.reply_text("Timeframe must be between 3 and 60 seconds! 🥺")
                return
            
            if action not in ['warn', 'mute', 'kick', 'ban']:
                await update.message.reply_text("Action must be: warn, mute, kick, or ban! 🥺")
                return
            
            if db.set_antiflood(chat_id, enabled=True, threshold=threshold, timeframe=timeframe, action=action):
                await update.message.reply_text(
                    f"✅ **Anti-flood configured!**\n\n"
                    f"**Threshold:** {threshold} messages in {timeframe} seconds\n"
                    f"**Action:** {action.upper()}\n\n"
                    f"Spammers beware! 🌊💪"
                )
                db.log_admin_action(chat_id, update.effective_user.id, "antiflood", reason=f"set:{threshold}/{timeframe}/{action}")
            else:
                await update.message.reply_text("Failed to configure anti-flood! 😢")
        
        except ValueError:
            await update.message.reply_text("Invalid numbers! Use: `!antiflood set <messages> <seconds> <action>`", parse_mode='Markdown')
    
    else:
        await update.message.reply_text("Invalid option! Use: `on`, `off`, or `set` 🥺")

async def setwarnaction_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set what happens when a user reaches the warn limit"""
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can configure warn actions, cutie! 🥺")
        return
    
    chat_id = update.effective_chat.id
    
    if not context.args:
        # Show current settings
        settings = db.get_mod_settings(chat_id)
        action = settings.get('warn_action', 'ban')
        duration = settings.get('warn_action_duration', 0)
        
        msg = f"⚙️ **Current Warn Action Settings**\n\n"
        msg += f"**Warn Limit:** {settings['warn_limit']} warnings\n"
        msg += f"**Action:** {action.upper()}\n"
        if action == 'mute' and duration > 0:
            msg += f"**Duration:** {duration} minutes\n"
        
        msg += f"\n**Available Actions:**\n"
        msg += f"• `!setwarnaction ban` - Ban user permanently\n"
        msg += f"• `!setwarnaction kick` - Kick user (can rejoin)\n"
        msg += f"• `!setwarnaction mute <minutes>` - Mute for X minutes\n"
        msg += f"• `!setwarnaction none` - Just count warns, no action\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        return
    
    action = context.args[0].lower()
    duration = 0
    
    # Validate action
    if action not in ['ban', 'kick', 'mute', 'none']:
        await update.message.reply_text(f"Invalid action! Use: `ban`, `kick`, `mute`, or `none` 🥺", parse_mode='Markdown')
        return
    
    # Parse duration for mute
    if action == 'mute':
        if len(context.args) < 2:
            await update.message.reply_text("Please specify mute duration! Example: `!setwarnaction mute 60` (60 minutes)", parse_mode='Markdown')
            return
        try:
            duration = int(context.args[1])
            if duration <= 0 or duration > 43200:  # Max 30 days in minutes
                await update.message.reply_text("Mute duration must be between 1 and 43200 minutes (30 days)! 🥺")
                return
        except ValueError:
            await update.message.reply_text("Invalid duration! Please use a number (in minutes) 🥺")
            return
    
    # Save settings
    if db.set_warn_action(chat_id, action, duration):
        if action == 'ban':
            await update.message.reply_text("✅ **Warn action set to BAN!**\nUsers reaching the warn limit will be permanently banned. 🔨")
        elif action == 'kick':
            await update.message.reply_text("✅ **Warn action set to KICK!**\nUsers reaching the warn limit will be kicked (but can rejoin). 👟")
        elif action == 'mute':
            await update.message.reply_text(f"✅ **Warn action set to MUTE!**\nUsers reaching the warn limit will be muted for {duration} minutes. 🤐")
        elif action == 'none':
            await update.message.reply_text("✅ **Warn action set to NONE!**\nWarnings will be counted but no automatic action will be taken. ⚠️")
        
        db.log_admin_action(chat_id, update.effective_user.id, "setwarnaction", reason=f"{action}:{duration}")
    else:
        await update.message.reply_text("Failed to save warn action settings! 😢")

async def cleanup_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodic job to delete old messages based on retention settings"""
    # This is a bit complex since retention is per-chat. 
    # For a simple implementation, we'll use a default or the smallest retention found.
    # Ideally, we'd iterate through chats, but db.py currently doesn't have a list_chats.
    # Let's assume a global cleanup for now or add a helper.
    db.delete_old_messages(30) # Default 30 days for now
    logging.info("🧹 Periodic log cleanup completed.")

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

def clean_ai_reply(reply):
    """Clean up AI response prefixes without being too aggressive."""
    if not reply:
        return reply
    # Remove [Name]: or [Name] prefix at start
    reply = re.sub(r'^\[.*?\]:?\s*', '', reply)
    # Only strip known bot-name prefixes, not arbitrary "word:" patterns
    reply = re.sub(r'^(?:Iris|iris|IRIS)\s*:\s*', '', reply)
    # Remove brackets around names in the middle of sentences
    reply = re.sub(r'\[([^\]]+)\]', r'\1', reply)
    return reply.strip()

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

        # Rotate keys per request for load balancing
        current_key = get_random_key(GROQ_API_KEY) if GROQ_API_KEY else None
        client = Groq(api_key=current_key) if current_key else groq_client
        if not client:
            raise Exception("Groq client not initialized")

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=1024,
            top_p=1,
            stop=None,
            stream=False
        )
        reply = completion.choices[0].message.content
        
        if reply:
            reply = clean_ai_reply(reply)
        return reply
    except Exception as e:
        logging.error(f"Groq API Error: {e}")
        return None

async def get_gemini_response(user_text, history, user_name=None, system_prompt=SYSTEM_PROMPT_GROUP):
    try:
        # Gemini 2.0 / New SDK Format
        # Convert history to Gemini format if needed, but the new SDK is flexible.
        # Simple content generation:
        
        # Rotate keys per request for load balancing
        current_key = get_random_key(GEMINI_API_KEY) if GEMINI_API_KEY else None
        client = genai.Client(api_key=current_key) if current_key else gemini_client
        if not client:
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

        response = client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=full_prompt
        )
        reply = response.text

        if reply:
            reply = clean_ai_reply(reply)
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
        
        if reply:
            reply = clean_ai_reply(reply)
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
        
        if reply:
            reply = clean_ai_reply(reply)
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
        
        if reply:
            reply = clean_ai_reply(reply)
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

    # Anti-flood detection (groups only, skip admins)
    if chat_type != "private" and update.effective_user and not await is_admin(update, context):
        settings = db.get_mod_settings(chat_id)
        if settings.get('antiflood_enabled', 1):
            current_time = time.time()
            threshold = settings.get('antiflood_threshold', 5)
            timeframe = settings.get('antiflood_timeframe', 5)
            action = settings.get('antiflood_action', 'mute')
            
            # Track message timestamp
            user_messages = flood_tracker[chat_id][user_id]
            user_messages.append(current_time)
            
            # Clean old timestamps
            user_messages[:] = [ts for ts in user_messages if current_time - ts <= timeframe]
            
            # Check threshold
            if len(user_messages) >= threshold:
                flood_tracker[chat_id][user_id].clear()
                
                try:
                    if action == 'warn':
                        count = db.add_warn(chat_id, user_id, "Flooding/Spam", update.effective_user.username)
                        await update.message.reply_text(f"⚠️ **{user_name}** slow down! **Warning {count}/3**")
                    elif action == 'mute':
                        until = datetime.now() + timedelta(minutes=10)
                        await context.bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False), until_date=until)
                        await update.message.reply_text(f"🤐 **{user_name}** muted for 10 minutes for flooding! 🌊")
                    elif action == 'kick':
                        await context.bot.unban_chat_member(chat_id, user_id)
                        await update.message.reply_text(f"👟 **{user_name}** kicked for flooding! 🌊")
                    elif action == 'ban':
                        await context.bot.ban_chat_member(chat_id, user_id)
                        await update.message.reply_text(f"🔨 **{user_name}** banned for severe flooding! 🌊")
                except Exception as e:
                    logging.error(f"Antiflood action failed: {e}")
                return

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
        "!pay": economy.pay, "!rich": economy.leaderboard, "!leaderboard": economy.leaderboard,
        "!warn": warn_command, "!mute": mute_command, "!unmute": unmute_command,
        "!ban": ban_command, "!unban": unban_command, "!kick": kick_command, "!purge": purge_command,
        "!filter": filter_command, "!stats": stats_command, "!lock": lock_command, "!unlock": unlock_command,
        "!privacy": privacy_command, "!export": export_command,
        "!import": import_command, "!retention": retention_command,
        "!admincheck": admincheck_command, "!setwarnaction": setwarnaction_command,
        "!antiflood": antiflood_command, "!pin": pin_command, "!unpin": unpin_command,
        "!promote": promote_command, "!demote": demote_command, "!announce": announce_command,
        "!report": report_command, "!rules": rules_command, "!setrules": setrules_command,
        "!note": note_command, "!notes": notes_command, "!savenote": savenote_command,
        "!delnote": delnote_command, "!groupstats": groupstats_command, "!qr": qr_command,
        # New fun commands
        "!coinflip": coinflip_command, "!flip": coinflip_command,
        "!wyr": wyr_command, "!wouldyourather": wyr_command,
        "!compliment": compliment_command, "!quote": quote_command,
        "!hack": hack_command, "!fight": fight_command,
        "!marry": marry_command, "!divorce": divorce_command,
        "!hug": hug_command, "!slap": slap_command, "!pat": pat_command,
        "!choose": choose_command, "!reverse": reverse_command,
        # New economy commands
        "!work": economy.work, "!rob": economy.rob, "!slots": economy.slots,
        "!shop": economy.shop, "!buy": economy.buy, "!inventory": economy.inventory,
        "!inv": economy.inventory, "!badges": economy.badges_command,
        # New moderation commands
        "!setwelcome": setwelcome_command, "!setgoodbye": setgoodbye_command,
        "!slowmode": slowmode_command,
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

# ==================== NEW FUN COMMANDS ====================

async def coinflip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Flip a coin, optionally bet coins."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    result = random.choice(["Heads", "Tails"])
    emoji = "🪙" if result == "Heads" else "🔄"

    # Optional betting
    if context.args:
        guess = context.args[0].lower()
        if guess not in ["heads", "tails", "h", "t"]:
            await context.bot.send_message(chat_id=chat_id, text="Usage: `!coinflip [heads/tails] [amount]`", parse_mode='Markdown')
            return

        guess_full = "Heads" if guess in ["heads", "h"] else "Tails"
        amount = 0
        if len(context.args) > 1:
            try:
                bal = db.get_balance(user_id)
                bet_str = context.args[1].lower()
                amount = bal if bet_str == "all" else int(bet_str)
                if amount <= 0 or amount > bal:
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ Invalid bet! Balance: {bal} 🌸")
                    return
            except ValueError:
                pass

        if amount > 0:
            if guess_full == result:
                db.update_balance(user_id, amount)
                await context.bot.send_message(chat_id=chat_id, text=f"{emoji} **{result}!** You guessed right and won **{amount}** 🌸! 🎉", parse_mode='Markdown')
            else:
                db.update_balance(user_id, -amount)
                await context.bot.send_message(chat_id=chat_id, text=f"{emoji} **{result}!** Wrong guess~ Lost **{amount}** 🌸 😢", parse_mode='Markdown')
            return

    await context.bot.send_message(chat_id=chat_id, text=f"{emoji} **{result}!**", parse_mode='Markdown')

async def wyr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Would You Rather — AI generated."""
    chat_id = update.effective_chat.id
    response = await get_ai_response(chat_id, "Give me a fun, creative 'Would You Rather' question with two options. Format: Would you rather A or B? Keep it clean and fun.", user_name="GameMaster", chat_type="game")
    await context.bot.send_message(chat_id=chat_id, text=f"🤔 **Would You Rather?**\n\n{response}", parse_mode='Markdown')

async def compliment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give someone a cute compliment."""
    chat_id = update.effective_chat.id

    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.first_name
    elif context.args:
        target = " ".join(context.args)
    else:
        target = update.effective_user.first_name

    compliments = [
        f"{target}, you're literally the main character and everyone knows it~ 👑✨",
        f"If {target} was a star, they'd be the sun because everything revolves around them~ ☀️💖",
        f"{target} is the type of person who makes the world better just by existing~ 🌸",
        f"Honestly? {target}'s vibe is immaculate. Like, chef's kiss~ 🤌✨",
        f"{target} walked in and suddenly everything got 10x better~ 💕",
        f"If kindness was a person, it would be {target}~ 🥹💖",
        f"{target} has the energy of a warm hug on a cold day~ 🤗✨",
        f"The world doesn't deserve {target}, but we're so lucky to have them~ 🌟",
        f"{target}'s smile could literally power a whole city~ ⚡💖",
        f"I genuinely believe {target} was sprinkled with extra magic at birth~ ✨🧚",
        f"{target} is proof that angels walk among us~ 👼💕",
        f"Being around {target} is like finding a four-leaf clover every single day~ 🍀💖",
    ]

    await context.bot.send_message(chat_id=chat_id, text=f"💖 {random.choice(compliments)}")

async def quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Random inspirational/funny quote."""
    chat_id = update.effective_chat.id
    quotes = [
        ("The only way to do great work is to love what you do.", "Steve Jobs"),
        ("Be yourself; everyone else is already taken.", "Oscar Wilde"),
        ("In three words I can sum up everything I've learned about life: it goes on.", "Robert Frost"),
        ("The future belongs to those who believe in the beauty of their dreams.", "Eleanor Roosevelt"),
        ("It is during our darkest moments that we must focus to see the light.", "Aristotle"),
        ("Do what you can, with what you have, where you are.", "Theodore Roosevelt"),
        ("Believe you can and you're halfway there.", "Theodore Roosevelt"),
        ("The best time to plant a tree was 20 years ago. The second best time is now.", "Chinese Proverb"),
        ("You miss 100% of the shots you don't take.", "Wayne Gretzky"),
        ("Life is what happens when you're busy making other plans.", "John Lennon"),
        ("Stay hungry, stay foolish.", "Steve Jobs"),
        ("It always seems impossible until it's done.", "Nelson Mandela"),
        ("Not all those who wander are lost.", "J.R.R. Tolkien"),
        ("The only limit to our realization of tomorrow is our doubts of today.", "Franklin D. Roosevelt"),
        ("Dream big. Start small. Act now.", "Robin Sharma"),
    ]
    text, author = random.choice(quotes)
    await context.bot.send_message(chat_id=chat_id, text=f"💬 _{text}_\n\n— **{author}** ✨", parse_mode='Markdown')

async def hack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fake 'hacking' someone with funny stages."""
    chat_id = update.effective_chat.id

    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.first_name
    elif context.args:
        target = " ".join(context.args)
    else:
        target = update.effective_user.first_name

    stages = [
        f"🔓 Hacking {target}...",
        "📡 Connecting to mainframe... [██░░░░░░░░] 20%",
        "🔍 Bypassing firewall... [████░░░░░░] 40%",
        "💾 Downloading browser history... [██████░░░░] 60%",
        "📂 Reading messages... [████████░░] 80%",
        "🔐 Cracking password... [██████████] 100%",
    ]

    msg = await context.bot.send_message(chat_id=chat_id, text=stages[0])

    for stage in stages[1:]:
        await asyncio.sleep(1.2)
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=stage)
        except Exception:
            pass

    await asyncio.sleep(1)

    findings = [
        f"browser history: 99% cat videos 🐱",
        f"most used emoji: 🥺",
        f"last Google search: 'how to be cool'",
        f"secret playlist: 100% Taylor Swift 🎵",
        f"screen time: 14 hours today 📱",
        f"Discord status: invisible but online 👀",
        f"Crush's name found: [REDACTED] 😳",
        f"most visited site: reddit.com/r/memes 💀",
    ]

    final = f"✅ **Hack complete on {target}!**\n\n📋 **Findings:**\n• {random.choice(findings)}\n• {random.choice(findings)}\n• Password: ••••••• (jk~ 😂)\n\n_This was totally a joke~ 💖_"

    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=final, parse_mode='Markdown')
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=final, parse_mode='Markdown')

async def fight_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fight someone with random outcomes."""
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name

    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.first_name
    elif context.args:
        target = " ".join(context.args)
    else:
        await context.bot.send_message(chat_id=chat_id, text="Reply to someone or use `!fight <name>` to fight them! ⚔️", parse_mode='Markdown')
        return

    attacks = [
        (f"🗡️ {user_name} slashed {target} with a diamond sword!", 30),
        (f"🔥 {user_name} used Fireball! It's super effective!", 40),
        (f"👊 {user_name} landed a critical punch on {target}!", 25),
        (f"🏹 {user_name} sniped {target} from across the map!", 35),
        (f"💥 {user_name} used Kamehameha on {target}!", 50),
        (f"🪃 {user_name} threw a boomerang at {target}!", 20),
        (f"🐍 {user_name} sent a snake at {target}!", 15),
        (f"⚡ {user_name} used Thunder Shock on {target}!", 45),
    ]

    defenses = [
        (f"🛡️ {target} blocked with a shield!", 20),
        (f"🏃 {target} dodged like a ninja!", 30),
        (f"💨 {target} used Smoke Bomb and vanished!", 25),
        (f"🪨 {target} hid behind a rock!", 10),
        (f"🧊 {target} froze {user_name} with an ice spell!", 35),
    ]

    counters = [
        f"💀 {target} pulled out an UNO reverse card!",
        f"😎 {target} reflected the attack back!",
        f"🤺 {target} parried perfectly!",
    ]

    user_hp = 100
    target_hp = 100
    log = f"⚔️ **{user_name} vs {target}** ⚔️\n\n"

    for _round in range(3):
        # User attacks
        atk_text, atk_dmg = random.choice(attacks)
        # Target defends sometimes
        if random.random() < 0.3:
            def_text, def_block = random.choice(defenses)
            atk_dmg = max(0, atk_dmg - def_block)
            log += f"{atk_text}\n{def_text} (-{def_block} blocked)\n"
        else:
            log += f"{atk_text}\n"
        target_hp -= atk_dmg

        # Counter chance
        if random.random() < 0.15:
            counter_dmg = random.randint(10, 30)
            log += f"{random.choice(counters)} (-{counter_dmg} HP to {user_name})\n"
            user_hp -= counter_dmg

        log += "\n"

    # Determine winner
    if target_hp <= user_hp:
        log += f"🏆 **{user_name} WINS!** 🎉\n"
        log += f"_{user_name}: {max(0, user_hp)} HP | {target}: {max(0, target_hp)} HP_"
        # Badge
        if update.effective_user:
            db.award_badge(update.effective_user.id, "Fighter")
    else:
        log += f"🏆 **{target} WINS!** 🎉\n"
        log += f"_{user_name}: {max(0, user_hp)} HP | {target}: {max(0, target_hp)} HP_"

    await context.bot.send_message(chat_id=chat_id, text=log, parse_mode='Markdown')

async def marry_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Marry someone (reply to them)."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name

    if not update.message.reply_to_message or not update.message.reply_to_message.from_user:
        await context.bot.send_message(chat_id=chat_id, text="Reply to someone to propose to them! 💍", parse_mode='Markdown')
        return

    target = update.message.reply_to_message.from_user
    if target.id == user_id:
        await context.bot.send_message(chat_id=chat_id, text="You can't marry yourself, silly! 😭")
        return
    if target.is_bot:
        await context.bot.send_message(chat_id=chat_id, text="You can't marry a bot! ...unless? 🤖💕")
        return

    # Check if either is already married
    existing1 = db.get_partner(user_id)
    existing2 = db.get_partner(target.id)
    if existing1:
        await context.bot.send_message(chat_id=chat_id, text="You're already married! Use `!divorce` first~ 💔", parse_mode='Markdown')
        return
    if existing2:
        await context.bot.send_message(chat_id=chat_id, text=f"{target.first_name} is already taken! 💔")
        return

    if db.marry(user_id, target.id):
        db.award_badge(user_id, "Married")
        db.award_badge(target.id, "Married")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"💒 **{user_name} and {target.first_name} are now married!!** 💍💕\n\nCongrats to the happy couple~ 🎉🥂✨",
            parse_mode='Markdown'
        )
    else:
        await context.bot.send_message(chat_id=chat_id, text="Something went wrong with the wedding! 😢")

async def divorce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Divorce your partner."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    partner_id = db.get_partner(user_id)
    if not partner_id:
        await context.bot.send_message(chat_id=chat_id, text="You're not married to anyone! 🥺")
        return

    if db.divorce(user_id, partner_id):
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"💔 **{update.effective_user.first_name}** filed for divorce... It's over. 😢\n\n_Sometimes love just isn't enough~_",
            parse_mode='Markdown'
        )
    else:
        await context.bot.send_message(chat_id=chat_id, text="Couldn't process the divorce! 😢")

async def action_command(update: Update, context: ContextTypes.DEFAULT_TYPE, action_type="hug"):
    """Generic action command (hug/slap/pat)."""
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name

    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user.first_name
    elif context.args:
        target = " ".join(context.args)
    else:
        target = "themselves"

    actions = {
        "hug": {
            "emoji": "🤗",
            "messages": [
                f"**{user_name}** gives **{target}** a warm hug~ 🤗💖",
                f"**{user_name}** hugged **{target}** tightly! So cute~ 🥹💕",
                f"**{user_name}** wraps **{target}** in a big bear hug! 🧸💖",
            ]
        },
        "slap": {
            "emoji": "👋",
            "messages": [
                f"**{user_name}** slapped **{target}**! 👋💥",
                f"**{user_name}** gave **{target}** a dramatic slap! 😤✋",
                f"**{user_name}** bonked **{target}** on the head! 🔨",
            ]
        },
        "pat": {
            "emoji": "🥰",
            "messages": [
                f"**{user_name}** pats **{target}** on the head~ 🥰✨",
                f"**{user_name}** gave **{target}** gentle headpats~ 💖",
                f"*pat pat pat* Good {target}~ 🥹💕",
            ]
        },
    }

    data = actions.get(action_type, actions["hug"])
    await context.bot.send_message(chat_id=chat_id, text=random.choice(data["messages"]), parse_mode='Markdown')

async def hug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await action_command(update, context, "hug")

async def slap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await action_command(update, context, "slap")

async def pat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await action_command(update, context, "pat")

async def choose_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pick between options (separated by 'or')."""
    chat_id = update.effective_chat.id

    if not context.args:
        await context.bot.send_message(chat_id=chat_id, text="Usage: `!choose pizza or burger or sushi`", parse_mode='Markdown')
        return

    text = " ".join(context.args)
    options = [o.strip() for o in text.split(" or ") if o.strip()]

    if len(options) < 2:
        # Try comma separation
        options = [o.strip() for o in text.split(",") if o.strip()]

    if len(options) < 2:
        await context.bot.send_message(chat_id=chat_id, text="Give me at least 2 options! Separate with `or` or `,`", parse_mode='Markdown')
        return

    choice = random.choice(options)
    await context.bot.send_message(chat_id=chat_id, text=f"🤔 Hmm... I choose **{choice}**! ✨", parse_mode='Markdown')

async def reverse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reverse text."""
    chat_id = update.effective_chat.id

    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    elif context.args:
        text = " ".join(context.args)
    else:
        await context.bot.send_message(chat_id=chat_id, text="Reply to a message or do `!reverse your text here`~", parse_mode='Markdown')
        return

    reversed_text = text[::-1]
    await context.bot.send_message(chat_id=chat_id, text=f"🔄 {reversed_text}")

async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a QR code from text"""
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `!qr <text or URL>`\nExample: `!qr https://example.com`",
            parse_mode='Markdown'
        )
        return

    text = " ".join(context.args)
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)

    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=bio,
        caption=f"Here's your QR code~ 💖"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User help - General commands for everyone"""
    help_text = """
✨ **Iris - Your Cute AI Friend!** ✨

Hii~ here's everything I can do! 💖

🤖 **Chatting with Me**
- Mention `@Iris` or reply to my messages to chat!
- In DMs, I'm always listening~ 💕
- `!reset` - Clear conversation memory
- `!roleplay <scenario>` - Act as any character!
- `!normal` - Return to normal Iris

🎉 **Fun Commands**
- `!meme` - Random meme 💀
- `!roast [@user]` - Playful roast 🔥
- `!ship <name1> <name2>` - Ship people 💘
- `!8ball <question>` - Magic 8-ball 🎱
- `!uwu <text>` - UwUify text~
- `!rate <thing>` - Rate out of 10
- `!vibe [@user]` - Vibe check ✨
- `!pp` / `!howgay` / `!simprate` - Classic memes 💀
- `!coinflip [heads/tails] [bet]` - Flip a coin 🪙
- `!compliment [@user]` - Give compliments 💖
- `!quote` - Inspirational quote 💬
- `!hack [@user]` - Fake hack someone 🔓
- `!fight [@user]` - Fight someone ⚔️
- `!hug` / `!slap` / `!pat` - Actions 🤗
- `!choose A or B` - Pick for you 🤔
- `!reverse <text>` - Reverse text 🔄
- `!wyr` - Would You Rather 🤔

💍 **Social**
- `!marry` - Propose (reply to someone) 💒
- `!divorce` - End your marriage 💔

💰 **Economy System**
- `!balance` / `!bal` - Check wallet 🌸
- `!daily` - Daily reward (500 coins)
- `!work` - Work a job (10m cooldown) 💼
- `!beg` - Beg for coins (1m cooldown)
- `!gamble <amount>` - Double or nothing 🎰
- `!slots <amount>` - Slot machine 🎰
- `!coinflip <h/t> <amount>` - Bet on a flip 🪙
- `!rob` - Rob someone (reply) 🦹
- `!pay <amount>` - Pay someone (reply) 💸
- `!rich` / `!leaderboard` - Top users 👑

🏪 **Shop & Items**
- `!shop` - View the item shop
- `!buy <item>` - Purchase an item
- `!inventory` / `!inv` - View your items 🎒
- `!badges` - View your badges 🏅

🎲 **Mini Games**
- `!truth` - Truth question 👀
- `!dare` - Dare challenge 🔥
- `!trivia` - Trivia quiz 🧠

⚙️ **Utilities**
- `!help` - This message
- `!donate` - Support the server 💖
- `!qr <text>` - Generate QR code
- `!rules` - View group rules 📜
- `!note <name>` / `!notes` - Saved notes 📝
- `!groupstats` - Group statistics 📊
- `!report` - Report to admins 🚨

🛡️ **For Admins** - Type `!mhelp`

Have fun~ 🌸💖
"""
    await context.bot.send_message(chat_id=update.effective_chat.id, text=help_text, parse_mode='Markdown')

async def mhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Moderation help - Admin commands only"""
    # Show full help for admins, basic info for users
    is_user_admin = await is_admin(update, context)
    
    if not is_user_admin:
        await update.message.reply_text(
            "🛡️ **Moderation Commands** 🛡️\n\n"
            "These commands are for admins only!\n"
            "If you're an admin, you'll see the full list when you use this command~ 💕"
        )
        return
    
    help_text = """
🛡️ **Iris Moderation Guide** 🛡️

**USER MANAGEMENT**
━━━━━━━━━━━━━━━━━
⚠️ `!warn [@user] [reason]` - Warn a user
   • Reason shortcuts: s (spam), a (ads), n (nsfw), u (unkind), r (raid)
   • Example: `!warn @user s` or `!warn @user Flooding chat`

🤐 `!mute [@user] [duration]` - Mute a user
   • Duration: 10m, 1h, 2d (default: 1h)
   • Example: `!mute @user 30m`

✨ `!unmute [@user]` - Unmute a user

🔨 `!ban [@user]` - Permanently ban a user

👟 `!kick [@user]` - Kick user (can rejoin)

🔓 `!unban [@user or ID]` - Unban a user
   • Can use username or user ID

🧹 `!purge` - Delete messages (reply to start message)

**WARN SYSTEM CONFIG**
━━━━━━━━━━━━━━━━━
⚙️ `!setwarnaction [action]` - Configure warn limit action
   • `!setwarnaction` - View current settings
   • `!setwarnaction ban` - Ban on warn limit
   • `!setwarnaction kick` - Kick on warn limit
   • `!setwarnaction mute 60` - Mute for 60 mins
   • `!setwarnaction none` - Just count, no action

**CHAT CONTROLS**
━━━━━━━━━━━━━━━━━
🔒 `!lock [duration:Xm/h/d]` - Lock chat (admins only speak)
   • Example: `!lock duration:30m`

🔓 `!unlock` - Unlock chat

🚫 `!filter <add/remove/list> [word]` - Word filter
   • `!filter add badword` - Block a word
   • `!filter remove badword` - Unblock
   • `!filter list` - Show blocked words

**ADMIN TOOLS**
━━━━━━━━━━━━━━━━━
📊 `!stats` - View admin action summary

🏥 `!admincheck` - Check inactive admins

📌 `!pin [silent]` - Pin a message (reply to it)

📌 `!unpin [all]` - Unpin message or all pins

👑 `!promote [@user] [title]` - Promote to admin

👤 `!demote [@user]` - Demote admin

📢 `!announce <message>` - Send announcement

📊 `!groupstats` - Group statistics & insights

🔒 `!privacy <on/off>` - Mask usernames in logs

🧹 `!retention <days>` - Auto-delete old logs

📦 `!export` / `!import` - Backup/Restore settings

**RULES & NOTES**
━━━━━━━━━━━━━━━━━
📜 `!rules` - View group rules

📜 `!setrules <text>` - Set group rules (admin)

📝 `!note <name>` - View a saved note

📝 `!notes` - List all notes

📝 `!savenote <name> <content>` - Save note (admin)

🗑️ `!delnote <name>` - Delete note (admin)

**ANTI-FLOOD**
━━━━━━━━━━━━━━━━━
🌊 `!antiflood` - View/configure flood protection
   • `!antiflood on/off` - Enable/disable
   • `!antiflood set <msgs> <secs> <action>` - Configure
   • Actions: warn, mute, kick, ban

**WELCOME & GOODBYE**
━━━━━━━━━━━━━━━━━
👋 `!setwelcome <msg>` - Set welcome message
   • Placeholders: `{name}`, `{group}`, `{count}`
   • `!setwelcome off` - Disable

👋 `!setgoodbye <msg>` - Set goodbye message
   • Placeholders: `{name}`, `{group}`
   • `!setgoodbye off` - Disable

🐌 `!slowmode <seconds>` - Set chat slowmode
   • `!slowmode off` - Disable

**TIPS & BEST PRACTICES**
━━━━━━━━━━━━━━━━━
✅ Always set warn action: `!setwarnaction ban` or `mute 120`
✅ Use word filters for common spam/abuse
✅ Check admin activity weekly with `!admincheck`
✅ Export settings regularly as backup
✅ Set welcome messages for new members
✅ Set retention to manage database size

Need help? Tag an owner or check `!help` for user commands! 💕
"""
    await context.bot.send_message(chat_id=update.effective_chat.id, text=help_text, parse_mode='Markdown')

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler to log unhandled exceptions."""
    logging.error(f"Unhandled exception: {context.error}", exc_info=context.error)
    if update and hasattr(update, 'effective_chat') and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Oopsie~ something went wrong! 🥺 Try again later~ 💖"
            )
        except Exception:
            pass

async def init_telethon():
    """Initialize Telethon client for username lookups"""
    global telethon_client
    
    if TELEGRAM_API_ID and TELEGRAM_API_HASH:
        try:
            telethon_client = TelegramClient('iris_session', int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await telethon_client.start()
            print("✅ Telethon client initialized for advanced username lookups!")
        except Exception as e:
            logging.warning(f"⚠️ Telethon initialization failed: {e}")
            logging.warning("Username lookups will fall back to bot API only.")
            telethon_client = None
    else:
        logging.info("ℹ️ Telethon credentials not provided. Username lookups will use bot API only.")

if __name__ == '__main__':
    # Initialize Database
    db.init_db()

    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env file.")
        print("Please copy .env.example to .env and fill in your tokens.")
    else:
        # Initialize Telethon for username lookups
        # Must use new_event_loop + set, NOT asyncio.run(), because run() closes
        # the loop afterward and run_polling() needs an active loop.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(init_telethon())
        
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
        application.add_handler(CommandHandler('leaderboard', economy.leaderboard))
        application.add_handler(CommandHandler('work', economy.work))
        application.add_handler(CommandHandler('rob', economy.rob))
        application.add_handler(CommandHandler('slots', economy.slots))
        application.add_handler(CommandHandler('shop', economy.shop))
        application.add_handler(CommandHandler('buy', economy.buy))
        application.add_handler(CommandHandler('inventory', economy.inventory))
        application.add_handler(CommandHandler('inv', economy.inventory))
        application.add_handler(CommandHandler('badges', economy.badges_command))

        # Utility Handlers
        application.add_handler(CommandHandler('qr', qr_command))

        # New Fun Command Handlers
        application.add_handler(CommandHandler('coinflip', coinflip_command))
        application.add_handler(CommandHandler('flip', coinflip_command))
        application.add_handler(CommandHandler('wyr', wyr_command))
        application.add_handler(CommandHandler('wouldyourather', wyr_command))
        application.add_handler(CommandHandler('compliment', compliment_command))
        application.add_handler(CommandHandler('quote', quote_command))
        application.add_handler(CommandHandler('hack', hack_command))
        application.add_handler(CommandHandler('fight', fight_command))
        application.add_handler(CommandHandler('marry', marry_command))
        application.add_handler(CommandHandler('divorce', divorce_command))
        application.add_handler(CommandHandler('hug', hug_command))
        application.add_handler(CommandHandler('slap', slap_command))
        application.add_handler(CommandHandler('pat', pat_command))
        application.add_handler(CommandHandler('choose', choose_command))
        application.add_handler(CommandHandler('reverse', reverse_command))

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
        application.add_handler(CommandHandler('setwarnaction', setwarnaction_command))
        application.add_handler(CommandHandler('antiflood', antiflood_command))
        application.add_handler(CommandHandler('pin', pin_command))
        application.add_handler(CommandHandler('unpin', unpin_command))
        application.add_handler(CommandHandler('promote', promote_command))
        application.add_handler(CommandHandler('demote', demote_command))
        application.add_handler(CommandHandler('announce', announce_command))
        application.add_handler(CommandHandler('report', report_command))
        application.add_handler(CommandHandler('rules', rules_command))
        application.add_handler(CommandHandler('setrules', setrules_command))
        application.add_handler(CommandHandler('note', note_command))
        application.add_handler(CommandHandler('notes', notes_command))
        application.add_handler(CommandHandler('savenote', savenote_command))
        application.add_handler(CommandHandler('delnote', delnote_command))
        application.add_handler(CommandHandler('groupstats', groupstats_command))
        application.add_handler(CommandHandler('setwelcome', setwelcome_command))
        application.add_handler(CommandHandler('setgoodbye', setgoodbye_command))
        application.add_handler(CommandHandler('slowmode', slowmode_command))

        # Welcome/Goodbye event handlers
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_handler))
        application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_handler))

        # Schedule periodic cleanup (every 24 hours) if JobQueue is available
        if application.job_queue:
            application.job_queue.run_repeating(cleanup_job, interval=86400, first=10)
        else:
            logging.warning("⚠️ JobQueue not available. Scheduled tasks (like log cleanup) will not run.")

        application.add_handler(start_handler)
        application.add_handler(msg_handler)
        application.add_handler(edit_handler)

        # Global error handler
        application.add_error_handler(error_handler)
        
        providers_str = ", ".join(ENABLED_PROVIDERS) if ENABLED_PROVIDERS else "NO AI BRAIN"
        print(f"Iris is waking up with {providers_str}... ✨ Press Ctrl+C to stop.")
        application.run_polling()
