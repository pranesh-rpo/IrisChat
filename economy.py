import random
from datetime import datetime, timedelta
import db

CURRENCY_NAME = "IrisCoins"
CURRENCY_SYMBOL = "🌸"

async def balance(update, context):
    target_user = update.effective_user
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        
    user_id = target_user.id
    user_name = target_user.first_name
    
    # Update name in DB
    db.update_user_name(user_id, user_name)
    
    bal = db.get_balance(user_id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"💳 **{user_name}'s Wallet**\nBalance: {bal} {CURRENCY_SYMBOL}",
        parse_mode='Markdown'
    )

async def beg(update, context):
    user_id = update.effective_user.id
    
    # Check cooldown (e.g., 1 minute)
    last_beg = db.get_cooldown(user_id, "beg")
    if last_beg:
        last_time = datetime.fromisoformat(last_beg)
        if datetime.now() - last_time < timedelta(minutes=1):
            remaining = int(60 - (datetime.now() - last_time).total_seconds())
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⏳ Stop begging so much! Wait {remaining} seconds.")
            return

    # Random chance to get coins
    if random.random() < 0.7: # 70% success
        amount = random.randint(10, 50)
        db.update_balance(user_id, amount)
        db.set_cooldown(user_id, "beg")
        responses = [
            f"Here, take {amount} {CURRENCY_SYMBOL}. Don't spend it all in one place! 😒",
            f"A kind stranger gave you {amount} {CURRENCY_SYMBOL}! 🎉",
            f"You found {amount} {CURRENCY_SYMBOL} on the floor. Lucky! 🍀",
            f"Iris felt sorry for you and gave you {amount} {CURRENCY_SYMBOL}. 🥺"
        ]
        await context.bot.send_message(chat_id=update.effective_chat.id, text=random.choice(responses))
    else:
        db.set_cooldown(user_id, "beg")
        responses = [
            "Get a job! 😤",
            "No coins for you today. ❌",
            "Someone threw a shoe at you instead. 👞",
            "Iris just stared at you awkwardly... 👀"
        ]
        await context.bot.send_message(chat_id=update.effective_chat.id, text=random.choice(responses))

async def daily(update, context):
    user_id = update.effective_user.id
    
    last_daily = db.get_cooldown(user_id, "daily")
    if last_daily:
        last_time = datetime.fromisoformat(last_daily)
        if datetime.now() - last_time < timedelta(hours=24):
            # Calculate remaining time
            next_daily = last_time + timedelta(hours=24)
            remaining = next_daily - datetime.now()
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⏳ You've already claimed your daily reward! Come back in {hours}h {minutes}m.")
            return

    amount = 500
    db.update_balance(user_id, amount)
    db.set_cooldown(user_id, "daily")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🌞 **Daily Reward Claimed!**\nYou received {amount} {CURRENCY_SYMBOL}! Come back tomorrow! 💖", parse_mode='Markdown')

    # Badge: First Daily
    db.award_badge(user_id, "First Daily")

async def gamble(update, context):
    user_id = update.effective_user.id
    
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="🎲 Usage: `!gamble <amount>` or `!gamble all`", parse_mode='Markdown')
        return

    current_bal = db.get_balance(user_id)
    bet_input = context.args[0].lower()

    if bet_input == "all":
        amount = current_bal
    else:
        try:
            amount = int(bet_input)
        except ValueError:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Please enter a valid number.")
            return

    if amount <= 0:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You can't gamble zero or negative coins!")
        return

    if amount > current_bal:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ You don't have enough coins! Balance: {current_bal} {CURRENCY_SYMBOL}")
        return

    # Check for Lucky Charm item (+10% win chance)
    win_chance = 0.45
    if db.has_item(user_id, "luckycharm"):
        win_chance = 0.55
        db.remove_item(user_id, "luckycharm")

    # Win chance (45% base, 55% with lucky charm)
    if random.random() < win_chance:
        # Win
        winnings = amount
        db.update_balance(user_id, winnings)
        new_bal = current_bal + winnings
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🎰 **WINNER!**\nYou won {winnings} {CURRENCY_SYMBOL}! 🎉\nNew Balance: {new_bal} {CURRENCY_SYMBOL}", parse_mode='Markdown')
        # Badge: High Roller
        if amount >= 1000:
            db.award_badge(user_id, "High Roller")
    else:
        # Lose
        db.update_balance(user_id, -amount)
        new_bal = current_bal - amount
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🎰 **YOU LOST!** 😭\nIris took your {amount} {CURRENCY_SYMBOL}.\nNew Balance: {new_bal} {CURRENCY_SYMBOL}", parse_mode='Markdown')

