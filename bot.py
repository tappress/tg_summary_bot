import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Tuple, Dict
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ContentType, ChatMemberUpdated
from config import Config
from agents import search_query_agent, summary_agent
from telegram_client import TelegramSearchClient
from database import MessageDatabase
from models import SearchResult, TelegramMessage
from ocr import extract_text_from_image

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize configuration
config = Config()

# Initialize bot and dispatcher
bot = Bot(token=config.bot_token)
dp = Dispatcher()

# Initialize database
db = MessageDatabase(config)

# Initialize search client
search_client = TelegramSearchClient(config, db)

# Thread pool for OCR processing (limited workers)
executor = ThreadPoolExecutor(max_workers=2)

# OCR processing queue
ocr_queue: asyncio.Queue[Tuple[Message, bytes]] = asyncio.Queue(maxsize=100)
ocr_workers = []

# Rate limiting for summary command (chat_id -> last_summary_time)
summary_cooldowns: Dict[int, datetime] = {}

# Rate limiting for ask command (chat_id -> last_ask_time)
ask_cooldowns: Dict[int, datetime] = {}


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command"""
    await message.answer(
        "🤖 <b>Welcome to Summary Bot!</b>\n\n"
        "I can help you search and summarize messages using AI.\n\n"
        "<b>📝 Commands:</b>\n"
        "• <code>/ask &lt;question&gt;</code> - Search and answer questions\n"
        "• <code>/summary</code> - Summarize last 300 messages\n"
        "• <code>/status</code> - Show bot health and queue status\n\n"
        "<b>🔍 What I can do:</b>\n"
        "• Search through text messages\n"
        "• Extract and search text from images (OCR)\n"
        "• Answer in the same language you ask\n"
        "• Provide links to original messages\n\n"
        "<b>⚠️ Important:</b>\n"
        "I only know about messages sent <b>after</b> I was added to this chat. "
        "I cannot search through old messages that were sent before I joined.\n\n"
        "<b>📱 Example:</b>\n"
        "<code>/ask what did John say about the meeting?</code>\n"
        "<code>/ask коли буде наступна зустріч?</code>",
        parse_mode="HTML"
    )


@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Show bot status"""
    queue_size = ocr_queue.qsize()
    worker_count = len([w for w in ocr_workers if not w.done()])
    
    status = (
        f"🤖 <b>Bot Status</b>\n"
        f"📸 OCR Queue: {queue_size}/100\n"
        f"👷 Active Workers: {worker_count}\n"
        f"💾 Database: Connected"
    )
    
    await message.answer(status, parse_mode="HTML")


@dp.message(Command("debug"))
async def cmd_debug(message: Message):
    """Debug search functionality"""
    # Extract query from command
    query = message.text.replace("/debug", "").strip()
    
    if not query:
        await message.answer("Usage: /debug <search query>")
        return
        
    try:
        debug_info = await db.debug_search(message.chat.id, query)
        
        response = (
            f"🐛 <b>Debug Search: '{query}'</b>\n\n"
            f"💬 Total messages in chat: {debug_info['total_messages']}\n"
            f"🔍 Vector search results: {debug_info.get('vector_search_results', 0)}\n\n"
            f"📄 <b>Sample texts:</b>\n"
        )
        
        for i, text in enumerate(debug_info['sample_texts'][:3], 1):
            response += f"{i}. {text}\n"
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Debug command error: {e}")
        await message.answer(f"Debug error: {str(e)}")


