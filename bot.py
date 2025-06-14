import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Tuple
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ContentType
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


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command"""
    await message.answer(
        "🤖 **Welcome to Summary Bot!**\n\n"
        "I can help you search and summarize messages using AI.\n\n"
        "**📝 Commands:**\n"
        "• `/ask <question>` - Search and answer questions\n"
        "• `/status` - Show bot health and queue status\n\n"
        "**🔍 What I can do:**\n"
        "• Search through text messages\n"
        "• Extract and search text from images (OCR)\n"
        "• Answer in the same language you ask\n"
        "• Provide links to original messages\n\n"
        "**⚠️ Important:**\n"
        "I only know about messages sent **after** I was added to this chat. "
        "I cannot search through old messages that were sent before I joined.\n\n"
        "**📱 Example:**\n"
        "`/ask what did John say about the meeting?`\n"
        "`/ask коли буде наступна зустріч?`",
        parse_mode="Markdown"
    )


@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Show bot status"""
    queue_size = ocr_queue.qsize()
    worker_count = len([w for w in ocr_workers if not w.done()])
    
    status = (
        f"🤖 **Bot Status**\n"
        f"📸 OCR Queue: {queue_size}/100\n"
        f"👷 Active Workers: {worker_count}\n"
        f"💾 Database: Connected"
    )
    
    await message.answer(status, parse_mode="Markdown")


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
    
    try:
        # Generate search query using Pydantic AI
        await message.answer("🔍 Generating search query...")
        query_result = await search_query_agent.run(question)
        search_query = query_result.output.query
        
        await message.answer(f"📱 Searching for: *{search_query}*", parse_mode="Markdown")
        
        # Search messages using Pyrogram
        search_result = await search_client.search_messages(
            chat_id=chat_id,
            query=search_query
        )
        
        if not search_result.messages:
            await message.answer("No messages found for your query.")
            return
            
        # Format messages for summary
        messages_text = "\n\n".join([
            f"[{msg.date.strftime('%Y-%m-%d %H:%M')}] {msg.sender}: {msg.text}"
            for msg in search_result.messages
        ])
        
        # Generate summary using Pydantic AI
        await message.answer("📝 Generating summary...")
        summary_result = await summary_agent.run(
            f"Question: {question}\n\nMessages:\n{messages_text}"
        )
        
        # Build response with links
        response_parts = [
            f"🔍 *Search Query:* {search_query}",
            f"📊 *Found:* {search_result.total_found} messages",
            f"📝 *Answer:*\n\n{summary_result.output}",
            "\n📌 *Messages:*"
        ]
        
        # Add links to messages
        for msg in search_result.messages[:5]:  # Show first 5 messages
            if msg.chat_username:
                # Public chat - create clickable link
                link = f"https://t.me/{msg.chat_username}/{msg.id}"
                response_parts.append(
                    f"• [{msg.date.strftime('%d.%m %H:%M')}]({link}) - {msg.sender}"
                )
            else:
                # Private chat - just show info
                response_parts.append(
                    f"• {msg.date.strftime('%d.%m %H:%M')} - {msg.sender} (private chat)"
                )
        
        response = "\n".join(response_parts)
        await message.answer(response, parse_mode="Markdown", disable_web_page_preview=True)
        
    except Exception as e:
        logger.error(f"Error processing /ask command: {e}")
        await message.answer(f"An error occurred: {str(e)}")


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