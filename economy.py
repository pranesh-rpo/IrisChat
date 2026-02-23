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
    await update.message.reply_text(
        f"💳 **{user_name}'s Wallet**\nBalance: {bal} {CURRENCY_SYMBOL}",
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
            await update.message.reply_text(f"⏳ Stop begging so much! Wait {remaining} seconds.")
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
        await update.message.reply_text(random.choice(responses))
    else:
        db.set_cooldown(user_id, "beg")
        responses = [
            "Get a job! 😤",
            "No coins for you today. ❌",
            "Someone threw a shoe at you instead. 👞",
            "Iris just stared at you awkwardly... 👀"
        ]
        await update.message.reply_text(random.choice(responses))

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
            await update.message.reply_text(f"⏳ You've already claimed your daily reward! Come back in {hours}h {minutes}m.")
            return

    amount = 500
    db.update_balance(user_id, amount)
    db.set_cooldown(user_id, "daily")
    await update.message.reply_text(f"🌞 **Daily Reward Claimed!**\nYou received {amount} {CURRENCY_SYMBOL}! Come back tomorrow! 💖", parse_mode='Markdown')

    # Badge: First Daily
    db.award_badge(user_id, "First Daily")

async def gamble(update, context):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("🎲 Usage: `!gamble <amount>` or `!gamble all`", parse_mode='Markdown')
        return

    current_bal = db.get_balance(user_id)
    bet_input = context.args[0].lower()

    if bet_input == "all":
        amount = current_bal
    else:
        try:
            amount = int(bet_input)
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number.")
            return

    if amount <= 0:
        await update.message.reply_text("❌ You can't gamble zero or negative coins!")
        return

    if amount > current_bal:
        await update.message.reply_text(f"❌ You don't have enough coins! Balance: {current_bal} {CURRENCY_SYMBOL}")
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
        await update.message.reply_text(f"🎰 **WINNER!**\nYou won {winnings} {CURRENCY_SYMBOL}! 🎉\nNew Balance: {new_bal} {CURRENCY_SYMBOL}", parse_mode='Markdown')
        # Badge: High Roller
        if amount >= 1000:
            db.award_badge(user_id, "High Roller")
    else:
        # Lose
        db.update_balance(user_id, -amount)
        new_bal = current_bal - amount
        await update.message.reply_text(f"🎰 **YOU LOST!** 😭\nIris took your {amount} {CURRENCY_SYMBOL}.\nNew Balance: {new_bal} {CURRENCY_SYMBOL}", parse_mode='Markdown')

async def leaderboard(update, context):
    top_users = db.get_leaderboard(10)
    if not top_users:
        await update.message.reply_text("No one has any coins yet! 🥺")
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
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def pay(update, context):
    sender_id = update.effective_user.id
    
    if not context.args:
         await update.message.reply_text("💸 Usage: Reply to someone with `!pay <amount>`", parse_mode='Markdown')
         return
         
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Use `!pay <amount>`")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Amount must be positive.")
        return

    sender_bal = db.get_balance(sender_id)
    if amount > sender_bal:
        await update.message.reply_text(f"❌ You're too poor! Balance: {sender_bal}")
        return

    # Determine recipient
    if update.message.reply_to_message:
        recipient_id = update.message.reply_to_message.from_user.id
        recipient_name = update.message.reply_to_message.from_user.first_name
    else:
        await update.message.reply_text("❌ You must reply to the user you want to pay.")
        return
        
    if recipient_id == sender_id:
        await update.message.reply_text("❌ You can't pay yourself!")
        return

    db.update_balance(sender_id, -amount)
    db.update_balance(recipient_id, amount)
    db.update_user_name(recipient_id, recipient_name)

    # Badge: Generous (pay 500+)
    if amount >= 500:
        if db.award_badge(sender_id, "Generous"):
            await update.message.reply_text("🏅 **Badge Unlocked:** Generous! (Paid 500+ coins) 💕")

    await update.message.reply_text(
        f"💸 **Payment Successful!**\n{update.effective_user.first_name} sent {amount} {CURRENCY_SYMBOL} to {recipient_name}!",
        parse_mode='Markdown'
    )

# ==================== SHOP SYSTEM ====================

