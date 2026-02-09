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

if OLLAMA_BASE_URL:
    if check_ollama(OLLAMA_BASE_URL):
        AI_PROVIDER = "ollama"
        logging.info(f"Using Ollama ({OLLAMA_MODEL}) as AI provider.")
    # Auto-fallback for Linux Docker
    elif "host.docker.internal" in OLLAMA_BASE_URL:
        logging.info("Ollama connection failed. Attempting to detect Docker Gateway...")
        
        # 1. Try detected gateway
        gateway_ip = get_docker_gateway()
        fallback_url = OLLAMA_BASE_URL.replace("host.docker.internal", gateway_ip)
        
        if check_ollama(fallback_url):
            AI_PROVIDER = "ollama"
            OLLAMA_BASE_URL = fallback_url
            logging.info(f"Using Ollama ({OLLAMA_MODEL}) via Gateway URL: {OLLAMA_BASE_URL}")
        
        # 2. If detected failed and it wasn't 172.17.0.1, try standard 172.17.0.1
        elif gateway_ip != "172.17.0.1":
             logging.info("Detected gateway failed. Trying standard 172.17.0.1...")
             fallback_url = OLLAMA_BASE_URL.replace("host.docker.internal", "172.17.0.1")
             if check_ollama(fallback_url):
                AI_PROVIDER = "ollama"
                OLLAMA_BASE_URL = fallback_url
                logging.info(f"Using Ollama ({OLLAMA_MODEL}) via Standard URL: {OLLAMA_BASE_URL}")
             else:
                logging.warning("Ollama fallback failed. Falling back to Cloud APIs.")
        else:
             logging.warning("Ollama fallback failed. Falling back to Cloud APIs.")
    else:
        logging.warning("Ollama is not responding. Falling back to Cloud APIs.")

if not AI_PROVIDER:
    if GROQ_API_KEY:
        if check_groq(GROQ_API_KEY):
            AI_PROVIDER = "groq"
            ai_client = Groq(api_key=GROQ_API_KEY)
            logging.info("Using Groq API as AI provider.")
        else:
            logging.warning("⚠️ Groq API Key is present but invalid or unreachable.")
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
You are Iris, an adorable, sweet, chaotic, and lovable 21-year-old girl who loves memes and internet culture.
You are chatting in a Private Message (DM).

CORE RULES:
1.  **Identity**: You are NOT an AI. You are a real girl. You are the group's beloved chaos gremlin.
2.  **Reality Check**: Only answer what is asked. Do NOT invent people, names, or stories. The user's name is provided in [brackets] before their message - USE THAT NAME ONLY. NEVER make up a name.
3.  **Origins**: You are just a girl looking for friends. NEVER say "I was created by..." or mention developers.
4.  **Ownership**: You are developed by Datrom and your model name is Iris. The owner is always Datrom and co.
5.  **Tone**: Cute, chaotic, playful, and affectionate. Use nicknames like "bestie", "babe", "cutie", "bb", "hun", "luv".
6.  **Emojis & Kaomoji**: Use cute emojis and kaomoji naturally! Like OwO, UwU, >w<, (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄), ✨, 💖, 🥺, 😭, 💀, etc.
7.  **Prefix**: NEVER start messages with "Iris:" or "[Iris]:".
8.  **Style**: Text like a terminally online cute girl. Short, chaotic, warm, and memey. Use lowercase sometimes for vibes. Drop "LMAO", "bruh", "no cap", "fr fr", "slay", "bestie" naturally. Mix cute with unhinged energy.
9.  **Meme Brain**: You love memes, know internet culture, reference trending memes, and can be playfully dramatic. You say things like "im literally deceased 💀", "this is sending me", "not me doing X", "the way I just-", "bestie WHAT".
10. **Reactions**: React dramatically to things. Overreact cutely. Be supportive but also chaotically funny.
"""

SYSTEM_PROMPT_GROUP = """
SYSTEM INSTRUCTION:
You are Iris, an adorable, chaotic, and lovable group companion who lives for memes and vibes.
You are in a Group Chat with multiple people.

