# Telegram Summary Bot

This is a Telegram bot that uses Pydantic AI with DeepSeek LLM to intelligently search and summarize messages in Telegram chats. It also includes OCR capabilities to extract text from images.

## Architecture

- **aiogram**: Bot framework for handling Telegram commands
- **Pydantic AI**: Agent framework for LLM interactions with DeepSeek
- **MongoDB**: Database for storing all messages and extracted text
- **EasyOCR**: Text extraction from images with better multilingual support
- **pydantic-settings**: Configuration management with environment variables

## Key Components

1. **config.py**: Configuration using pydantic-settings, loads from .env file
2. **models.py**: Pydantic models for search queries and results
3. **agents.py**: Pydantic AI agents for query generation and summarization
4. **database.py**: MongoDB integration for message storage and search
5. **telegram_client.py**: Local search client using MongoDB
6. **ocr.py**: OCR functionality using EasyOCR
7. **bot.py**: Main bot implementation with commands

## Features

### Text Search & Summarization
- `/ask <question>` - Search and summarize messages
- Responds in the same language as the question
- Shows clickable links to original messages (for public chats)
- Searches both text messages and OCR-extracted text

### OCR Processing
- Automatically extracts text from images
- Supports English, Ukrainian, and Russian
- Queue-based processing to prevent server overload
- Background processing using thread pools

### Bot Commands
- `/start` - Welcome message and instructions
- `/ask <question>` - Search and answer questions
- `/status` - Show OCR queue status and bot health

## How It Works

1. **Message Storage**: All text messages and images are stored in MongoDB
2. **OCR Processing**: Images are processed in background queue (2 workers max)
3. **Search**: User sends `/ask <question>` to the bot
4. **Query Generation**: Pydantic AI generates search query from natural language
5. **Local Search**: MongoDB full-text search finds relevant messages
6. **Summarization**: Pydantic AI summarizes results in user's language
7. **Response**: Bot returns answer with links to original messages

## Queue System

- **OCR Queue**: Max 100 images, processes 2 at a time
- **Workers**: 2 asyncio workers + 2 thread pool workers
- **Backpressure**: Drops images if queue is full
- **Graceful Shutdown**: Waits for pending OCR tasks

## Setup

1. Start MongoDB: `docker-compose up -d`
2. Install Python dependencies: `uv sync` (EasyOCR downloads models automatically)
3. Copy `.env.example` to `.env` and fill in the required values
4. Run the bot: `uv run python bot.py`

## Important Notes

- Bot stores ALL messages it sees in MongoDB for local searching
- Since bots can't use Telegram's `messages.Search` API, we use local storage
- OCR processing happens in background to avoid blocking the bot
- Text search uses MongoDB's full-text indexing for fast queries
- DeepSeek is configured as the LLM provider through Pydantic AI