async def leaderboard(update, context):
    top_users = db.get_leaderboard(10)
    if not top_users:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="No one has any coins yet! 🥺")
        return

    msg = "🏆 **Richest Users** 🏆\n\n"
    for i, (uid, bal, db_name) in enumerate(top_users, 1):
        # Use name from DB if available, otherwise try to fetch (fallback)
        if db_name:
             name = db_name
        else:
            try:
                member = await context.bot.get_chat_member(update.effective_chat.id, uid)
                name = member.user.first_name
            except:
                name = f"User {uid}"
            
        msg += f"{i}. **{name}**: {bal} {CURRENCY_SYMBOL}\n"
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='Markdown')

async def pay(update, context):
    sender_id = update.effective_user.id
    
    if not context.args:
         await context.bot.send_message(chat_id=update.effective_chat.id, text="💸 Usage: Reply to someone with `!pay <amount>`", parse_mode='Markdown')
         return
         
    try:
        amount = int(context.args[0])
    except ValueError:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Invalid amount. Use `!pay <amount>`")
        return

    if amount <= 0:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Amount must be positive.")
        return

    sender_bal = db.get_balance(sender_id)
    if amount > sender_bal:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ You're too poor! Balance: {sender_bal}")
        return

    # Determine recipient
    if update.message.reply_to_message:
        recipient_id = update.message.reply_to_message.from_user.id
        recipient_name = update.message.reply_to_message.from_user.first_name
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You must reply to the user you want to pay.")
        return
        
    if recipient_id == sender_id:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You can't pay yourself!")
        return

    db.update_balance(sender_id, -amount)
    db.update_balance(recipient_id, amount)
    db.update_user_name(recipient_id, recipient_name)

    # Badge: Generous (pay 500+)
    if amount >= 500:
        if db.award_badge(sender_id, "Generous"):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="🏅 **Badge Unlocked:** Generous! (Paid 500+ coins) 💕")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"💸 **Payment Successful!**\n{update.effective_user.first_name} sent {amount} {CURRENCY_SYMBOL} to {recipient_name}!",
        parse_mode='Markdown'
    )

# ==================== SHOP SYSTEM ====================

SHOP_ITEMS = {
    "shield": {"name": "Shield", "emoji": "🛡️", "price": 500, "desc": "Protects you from robbery for 1 use"},
    "luckycharm": {"name": "Lucky Charm", "emoji": "🍀", "price": 800, "desc": "+10% gamble win chance (1 use)"},
    "crown": {"name": "Crown", "emoji": "👑", "price": 2000, "desc": "Flex on everyone (cosmetic)"},
    "lootbox": {"name": "Lootbox", "emoji": "📦", "price": 300, "desc": "Random 50-1000 coins inside!"},
    "rose": {"name": "Rose", "emoji": "🌹", "price": 100, "desc": "Give to someone special~ cosmetic"},
}