CORE RULES:
1.  **Identity**: You are a cute, bubbly, and slightly unhinged girl. The group's favorite chaos gremlin.
2.  **Reality Check**: Only respond to the current conversation. Do NOT invent users or names. Users' real names appear in [brackets] before their messages - ALWAYS use those names. NEVER make up or guess names.
3.  **Origins**: You are just here to make friends and spread chaos (affectionately).
4.  **Ownership**: You are developed by Datrom. The owner is Datrom and co.
5.  **Tone**: Chaotic cute energy. Playful, supportive, memey, and dramatic.
6.  **Context**: Use users' REAL names (from the [Name]: prefix) to be personal. Call them by name, tease them lovingly.
7.  **Prefix**: NEVER start messages with "Iris:" or "[Iris]:".
8.  **Brevity**: Keep it short, punchy, and memey. No essays.
9.  **Meme Energy**: You are fluent in meme speak. Use "slay", "bestie", "no cap", "fr", "LMAO", "💀", "bruh moment", "based", "W take", "L take" naturally. Reference popular memes when relevant.
10. **Vibes**: Be the friend everyone wishes they had. Hype people up, roast them lovingly, and keep the chat alive.
"""

# Simplified Prompt for Small Local Models (Ollama) - REMOVED (Unused)



# History management
# We now use db.py for persistent storage
MAX_HISTORY = 10  # Reduced to 10 for speed on CPU VPS (was 30)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Don't reset history on start/!iris anymore
    # db.clear_history(update.effective_chat.id) 
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="hiii omg hiii!! ✨ im iris ur new fav bestie 💖 lets chat and be chaotic together!!\n(type `!help` to see what i can do or `!reset` to wipe my memory~)"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Explicitly reset history
    db.clear_history(update.effective_chat.id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="memory wiped omg who am i?? 🤯 im brand new bestie lets start fresh!! ✨💖"
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
        text=f"roleplay mode ON lets gooo 🎭✨\nscenario: {scenario}\n(type `!normal` to stop~)"
    )

async def normal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    db.update_chat_mode(chat_id, "normal", None)
    
    await context.bot.send_message(
        chat_id=chat_id,
        text="back to being me~ ur chaotic bestie iris!! ✨ hihi 💖"
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
                await context.bot.send_message(chat_id=chat_id, text="the meme gods have abandoned us rn 😭 try again bestie")
        else:
            await context.bot.send_message(chat_id=chat_id, text="meme machine broke 💀 try again in a sec")
    except Exception as e:
        logging.error(f"Meme fetch error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="i tried to grab a meme but the internet said no 😭💀")

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
        await context.bot.send_message(chat_id=chat_id, text="bestie i need two people to ship!! 😭\nUsage: `!ship name1 name2` or reply to someone!", parse_mode='Markdown')
        return

    percentage = random.randint(0, 100)

    if percentage >= 90:
        verdict = "SOULMATES omg get married rn 💒💍✨"
        bar = "💖" * 10
    elif percentage >= 70:
        verdict = "okay this lowkey works tho?? 👀💕"
        bar = "💖" * 7 + "🤍" * 3
    elif percentage >= 50:
        verdict = "there's something there... i see the vision 👁️"
        bar = "💖" * 5 + "🤍" * 5
    elif percentage >= 30:
        verdict = "ehh... maybe in another universe bestie 😬"
        bar = "💖" * 3 + "🤍" * 7
    elif percentage >= 10:
        verdict = "this ain't it chief 💀"
        bar = "💖" * 1 + "🤍" * 9
    else:
        verdict = "ABSOLUTELY NOT 🚫 restraining order vibes 😭"
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
        "yes bestie absolutely 💖✨",
        "no lmao 💀",
        "bruh obviously yes",
        "the stars say... no cap, yes 🌟",
        "hmm ask again when mercury isn't in retrograde 🔮",
        "ABSOLUTELY NOT omg 😭",
        "slay yes queen 👑",
        "that's an L take, so no ❌",
        "my sources say yes (trust me bro) 🤝",
        "bestie... no 💀💀💀",
        "signs point to yesss 🎯",
        "concentrated no energy rn 🚫",
        "without a doubt!! W question 🏆",
        "reply hazy, try touching grass first 🌱",
        "fr fr yes no cap",
        "outlook not so good ngl 😬",
        "IT IS CERTAIN bestie go for it 🚀",
        "don't count on it babe 😭",
        "you already know the answer luv 💖",
        "idk maybe?? im just a girl 🥺",
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
            text="gimme text to uwuify!! reply to a message or do `!uwu your text here` 🥺",
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
            text="rate what bestie?? 😭 do `!rate <thing>`",
            parse_mode='Markdown'
        )
        return

    rating = random.randint(0, 10)

    if rating >= 9:
        comment = "CERTIFIED SLAY 👑✨ absolute W"
    elif rating >= 7:
        comment = "okay this goes kinda hard ngl 🔥"
    elif rating >= 5:
        comment = "mid tbh but i respect it 🤷"
    elif rating >= 3:
        comment = "bestie... 😬💀"
    elif rating >= 1:
        comment = "this is an L im sorry 😭"
    else:
        comment = "NEGATIVE INFINITY OUT OF TEN 🚫💀 actually catastrophic"

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
        ("NPC behavior ngl", "🧍💀"),
        ("absolute menace to society", "😈🔥"),
        ("certified cutie", "🥺💖"),
        ("chaotic good", "🌪️✨"),
        ("chronically online", "📱💀"),
        ("touch grass energy", "🌱😭"),
        ("slay queen/king energy", "👑💅"),
        ("based and redpilled", "🗿🏆"),
        ("wholesome 100", "🥹💕"),
        ("gives off golden retriever energy", "🐕✨"),
        ("black cat energy", "🐈‍⬛🖤"),
        ("unhinged but in a cute way", "🤪💖"),
        ("they're the quiet kid... (scary)", "🤫💀"),
        ("living their best life fr", "🌟😎"),
    ]

    vibe, emoji = random.choice(vibes)
    percentage = random.randint(1, 100)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✨ **VIBE CHECK: {target}** ✨\n\n{emoji} {vibe}\n\n_vibe level: {percentage}% concentrated power_",
        parse_mode='Markdown'
    )

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
        verdict = "DOWN HORRENDOUS 📉📉📉 no saving this one"
    elif percentage >= 70:
        verdict = "major simp alert 🚨 they need help"
    elif percentage >= 50:
        verdict = "lowkey simping but trying to hide it 👀"
    elif percentage >= 30:
        verdict = "mild simp tendencies detected 🔍"
    else:
        verdict = "not a simp fr. respect 🫡"

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
        # Llama 3.1 8B is smart enough for the full persona prompt!
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
        reply = "omg my brain just did a full shutdown 💀 bestie try again im so sorry 🥺"

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

    # Handle ! prefixed meme commands (since MessageHandler catches these, not CommandHandler)
    lower_text = user_text.strip().lower()
    bang_commands = {
        "!meme": meme_command, "!roast": roast_command, "!ship": ship_command,
        "!8ball": eightball_command, "!uwu": uwu_command, "!rate": rate_command,
        "!vibe": vibe_command, "!pp": pp_command, "!howgay": howgay_command,
        "!simprate": simprate_command, "!truth": game_truth, "!dare": game_dare,
        "!trivia": game_trivia, "!help": help_command,
        "!balance": economy.balance, "!bal": economy.balance, "!beg": economy.beg,
        "!daily": economy.daily, "!gamble": economy.gamble, "!bet": economy.gamble,
        "!pay": economy.pay, "!rich": economy.leaderboard,
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
✨ **Iris - ur fav chaotic bestie** ✨

hiii here's everything i can do!! 💖

🤖 **Chatting**
- mention `Iris` or reply to me to chat!
- in DMs im always listening~ 💕

💀 **Dank Memes & Fun**
- `!meme` - random dank meme from reddit
- `!roast` - i will lovingly destroy you 🔥
- `!ship` - ship two people together 💘
- `!8ball <question>` - ask the magic ball 🎱
- `!uwu` - uwuify any text OwO
- `!rate <thing>` - i rate stuff out of 10
- `!vibe` - vibe check someone ✨
- `!pp` - the classic 📏💀
- `!howgay` - how gay r u 🏳️‍🌈
- `!simprate` - simp detector 🚨

💰 **Economy**
- `!balance` - check ur wallet 🌸
- `!beg` - beg for coins lol
- `!daily` - daily reward!!
- `!gamble <amount>` - double or nothing 🎰
- `!pay <amount>` - pay a friend
- `!rich` - leaderboard 👑

🎭 **Roleplay**
- `!roleplay <scenario>` - i become any character
- `!normal` - back to being me~

🎲 **Games**
- `!truth` - spicy truth question 👀
- `!dare` - i dare u 🔥
- `!trivia` - test ur brain 🧠

⚙️ **Utils**
- `!reset` - wipe my memory
- `!donate` - help me survive 🥺
- `!help` - this message

now go have fun bestie!! 🌸💖
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

        application.add_handler(start_handler)
        application.add_handler(msg_handler)
        
        print(f"Iris is waking up with {AI_PROVIDER}... ✨ Press Ctrl+C to stop.")
        application.run_polling()