SHOP_ITEMS = {
    "shield": {"name": "Shield", "emoji": "🛡️", "price": 500, "desc": "Protects you from robbery for 1 use", "type": "consumable"},
    "luckycharm": {"name": "Lucky Charm", "emoji": "🍀", "price": 800, "desc": "+10% gamble win chance (1 use)", "type": "consumable"},
    "crown": {"name": "Crown", "emoji": "👑", "price": 2000, "desc": "Flex on everyone (cosmetic)", "type": "cosmetic"},
    "lootbox": {"name": "Lootbox", "emoji": "📦", "price": 300, "desc": "Random 50-1000 coins inside!", "type": "instant"},
    "rose": {"name": "Rose", "emoji": "🌹", "price": 100, "desc": "Give to someone special~ cosmetic", "type": "giftable"},
    "potion": {"name": "Energy Potion", "emoji": "⚗️", "price": 400, "desc": "Reset work cooldown instantly!", "type": "consumable"},
    "magnet": {"name": "Coin Magnet", "emoji": "🧲", "price": 1000, "desc": "2x earnings for next 3 work sessions", "type": "consumable"},
    "dice": {"name": "Lucky Dice", "emoji": "🎲", "price": 600, "desc": "50% better rob success rate (1 use)", "type": "consumable"},
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
            await update.message.reply_text(f"⏳ You're tired! Rest for {mins}m {secs}s before working again.")
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
    
    # Check for Coin Magnet effect (2x earnings)
    magnet_uses = db.get_effect(user_id, "magnet")
    bonus_text = ""
    if magnet_uses and magnet_uses > 0:
        amount *= 2
        db.set_effect(user_id, "magnet", magnet_uses - 1)
        remaining = magnet_uses - 1
        bonus_text = f"\n🧲 **Coin Magnet active!** Earnings doubled! ({remaining} uses left)"
    
    db.update_balance(user_id, amount)
    db.set_cooldown(user_id, "work")

    await update.message.reply_text(f"{job_text} **{amount}** {CURRENCY_SYMBOL}! 💪{bonus_text}", parse_mode='Markdown')

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
            await update.message.reply_text(f"⏳ You need to lay low! Wait {mins}m {secs}s.")
            return

    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to someone to rob them! 🦹")
        return

    target = update.message.reply_to_message.from_user
    if target.id == user_id:
        await update.message.reply_text("❌ You can't rob yourself, silly! 😂")
        return
    if target.is_bot:
        await update.message.reply_text("❌ You can't rob a bot! 🤖")
        return

    # Check if target has a shield
    if db.has_item(target.id, "shield"):
        db.remove_item(target.id, "shield")
        db.set_cooldown(user_id, "rob")
        await update.message.reply_text(f"🛡️ **{target.first_name}** had a Shield! Your robbery was blocked! The shield broke in the process~ 💔", parse_mode='Markdown')
        return

    target_bal = db.get_balance(target.id)
    robber_bal = db.get_balance(user_id)

    if target_bal < 100:
        await update.message.reply_text(f"❌ {target.first_name} is too poor to rob! (Balance < 100) 🥺")
        return

    db.set_cooldown(user_id, "rob")

    # Check for Lucky Dice (better success rate)
    success_rate = 0.40  # 40% base
    dice_used = False
    if db.has_item(user_id, "dice"):
        success_rate = 0.65  # 65% with dice (50% boost)
        db.remove_item(user_id, "dice")
        dice_used = True

    # Success check
    if random.random() < success_rate:
        stolen = random.randint(1, min(target_bal // 3, 500))
        db.update_balance(user_id, stolen)
        db.update_balance(target.id, -stolen)
        dice_text = "\n🎲 Lucky Dice helped you succeed!" if dice_used else ""
        await update.message.reply_text(f"🦹 **{user_name}** robbed **{stolen}** {CURRENCY_SYMBOL} from **{target.first_name}**! 💰{dice_text}", parse_mode='Markdown')
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
        await update.message.reply_text(random.choice(fail_msgs), parse_mode='Markdown')

async def slots(update, context):
    """Slot machine game."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("🎰 Usage: `!slots <amount>` or `!slots all`", parse_mode='Markdown')
        return

    current_bal = db.get_balance(user_id)
    bet_input = context.args[0].lower()

    if bet_input == "all":
        amount = current_bal
    else:
        try:
            amount = int(bet_input)
        except ValueError:
            await update.message.reply_text("❌ Invalid amount!")
            return

    if amount <= 0:
        await update.message.reply_text("❌ Bet must be positive!")
        return
    if amount > current_bal:
        await update.message.reply_text(f"❌ Not enough coins! Balance: {current_bal} {CURRENCY_SYMBOL}")
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

    await update.message.reply_text(result, parse_mode='Markdown')

async def shop(update, context):
    """Display the item shop."""
    chat_id = update.effective_chat.id
    msg = "🏪 **Iris Shop** 🏪\n\n"
    for key, item in SHOP_ITEMS.items():
        msg += f"{item['emoji']} **{item['name']}** — {item['price']} {CURRENCY_SYMBOL}\n"
        msg += f"   _{item['desc']}_\n\n"
    msg += f"Buy with: `!buy <item>`\nExample: `!buy shield`"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def buy(update, context):
    """Buy an item from the shop."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Usage: `!buy <item>`\nSee `!shop` for available items!", parse_mode='Markdown')
        return

    item_key = context.args[0].lower()
    if item_key not in SHOP_ITEMS:
        await update.message.reply_text(f"❌ Item `{item_key}` not found! Check `!shop`", parse_mode='Markdown')
        return

    item = SHOP_ITEMS[item_key]
    bal = db.get_balance(user_id)
    if bal < item["price"]:
        await update.message.reply_text(f"❌ You need **{item['price']}** {CURRENCY_SYMBOL} but only have **{bal}**!", parse_mode='Markdown')
        return

    # Special handling for lootbox — instant open
    if item_key == "lootbox":
        db.update_balance(user_id, -item["price"])
        loot = random.randint(50, 1000)
        db.update_balance(user_id, loot)
        new_bal = bal - item["price"] + loot
        await update.message.reply_text(f"📦 **Lootbox opened!**\nYou found **{loot}** {CURRENCY_SYMBOL} inside! {'🎉' if loot > 500 else '😊'}\nBalance: {new_bal} {CURRENCY_SYMBOL}", parse_mode='Markdown')
        return

    db.update_balance(user_id, -item["price"])
    db.add_item(user_id, item_key)
    new_bal = bal - item["price"]
    await update.message.reply_text(f"✅ **Purchased {item['emoji']} {item['name']}!**\nBalance: {new_bal} {CURRENCY_SYMBOL}\nCheck `!inventory` to see your items!", parse_mode='Markdown')

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
        await update.message.reply_text(f"🎒 **{user_name}'s Inventory**\n\n_Empty! Buy items with `!shop`_", parse_mode='Markdown')
        return

    msg = f"🎒 **{user_name}'s Inventory**\n\n"
    for item_key, qty in inv.items():
        item_info = SHOP_ITEMS.get(item_key, {"name": item_key, "emoji": "❓"})
        msg += f"{item_info['emoji']} **{item_info['name']}** x{qty}\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

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
        await update.message.reply_text(f"🏅 **{user_name}'s Badges**\n\n_No badges yet! Keep playing to earn some~_ 💕", parse_mode='Markdown')
        return

    msg = f"🏅 **{user_name}'s Badges**\n\n"
    for badge_name, earned_at in user_badges:
        emoji = BADGE_EMOJIS.get(badge_name, "🏅")
        msg += f"{emoji} **{badge_name}**\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

async def use_item(update, context):
    """Use a consumable item from inventory."""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    if not context.args:
        await update.message.reply_text("💊 Usage: `!use <item>`\nExample: `!use potion`", parse_mode='Markdown')
        return
    
    item_key = context.args[0].lower()
    
    if item_key not in SHOP_ITEMS:
        await update.message.reply_text(f"❌ Item `{item_key}` doesn't exist!", parse_mode='Markdown')
        return
    
    if not db.has_item(user_id, item_key):
        await update.message.reply_text(f"❌ You don't have a {SHOP_ITEMS[item_key]['emoji']} **{SHOP_ITEMS[item_key]['name']}**!", parse_mode='Markdown')
        return
    
    item = SHOP_ITEMS[item_key]
    
    # Handle different item types
    if item_key == "potion":
        # Reset work cooldown
        db.set_cooldown(user_id, "work", reset=True)
        db.remove_item(user_id, item_key)
        await update.message.reply_text(f"⚗️ **Energy Potion used!**\nYour work cooldown has been reset! You can work again now! 💪", parse_mode='Markdown')
    
    elif item_key == "magnet":
        # Activate 2x work earnings for 3 sessions
        db.set_effect(user_id, "magnet", 3)  # Store effect with 3 uses remaining
        db.remove_item(user_id, item_key)
        await update.message.reply_text(f"🧲 **Coin Magnet activated!**\nYour next 3 work sessions will earn **2x coins**! 💰", parse_mode='Markdown')
    
    elif item_key == "luckycharm":
        await update.message.reply_text(f"🍀 **Lucky Charm** is automatically used when you gamble!\nJust use `!gamble <amount>` and it will boost your chances! ✨", parse_mode='Markdown')
    
    elif item_key == "shield":
        await update.message.reply_text(f"🛡️ **Shield** is automatically used when someone tries to rob you!\nIt will protect you from the next robbery attempt! 🔒", parse_mode='Markdown')
    
    elif item_key == "dice":
        await update.message.reply_text(f"🎲 **Lucky Dice** is automatically used when you rob someone!\nJust use `!rob` (reply to someone) and it will boost your success rate! 🎯", parse_mode='Markdown')
    
    elif item["type"] == "cosmetic":
        await update.message.reply_text(f"✨ You can't 'use' cosmetic items! They're for showing off!\nUse `!profile` to see your equipped items! 👑", parse_mode='Markdown')
    
    elif item["type"] == "giftable":
        await update.message.reply_text(f"🎁 Use `!gift <item>` (reply to someone) to give them this item!\nExample: Reply to someone and type `!gift rose` 🌹", parse_mode='Markdown')
    
    else:
        await update.message.reply_text(f"❌ This item can't be used directly!", parse_mode='Markdown')

async def gift_item(update, context):
    """Gift an item to another user."""
    sender_id = update.effective_user.id
    sender_name = update.effective_user.first_name
    
    if not context.args:
        await update.message.reply_text("🎁 Usage: Reply to someone with `!gift <item>`\nExample: `!gift rose`", parse_mode='Markdown')
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ You must reply to the user you want to gift!", parse_mode='Markdown')
        return
    
    recipient = update.message.reply_to_message.from_user
    recipient_id = recipient.id
    recipient_name = recipient.first_name
    
    if recipient_id == sender_id:
        await update.message.reply_text("❌ You can't gift yourself! That's just... sad. 🥺", parse_mode='Markdown')
        return
    
    if recipient.is_bot:
        await update.message.reply_text("❌ Bots don't need gifts! 🤖", parse_mode='Markdown')
        return
    
    item_key = context.args[0].lower()
    
    if item_key not in SHOP_ITEMS:
        await update.message.reply_text(f"❌ Item `{item_key}` doesn't exist!", parse_mode='Markdown')
        return
    
    if not db.has_item(sender_id, item_key):
        item = SHOP_ITEMS[item_key]
        await update.message.reply_text(f"❌ You don't have a {item['emoji']} **{item['name']}** to gift!", parse_mode='Markdown')
        return
    
    item = SHOP_ITEMS[item_key]
    
    # Transfer item
    db.remove_item(sender_id, item_key)
    db.add_item(recipient_id, item_key)
    db.update_user_name(recipient_id, recipient_name)
    
    await update.message.reply_text(
        f"🎁 **Gift Sent!**\n{sender_name} gave {item['emoji']} **{item['name']}** to {recipient_name}! 💝",
        parse_mode='Markdown'
    )
    
    # Award badge for gifting
    if item_key == "rose":
        db.award_badge(sender_id, "Romantic")

async def profile_command(update, context):
    """Show user's profile with cosmetics and stats."""
    target_user = update.effective_user
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    
    user_id = target_user.id
    user_name = target_user.first_name
    
    bal = db.get_balance(user_id)
    inv = db.get_inventory(user_id)
    badges = db.get_badges(user_id)
    
    # Build profile
    msg = f"👤 **{user_name}'s Profile**\n\n"
    msg += f"💰 Balance: **{bal}** {CURRENCY_SYMBOL}\n"
    
    # Show equipped cosmetics
    cosmetics = []
    if inv:
        for item_key, qty in inv.items():
            item_info = SHOP_ITEMS.get(item_key, {})
            if item_info.get("type") == "cosmetic" and qty > 0:
                cosmetics.append(item_info['emoji'])
    
    if cosmetics:
        msg += f"✨ Cosmetics: {' '.join(cosmetics)}\n"
    
    # Show badge count
    badge_count = len(badges) if badges else 0
    msg += f"🏅 Badges: **{badge_count}**\n"
    
    # Show total items
    item_count = sum(inv.values()) if inv else 0
    msg += f"🎒 Items: **{item_count}**\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')