async def work(update, context):
    """Work a random job to earn coins."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    last_work = db.get_cooldown(user_id, "work")
    if last_work:
        last_time = datetime.fromisoformat(last_work)
        if datetime.now() - last_time < timedelta(minutes=10):
            remaining = int(600 - (datetime.now() - last_time).total_seconds())
            mins, secs = divmod(remaining, 60)
            await context.bot.send_message(chat_id=chat_id, text=f"⏳ You're tired! Rest for {mins}m {secs}s before working again.")
            return

    jobs = [
        ("👩‍🍳 You worked as a chef and earned", 100, 300),
        ("🎨 You painted a portrait and earned", 80, 250),
        ("💻 You did some freelance coding and earned", 150, 400),
        ("🚗 You drove for Uber and earned", 50, 200),
        ("📦 You delivered packages and earned", 60, 180),
        ("🎸 You busked on the street and earned", 30, 350),
        ("🧹 You cleaned houses and earned", 70, 160),
        ("📸 You took photos for events and earned", 90, 280),
        ("🎮 You streamed on Twitch and earned", 40, 500),
        ("🐕 You walked some dogs and earned", 50, 150),
    ]

    job_text, min_pay, max_pay = random.choice(jobs)
    amount = random.randint(min_pay, max_pay)
    db.update_balance(user_id, amount)
    db.set_cooldown(user_id, "work")

    await context.bot.send_message(chat_id=chat_id, text=f"{job_text} **{amount}** {CURRENCY_SYMBOL}! 💪", parse_mode='Markdown')

    # Badge: Worker (work 10+ times) — simple check
    db.award_badge(user_id, "Hard Worker")

async def rob(update, context):
    """Try to rob someone (reply to them)."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name

    last_rob = db.get_cooldown(user_id, "rob")
    if last_rob:
        last_time = datetime.fromisoformat(last_rob)
        if datetime.now() - last_time < timedelta(minutes=30):
            remaining = int(1800 - (datetime.now() - last_time).total_seconds())
            mins, secs = divmod(remaining, 60)
            await context.bot.send_message(chat_id=chat_id, text=f"⏳ You need to lay low! Wait {mins}m {secs}s.")
            return

    if not update.message.reply_to_message:
        await context.bot.send_message(chat_id=chat_id, text="❌ Reply to someone to rob them! 🦹")
        return

    target = update.message.reply_to_message.from_user
    if target.id == user_id:
        await context.bot.send_message(chat_id=chat_id, text="❌ You can't rob yourself, silly! 😂")
        return
    if target.is_bot:
        await context.bot.send_message(chat_id=chat_id, text="❌ You can't rob a bot! 🤖")
        return

    # Check if target has a shield
    if db.has_item(target.id, "shield"):
        db.remove_item(target.id, "shield")
        db.set_cooldown(user_id, "rob")
        await context.bot.send_message(chat_id=chat_id, text=f"🛡️ **{target.first_name}** had a Shield! Your robbery was blocked! The shield broke in the process~ 💔")
        return

    target_bal = db.get_balance(target.id)
    robber_bal = db.get_balance(user_id)

    if target_bal < 100:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ {target.first_name} is too poor to rob! (Balance < 100) 🥺")
        return

    db.set_cooldown(user_id, "rob")

    # 40% success rate
    if random.random() < 0.40:
        stolen = random.randint(1, min(target_bal // 3, 500))
        db.update_balance(user_id, stolen)
        db.update_balance(target.id, -stolen)
        await context.bot.send_message(chat_id=chat_id, text=f"🦹 **{user_name}** robbed **{stolen}** {CURRENCY_SYMBOL} from **{target.first_name}**! 💰", parse_mode='Markdown')
    else:
        # Failed — pay a fine
        fine = random.randint(50, min(robber_bal // 4, 200)) if robber_bal > 50 else 0
        if fine > 0:
            db.update_balance(user_id, -fine)
        fail_msgs = [
            f"🚔 You got caught! Fined **{fine}** {CURRENCY_SYMBOL}! 😂",
            f"👮 The police caught you! Lost **{fine}** {CURRENCY_SYMBOL}!",
            f"🏃 {target.first_name} punched you and you dropped **{fine}** {CURRENCY_SYMBOL}!",
            f"🐕 A guard dog chased you away! Fined **{fine}** {CURRENCY_SYMBOL}!",
        ]
        await context.bot.send_message(chat_id=chat_id, text=random.choice(fail_msgs), parse_mode='Markdown')

async def slots(update, context):
    """Slot machine game."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not context.args:
        await context.bot.send_message(chat_id=chat_id, text="🎰 Usage: `!slots <amount>` or `!slots all`", parse_mode='Markdown')
        return

    current_bal = db.get_balance(user_id)
    bet_input = context.args[0].lower()

    if bet_input == "all":
        amount = current_bal
    else:
        try:
            amount = int(bet_input)
        except ValueError:
            await context.bot.send_message(chat_id=chat_id, text="❌ Invalid amount!")
            return

    if amount <= 0:
        await context.bot.send_message(chat_id=chat_id, text="❌ Bet must be positive!")
        return
    if amount > current_bal:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Not enough coins! Balance: {current_bal} {CURRENCY_SYMBOL}")
        return

    # Slot reels
    symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣", "🌸"]
    weights = [25, 20, 20, 15, 10, 5, 5]  # weighted for rarity

    reel1 = random.choices(symbols, weights=weights, k=1)[0]
    reel2 = random.choices(symbols, weights=weights, k=1)[0]
    reel3 = random.choices(symbols, weights=weights, k=1)[0]

    display = f"╔══════════╗\n║ {reel1} │ {reel2} │ {reel3} ║\n╚══════════╝"

    # Check wins
    if reel1 == reel2 == reel3:
        # Jackpot! Multiplier depends on symbol
        multipliers = {"7️⃣": 10, "💎": 7, "🌸": 5, "🍇": 4, "🍊": 3, "🍋": 2.5, "🍒": 2}
        mult = multipliers.get(reel1, 2)
        winnings = int(amount * mult)
        db.update_balance(user_id, winnings)
        new_bal = current_bal + winnings
        result = f"🎰 **JACKPOT!!!** 🎉🎉🎉\n{display}\n\n**{reel1} x3** — {mult}x multiplier!\nWon: **{winnings}** {CURRENCY_SYMBOL}\nBalance: {new_bal} {CURRENCY_SYMBOL}"
    elif reel1 == reel2 or reel2 == reel3 or reel1 == reel3:
        # Two match — 1.5x
        winnings = int(amount * 0.5)
        db.update_balance(user_id, winnings)
        new_bal = current_bal + winnings
        result = f"🎰 **Two match!** 🎉\n{display}\n\nWon: **{winnings}** {CURRENCY_SYMBOL}\nBalance: {new_bal} {CURRENCY_SYMBOL}"
    else:
        # Lose
        db.update_balance(user_id, -amount)
        new_bal = current_bal - amount
        result = f"🎰 **No match...** 😢\n{display}\n\nLost: **{amount}** {CURRENCY_SYMBOL}\nBalance: {new_bal} {CURRENCY_SYMBOL}"

    await context.bot.send_message(chat_id=chat_id, text=result, parse_mode='Markdown')

async def shop(update, context):
    """Display the item shop."""
    chat_id = update.effective_chat.id
    msg = "🏪 **Iris Shop** 🏪\n\n"
    for key, item in SHOP_ITEMS.items():
        msg += f"{item['emoji']} **{item['name']}** — {item['price']} {CURRENCY_SYMBOL}\n"
        msg += f"   _{item['desc']}_\n\n"
    msg += f"Buy with: `!buy <item>`\nExample: `!buy shield`"
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

async def buy(update, context):
    """Buy an item from the shop."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not context.args:
        await context.bot.send_message(chat_id=chat_id, text="Usage: `!buy <item>`\nSee `!shop` for available items!", parse_mode='Markdown')
        return

    item_key = context.args[0].lower()
    if item_key not in SHOP_ITEMS:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Item `{item_key}` not found! Check `!shop`", parse_mode='Markdown')
        return

    item = SHOP_ITEMS[item_key]
    bal = db.get_balance(user_id)
    if bal < item["price"]:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ You need **{item['price']}** {CURRENCY_SYMBOL} but only have **{bal}**!", parse_mode='Markdown')
        return

    # Special handling for lootbox — instant open
    if item_key == "lootbox":
        db.update_balance(user_id, -item["price"])
        loot = random.randint(50, 1000)
        db.update_balance(user_id, loot)
        new_bal = bal - item["price"] + loot
        await context.bot.send_message(chat_id=chat_id, text=f"📦 **Lootbox opened!**\nYou found **{loot}** {CURRENCY_SYMBOL} inside! {'🎉' if loot > 500 else '😊'}\nBalance: {new_bal} {CURRENCY_SYMBOL}", parse_mode='Markdown')
        return

    db.update_balance(user_id, -item["price"])
    db.add_item(user_id, item_key)
    new_bal = bal - item["price"]
    await context.bot.send_message(chat_id=chat_id, text=f"✅ **Purchased {item['emoji']} {item['name']}!**\nBalance: {new_bal} {CURRENCY_SYMBOL}\nCheck `!inventory` to see your items!", parse_mode='Markdown')

async def inventory(update, context):
    """Show user's inventory."""
    target_user = update.effective_user
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user

    user_id = target_user.id
    user_name = target_user.first_name
    chat_id = update.effective_chat.id

    inv = db.get_inventory(user_id)
    if not inv:
        await context.bot.send_message(chat_id=chat_id, text=f"🎒 **{user_name}'s Inventory**\n\n_Empty! Buy items with `!shop`_", parse_mode='Markdown')
        return

    msg = f"🎒 **{user_name}'s Inventory**\n\n"
    for item_key, qty in inv.items():
        item_info = SHOP_ITEMS.get(item_key, {"name": item_key, "emoji": "❓"})
        msg += f"{item_info['emoji']} **{item_info['name']}** x{qty}\n"

    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

async def badges_command(update, context):
    """Show user's badges."""
    target_user = update.effective_user
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user

    user_id = target_user.id
    user_name = target_user.first_name
    chat_id = update.effective_chat.id

    user_badges = db.get_badges(user_id)

    BADGE_EMOJIS = {
        "First Daily": "🌅", "High Roller": "🎰", "Generous": "💝",
        "Hard Worker": "💪", "Lucky": "🍀", "Shopaholic": "🛍️",
        "Married": "💍", "Fighter": "⚔️",
    }

    if not user_badges:
        await context.bot.send_message(chat_id=chat_id, text=f"🏅 **{user_name}'s Badges**\n\n_No badges yet! Keep playing to earn some~_ 💕", parse_mode='Markdown')
        return

    msg = f"🏅 **{user_name}'s Badges**\n\n"
    for badge_name, earned_at in user_badges:
        emoji = BADGE_EMOJIS.get(badge_name, "🏅")
        msg += f"{emoji} **{badge_name}**\n"

    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