@dp.my_chat_member()
async def on_bot_added_to_chat(update: ChatMemberUpdated):
    """Handle when bot is added to a chat"""
    try:
        # Check if bot was added to the chat
        if (update.new_chat_member.status in ['member', 'administrator'] and 
            update.old_chat_member.status in ['left', 'kicked']):
            
            # Bot was added to the chat
            chat = update.chat
            
            # Only send welcome in groups/supergroups
            if chat.type in ['group', 'supergroup']:
                welcome_message = (
                    "👋 <b>Hello! I'm Summary Bot!</b>\n\n"
                    f"I've been added to <b>{chat.title}</b> and I'm ready to help!\n\n"
                    "<b>🔍 What I can do:</b>\n"
                    "• Search and summarize your chat messages\n"
                    "• Extract text from images (OCR)\n"
                    "• Answer questions in multiple languages\n\n"
                    "<b>📝 How to use:</b>\n"
                    "• <code>/ask &lt;question&gt;</code> - Ask me anything about your chat\n"
                    "• <code>/summary</code> - Get summary of recent chat activity\n"
                    "• <code>/status</code> - Check my health status\n\n"
                    "<b>⚠️ Important:</b>\n"
                    "I only know about messages sent <b>after</b> this moment. "
                    "I cannot search through old messages that were sent before I joined.\n\n"
                    "<b>🚀 Try me:</b>\n"
                    "<code>/ask what are we discussing?</code>\n"
                    "<code>/ask коли буде зустріч?</code>"
                )
                
                await bot.send_message(
                    chat_id=chat.id,
                    text=welcome_message,
                    parse_mode="HTML"
                )
                logger.info(f"Bot added to chat: {chat.title} (ID: {chat.id})")
                
    except Exception as e:
        logger.error(f"Error handling bot added to chat: {e}")


@dp.message(Command("ask"))
async def cmd_ask(message: Message):
    """Handle /ask command"""
    # Extract question from command
    question = message.text.replace("/ask", "").strip()
    
    if not question:
        await message.answer("Please provide a question after /ask command.")
        return
        
    # Get chat ID
    chat_id = message.chat.id
    current_time = datetime.now()
    
    # Check rate limiting (10 seconds cooldown)
    if chat_id in ask_cooldowns:
        last_ask = ask_cooldowns[chat_id]
        time_diff = current_time - last_ask
        cooldown_remaining = timedelta(seconds=10) - time_diff
        
        if cooldown_remaining.total_seconds() > 0:
            seconds_remaining = int(cooldown_remaining.total_seconds())
            await message.answer(
                f"⏳ Ask command is on cooldown. "
                f"Please wait {seconds_remaining}s before using it again."
            )
            return

    # Update cooldown
    ask_cooldowns[chat_id] = current_time

    try:
        # Send initial processing message that we'll edit later
        processing_msg = await message.answer("📱 Searching...")
        
        # Generate search query using Pydantic AI
        query_result = await search_query_agent.run(question)
        search_query = query_result.output.query
        
        # Search messages using database
        search_result = await search_client.search_messages(
            chat_id=chat_id,
            query=search_query
        )
        
        if not search_result.messages:
            await processing_msg.edit_text("No messages found for your query.")
            return
            
        # Format messages for summary
        messages_text = "\n\n".join([
            f"[{msg.date.strftime('%Y-%m-%d %H:%M')}] {msg.sender}: {msg.text}"
            for msg in search_result.messages
        ])
        
        # Generate summary using Pydantic AI
        summary_result = await summary_agent.run(
            f"Question: {question}\n\nMessages:\n{messages_text}"
        )
        
        # Build response with links
        response_parts = [
            f"🔍 <i>Search Query:</i> {search_query}",
            f"📊 <i>Found:</i> {search_result.total_found} messages",
            f"📝 <i>Answer:</i>\n\n{summary_result.output}",
            "\n📌 <i>Messages:</i>"
        ]
        
        # Add links to messages
        for msg in search_result.messages[:5]:  # Show first 5 messages
            if msg.chat_username:
                # Public chat - create clickable link
                link = f"https://t.me/{msg.chat_username}/{msg.id}"
                response_parts.append(
                    f"• <a href=\"{link}\">{msg.date.strftime('%d.%m %H:%M')}</a> - {msg.sender}"
                )
            else:
                # Private chat - just show info
                response_parts.append(
                    f"• {msg.date.strftime('%d.%m %H:%M')} - {msg.sender} (private chat)"
                )
        
        response = "\n".join(response_parts)
        await processing_msg.edit_text(response, parse_mode="HTML", disable_web_page_preview=True)

        logger.info(f"Ask processed for chat {chat_id}, cooldown updated")
        
    except Exception as e:
        logger.error(f"Error processing /ask command: {e}")
        await message.answer(f"An error occurred: {str(e)}")


