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

    # 45% chance to win (House edge)
    if random.random() < 0.45:
        # Win
        winnings = amount
        db.update_balance(user_id, winnings)
        new_bal = current_bal + winnings
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🎰 **WINNER!**\nYou won {winnings} {CURRENCY_SYMBOL}! 🎉\nNew Balance: {new_bal} {CURRENCY_SYMBOL}", parse_mode='Markdown')
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
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text=f"💸 **Payment Successful!**\n{update.effective_user.first_name} sent {amount} {CURRENCY_SYMBOL} to {recipient_name}!",
        parse_mode='Markdown'
    )
