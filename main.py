import logging
import re
from datetime import timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, ChatMember
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ChatJoinRequestHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- CONFIGURATION ---
# NOTE: Replace with your actual token
BOT_TOKEN = "7974658489:AAFCdZtki5NVOn7ez9UukXcCSYtpvF2fnVg"

# Multiple admin IDs
ADMIN_IDS = [8186973947, 7857898495]

CHANNEL_LINK = "https://t.me/shinchanbannedmovies"
CHANNEL_USERNAME = "@shinchanbannedmovies"

AUTO_APPROVE = True
DEFAULT_MUTE_DURATION_HOURS = 1
# ---------------------

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# Using __name__ for logger initialization
logger = logging.getLogger(__name__)

# Track warnings
user_warnings = {}  # {user_id: count}


# --- HELPER FUNCTIONS ---

def is_admin(user_id: int) -> bool:
    """Checks if the user ID is in the hardcoded ADMIN_IDS list."""
    return user_id in ADMIN_IDS

async def get_target_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Finds the target user ID either from a reply or an argument."""
    message = update.effective_message
    
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif context.args and context.args[0].isdigit():
        try:
            target_user = await context.bot.get_chat_member(message.chat_id, int(context.args[0]))
            return target_user.user.id
        except Exception:
            return int(context.args[0]) # Use ID directly even if not a known member
    else:
        await message.reply_text("Please reply to a user's message or provide their User ID.")
        return None
    
    return target_user.id

async def is_group_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if a user is an admin or creator of the current chat."""
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.CREATOR]
    except Exception:
        return False

async def apply_punishment(chat_id: int, user: object, count: int, context: ContextTypes.DEFAULT_TYPE, message_to_delete: Update = None):
    """Handles the 3-strike punishment system."""
    user_mention = user.mention_html()
    
    if message_to_delete:
        try:
            await message_to_delete.delete()
        except Exception as e:
            logger.warning(f"Failed to delete message from {user.id}: {e}")
            pass

    if count == 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ {user_mention}, this is your *first warning!* Stop sharing unauthorized content/links.",
            parse_mode=ParseMode.HTML,
        )
    elif count == 2:
        try:
            # Mute for 1 hour
            await context.bot.restrict_chat_member(
                chat_id,
                user.id,
                ChatPermissions(can_send_messages=False),
                until_date=timedelta(hours=DEFAULT_MUTE_DURATION_HOURS),
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔇 {user_mention} muted for {DEFAULT_MUTE_DURATION_HOURS} hour(s) for the second strike!",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Failed to mute {user.id}: {e}")
            await context.bot.send_message(chat_id, f"❌ Failed to mute {user_mention}. Bot may lack admin rights.", parse_mode=ParseMode.HTML)
    else:
        try:
            # Ban the user
            await context.bot.ban_chat_member(chat_id, user.id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🚫 {user_mention} has been *banned* for repeated offenses (3 strikes).",
                parse_mode=ParseMode.HTML,
            )
            # Clear warnings after ban
            if user.id in user_warnings:
                del user_warnings[user.id]

        except Exception as e:
            logger.error(f"Failed to ban {user.id}: {e}")
            await context.bot.send_message(chat_id, f"❌ Failed to ban {user_mention}. Bot may lack admin rights.", parse_mode=ParseMode.HTML)