@dp.message(Command("summary"))
async def cmd_summary(message: Message):
    """Handle /summary command - summarize last 300 messages"""
    chat_id = message.chat.id
    current_time = datetime.now()
    
    # Check rate limiting (5 minutes cooldown)
    if chat_id in summary_cooldowns:
        last_summary = summary_cooldowns[chat_id]
        time_diff = current_time - last_summary
        cooldown_remaining = timedelta(minutes=5) - time_diff
        
        if cooldown_remaining.total_seconds() > 0:
            minutes_remaining = int(cooldown_remaining.total_seconds() / 60)
            seconds_remaining = int(cooldown_remaining.total_seconds() % 60)
            await message.answer(
                f"⏳ Summary command is on cooldown. "
                f"Please wait {minutes_remaining}m {seconds_remaining}s before using it again."
            )
            return

    # Update cooldown
    summary_cooldowns[chat_id] = current_time

    try:
        # Send initial processing message
        processing_msg = await message.answer("📊 Analyzing recent messages...")
        
        # Get recent messages from database
        recent_messages = await db.get_recent_messages(chat_id, limit=300)
        
        if not recent_messages:
            await processing_msg.edit_text("No messages found in this chat.")
            return
        
        if len(recent_messages) < 2:
            await processing_msg.edit_text(f"Only {len(recent_messages)} messages found. Need at least 10 messages for a meaningful summary.")
            return
        
        # Format messages for AI analysis
        messages_text = "\n\n".join([
            f"[{msg.date.strftime('%Y-%m-%d %H:%M')}] {msg.sender}: {msg.text}"
            for msg in recent_messages
        ])
        
        # Generate summary using Pydantic AI
        summary_result = await summary_agent.run(
            f"Please provide a comprehensive summary of this chat conversation. "
            f"Include main topics discussed, key decisions made, and important information shared. "
            f"Respond in the same language as the majority of messages.\n\n"
            f"Messages:\n{messages_text}"
        )
        
        # Build response
        time_range = f"{recent_messages[0].date.strftime('%d.%m %H:%M')} - {recent_messages[-1].date.strftime('%d.%m %H:%M')}"
        
        response = (
            f"📊 <b>Chat Summary</b>\n\n"
            f"📅 <i>Period:</i> {time_range}\n"
            f"💬 <i>Messages analyzed:</i> {len(recent_messages)}\n\n"
            f"📝 <i>Summary:</i>\n\n{summary_result.output}"
        )
        
        await processing_msg.edit_text(response, parse_mode="HTML")
        
        logger.info(f"Summary generated for chat {chat_id}, cooldown updated")
        
    except Exception as e:
        logger.error(f"Error processing /summary command: {e}")
        await message.answer(f"An error occurred while generating summary: {str(e)}")


