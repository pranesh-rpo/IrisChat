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

# 2. Configure Groq
if GROQ_API_KEY:
    if check_groq(GROQ_API_KEY):
        groq_client = Groq(api_key=GROQ_API_KEY)
        ENABLED_PROVIDERS.append("groq")
        logging.info("✅ Groq API is available as backup.")
    else:
        logging.warning("⚠️ Groq API Key is present but invalid or unreachable.")

# 3. Configure Gemini
if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        ENABLED_PROVIDERS.append("gemini")
        logging.info("✅ Gemini API is available as backup.")
    except Exception as e:
        logging.warning(f"⚠️ Gemini Setup Failed: {e}")

# 4. Configure Mistral
if MISTRAL_API_KEY:
    try:
        mistral_client = MistralAsyncClient(api_key=MISTRAL_API_KEY)
        ENABLED_PROVIDERS.append("mistral")
        logging.info("✅ Mistral AI is available as backup.")
    except Exception as e:
        logging.warning(f"⚠️ Mistral Setup Failed: {e}")

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
- Made by Datrom. Model name is Iris (Main).
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
- Made by Datrom. Model name is Iris (Main).
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
        db.add_message(chat_id, "user", user_text, user_name)
        db.add_message(chat_id, "assistant", reply)
    else:
        reply = "Ahh my brain glitched~ 🥺 try again please! 💖"

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
        
        providers_str = ", ".join(ENABLED_PROVIDERS) if ENABLED_PROVIDERS else "NO AI BRAIN"
        print(f"Iris is waking up with {providers_str}... ✨ Press Ctrl+C to stop.")
        application.run_polling()