# --- BOT COMMANDS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets the user and gives bot status."""
    await update.message.reply_text(
        "🤖 *Auto Approver + Anti-Link Bot Online!*\n\n"
        "Add me to your group and make me admin to start working!",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the bot commands and rules."""
    await update.message.reply_text(
        "🧩 *Bot Commands:*\n\n"
        "• /start - Check bot status\n"
        "• /help - Show this help\n"
        "• /status - Check bot permissions in the group\n"
        "• /broadcast <msg> - Send message to all active chats (Super Admin Only)\n\n"
        "🚨 *Moderation Commands (Group Admins/Super Admins):*\n"
        "• /warn [reply/ID] - Manually issue a warning.\n"
        "• /mute [reply/ID] [time_h] - Mute for specified hours (default 1h).\n"
        "• /unmute [reply/ID] - Unmute the user.\n"
        "• /clearwarn [reply/ID] - Reset user's warning count.\n\n"
        "🔗 *Protections:*\n"
        "• Auto Approve Join Requests\n"
        "• Welcome New Users\n"
        "• Detect Bio/External Links & Punish (3-strike system)\n",
        parse_mode=ParseMode.MARKDOWN,
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks and reports the bot's administrative status in the group."""
    chat = update.effective_chat
    bot_id = context.bot.id
    
    if chat.type == 'private':
        await update.message.reply_text("This command must be used in a group!")
        return
        
    try:
        member = await chat.get_member(bot_id)
        
        status_msg = f"⚙️ *Bot Status in {chat.title}:*\n\n"
        if member.status in [ChatMember.ADMINISTRATOR, ChatMember.CREATOR]:
            status_msg += "✅ I am an Administrator.\n"
            if member.can_restrict_members:
                status_msg += "✅ Can Restrict Members (Mute/Ban).\n"
            if member.can_delete_messages:
                status_msg += "✅ Can Delete Messages (Anti-Link).\n"
            if member.can_invite_users:
                status_msg += "✅ Can Invite Users (Auto-Approve).\n"
        else:
            status_msg += "❌ I am NOT an Administrator. Please make me one to enable all features."

        await update.message.reply_text(status_msg, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Error checking bot status: {e}")
        await update.message.reply_text("❌ Could not check bot status. Please ensure I am an admin.")


async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually issues a strike to a user."""
    chat = update.effective_chat
    issuer = update.effective_user
    
    if not (is_admin(issuer.id) or await is_group_admin(chat.id, issuer.id, context)):
        await update.message.reply_text("⛔ You must be a Super Admin or Group Admin to use this command.")
        return

    target_id = await get_target_user_id(update, context)
    if not target_id:
        return

    try:
        target_user = await context.bot.get_chat_member(chat.id, target_id)
        user = target_user.user
        
        # Don't punish admins
        if await is_group_admin(chat.id, user.id, context):
            await update.message.reply_text(f"🚫 Cannot warn {user.mention_html()}: they are a group admin.", parse_mode=ParseMode.HTML)
            return
            
        user_warnings[user.id] = user_warnings.get(user.id, 0) + 1
        count = user_warnings[user.id]
        
        await update.message.reply_text(f"Manual strike issued to {user.mention_html()}. Strike count: {count}", parse_mode=ParseMode.HTML)
        await apply_punishment(chat.id, user, count, context)
        
    except Exception as e:
        logger.error(f"Error in warn command: {e}")
        await update.message.reply_text("❌ Error processing warn command. User ID may be invalid or bot lacks permissions.")


async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mutes a user for a specified duration."""
    chat = update.effective_chat
    issuer = update.effective_user
    
    if not (is_admin(issuer.id) or await is_group_admin(chat.id, issuer.id, context)):
        await update.message.reply_text("⛔ You must be a Super Admin or Group Admin to use this command.")
        return

    target_id = await get_target_user_id(update, context)
    if not target_id:
        return
    
    duration_hours = DEFAULT_MUTE_DURATION_HOURS
    if len(context.args) > 0 and context.args[-1].isdigit():
        duration_hours = int(context.args[-1])

    try:
        target_user = await context.bot.get_chat_member(chat.id, target_id)
        user = target_user.user

        if await is_group_admin(chat.id, user.id, context):
            await update.message.reply_text(f"🚫 Cannot mute {user.mention_html()}: they are a group admin.", parse_mode=ParseMode.HTML)
            return

        # Mute the user
        await context.bot.restrict_chat_member(
            chat.id,
            user.id,
            ChatPermissions(can_send_messages=False),
            until_date=timedelta(hours=duration_hours),
        )
        
        await update.message.reply_text(
            f"✅ {user.mention_html()} has been muted for {duration_hours} hour(s).",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Error in mute command: {e}")
        await update.message.reply_text("❌ Error processing mute command. Bot may lack 'Restrict Members' permission.")


async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unmutes a user."""
    chat = update.effective_chat
    issuer = update.effective_user

    if not (is_admin(issuer.id) or await is_group_admin(chat.id, issuer.id, context)):
        await update.message.reply_text("⛔ You must be a Super Admin or Group Admin to use this command.")
        return

    target_id = await get_target_user_id(update, context)
    if not target_id:
        return

    try:
        target_user = await context.bot.get_chat_member(chat.id, target_id)
        user = target_user.user

        # Unmute: set all permissions back to True
        await context.bot.restrict_chat_member(
            chat.id,
            user.id,
            ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True, # covers stickers/gifs
                can_add_web_page_previews=True,
            ),
        )

        await update.message.reply_text(
            f"✅ {user.mention_html()} has been unmuted and can talk again.",
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Error in unmute command: {e}")
        await update.message.reply_text("❌ Error processing unmute command. Bot may lack 'Restrict Members' permission.")


async def clearwarn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resets the warning count for a specific user."""
    chat = update.effective_chat
    issuer = update.effective_user

    if not (is_admin(issuer.id) or await is_group_admin(chat.id, issuer.id, context)):
        await update.message.reply_text("⛔ You must be a Super Admin or Group Admin to use this command.")
        return

    target_id = await get_target_user_id(update, context)
    if not target_id:
        return
        
    try:
        target_user = await context.bot.get_chat_member(chat.id, target_id)
        user = target_user.user
        
        if user.id in user_warnings:
            del user_warnings[user.id]
            await update.message.reply_text(f"✅ Warning count for {user.mention_html()} has been reset.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(f"ℹ️ {user.mention_html()} has no active warnings.", parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Error in clearwarn command: {e}")
        await update.message.reply_text("❌ Error processing clearwarn command.")


# --- CORE LISTENERS ---

async def approve_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Automatically approves chat join requests."""
    chat = update.chat_join_request.chat
    user = update.chat_join_request.from_user
    logger.info(f"{user.full_name} requested to join {chat.title}")

    if AUTO_APPROVE:
        try:
            await context.bot.approve_chat_join_request(chat.id, user.id)
            logger.info(f"✅ Approved {user.full_name}")
        except Exception as e:
            logger.error(f"❌ Failed to approve: {e}")


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message to new members joining the group."""
    chat = update.effective_chat
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue

        user_mention = member.mention_html()
        buttons = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📢 Join Our Channel", url=CHANNEL_LINK)]]
        )

        msg = (
            f"👋 Welcome {user_mention}!\n"
            f"You're now part of <b>{chat.title}</b> 🎉\n\n"
            f"Make sure you’ve joined our updates channel:\n{CHANNEL_USERNAME}"
        )

        await update.message.reply_text(
            msg, 
            parse_mode=ParseMode.HTML, 
            reply_markup=buttons, 
            disable_web_page_preview=True
        )


async def detect_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detects links and applies the 3-strike punishment system."""
    message = update.message
    chat = update.effective_chat
    user = message.from_user

    if not user or user.is_bot or not message:
        return

    # Check if the user is an admin of the current group (to ignore them)
    try:
        if await is_group_admin(chat.id, user.id, context):
            return
    except Exception as e:
        logger.warning(f"Could not check admin status for {user.id}: {e}")
        # Continue if check fails, but log the warning

    text = message.text or message.caption or ""
    # Pattern detects common link structures including t.me, telegram.me, and bio links
    link_pattern = r"(https?://|t\.me/|telegram\.me/|bit\.ly|linktr\.ee|bio\.link)"

    if re.search(link_pattern, text, re.IGNORECASE):
        user_warnings[user.id] = user_warnings.get(user.id, 0) + 1
        count = user_warnings[user.id]

        # Apply the punishment system logic
        await apply_punishment(chat.id, user, count, context, message_to_delete=message)


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Super Admin-only command to send a message to all chats the bot knows about
    from recent updates.
    """
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ You’re not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    text = " ".join(context.args)
    sent = 0

    chats_to_broadcast = set()

    # FIX: Await the coroutine and iterate over the resulting list of Updates.
    try:
        updates = await context.bot.get_updates(offset=0)
    except Exception as e:
        logger.error(f"Failed to fetch updates for broadcast: {e}")
        await update.message.reply_text("❌ Error fetching recent chats for broadcast.")
        return

    # Extract unique chat IDs from the list of updates
    for item in updates:
        if item.effective_chat:
            chats_to_broadcast.add(item.effective_chat.id)
    
    # Also add the current chat ID
    if update.effective_chat:
        chats_to_broadcast.add(update.effective_chat.id)

    # Send the message
    for chat_id in chats_to_broadcast:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
            sent += 1
        except Exception as e:
            logger.warning(f"Could not send broadcast to chat {chat_id}: {e}")

    await update.message.reply_text(f"📢 Broadcast done. Sent to {sent} unique chats.")


# --- MAIN FUNCTION ---
def main():
    """Starts the bot."""
    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command, filters=filters.ChatType.GROUPS))
    
    # Moderation Commands
    app.add_handler(CommandHandler("warn", warn_command, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("mute", mute_command, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("unmute", unmute_command, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("clearwarn", clearwarn_command, filters=filters.ChatType.GROUPS))
    
    # Admin Command
    app.add_handler(CommandHandler("broadcast", broadcast))

    # Core Listeners
    app.add_handler(ChatJoinRequestHandler(approve_join_request))
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member)
    )
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & (filters.TEXT | filters.CAPTION), detect_links)
    )

    logger.info("🚀 Bot is now running...")
    app.run_polling(poll_interval=1.0) 


if __name__ == "__main__":
    main()