async def ocr_worker(worker_id: int):
    """OCR worker that processes images from the queue"""
    logger.info(f"OCR Worker {worker_id} started")
    
    while True:
        try:
            # Wait for an image to process (with timeout to allow graceful shutdown)
            try:
                message, image_bytes = await asyncio.wait_for(ocr_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
                
            logger.info(f"OCR Worker {worker_id} processing image from chat {message.chat.id}")
            
            # Run OCR in thread pool
            loop = asyncio.get_event_loop()
            extracted_text = await loop.run_in_executor(executor, extract_text_from_image, image_bytes)
            
            if extracted_text:
                # Get chat username if it's a public chat
                chat_username = None
                if message.chat.type in ['group', 'supergroup', 'channel']:
                    chat_username = message.chat.username
                    
                # Create message with extracted text
                text_content = f"[Image OCR] {extracted_text}"
                telegram_message = TelegramMessage(
                    id=message.message_id,
                    text=text_content,
                    sender=message.from_user.username or message.from_user.first_name or "Unknown",
                    date=message.date,
                    chat_id=message.chat.id,
                    chat_username=chat_username
                )
                await db.save_message(telegram_message)
                logger.info(f"OCR Worker {worker_id} saved {len(extracted_text)} chars")
                
            # Mark task as done
            ocr_queue.task_done()
            
        except asyncio.CancelledError:
            logger.info(f"OCR Worker {worker_id} shutting down")
            break
        except Exception as e:
            logger.error(f"OCR Worker {worker_id} error: {e}")
            await asyncio.sleep(1)  # Brief pause on error


@dp.message()
async def store_message(message: Message):
    """Store all incoming messages and images in MongoDB"""
    try:
        # Handle text messages
        if message.text and not message.text.startswith('/'):  # Don't store commands
            # Get chat username if it's a public chat
            chat_username = None
            if message.chat.type in ['group', 'supergroup', 'channel']:
                chat_username = message.chat.username
                
            telegram_message = TelegramMessage(
                id=message.message_id,
                text=message.text,
                sender=message.from_user.username or message.from_user.first_name or "Unknown",
                date=message.date,
                chat_id=message.chat.id,
                chat_username=chat_username
            )
            await db.save_message(telegram_message)
            
        # Handle photo messages
        elif message.photo:
            # Get the largest photo
            photo = message.photo[-1]
            
            # Download photo bytes
            file_info = await bot.get_file(photo.file_id)
            image_bytes = await bot.download_file(file_info.file_path)
            
            # Add to OCR queue for processing
            try:
                await asyncio.wait_for(
                    ocr_queue.put((message, image_bytes.read())), 
                    timeout=5.0
                )
                logger.info(f"Added image to OCR queue (queue size: {ocr_queue.qsize()})")
            except asyncio.TimeoutError:
                logger.warning("OCR queue is full, dropping image")
            except Exception as e:
                logger.error(f"Error adding image to OCR queue: {e}")
            
            # Also save caption if exists
            if message.caption:
                chat_username = None
                if message.chat.type in ['group', 'supergroup', 'channel']:
                    chat_username = message.chat.username
                    
                caption_message = TelegramMessage(
                    id=message.message_id,
                    text=f"[Image Caption] {message.caption}",
                    sender=message.from_user.username or message.from_user.first_name or "Unknown",
                    date=message.date,
                    chat_id=message.chat.id,
                    chat_username=chat_username
                )
                await db.save_message(caption_message)
                
    except Exception as e:
        logger.error(f"Error storing message: {e}")


async def main():
    """Main function to run the bot"""
    global ocr_workers
    
    # Setup database indexes
    await db.setup_indexes()
    
    # Start OCR workers
    num_workers = 2
    for i in range(num_workers):
        worker = asyncio.create_task(ocr_worker(i + 1))
        ocr_workers.append(worker)
    
    logger.info(f"Started {num_workers} OCR workers")
    
    try:
        # Start polling
        await dp.start_polling(bot)
    finally:
        # Clean up
        logger.info("Shutting down...")
        
        # Cancel OCR workers
        for worker in ocr_workers:
            worker.cancel()
        
        # Wait for workers to finish
        if ocr_workers:
            await asyncio.gather(*ocr_workers, return_exceptions=True)
        
        # Wait for remaining OCR tasks to complete
        if not ocr_queue.empty():
            logger.info(f"Waiting for {ocr_queue.qsize()} remaining OCR tasks...")
            await ocr_queue.join()
        
        # Shutdown thread pool
        executor.shutdown(wait=True)
        
        # Close database and bot
        await db.close()
        await bot.session.close()
        
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())