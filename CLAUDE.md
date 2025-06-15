# Telegram Summary Bot

This is a Telegram bot that uses Pydantic AI with DeepSeek LLM to intelligently search and summarize messages in Telegram chats. It uses vector embeddings for semantic search and includes OCR capabilities to extract text from images.

## Architecture

- **aiogram**: Bot framework for handling Telegram commands
- **Pydantic AI**: Agent framework for LLM interactions with DeepSeek
- **ChromaDB**: Vector database for semantic search using embeddings
- **SentenceTransformers**: Creates embeddings for semantic similarity search
- **EasyOCR**: Text extraction from images with better multilingual support
- **pydantic-settings**: Configuration management with environment variables

## Key Components

1. **config.py**: Configuration using pydantic-settings, loads from .env file
2. **models.py**: Pydantic models for search queries and results
3. **agents.py**: Pydantic AI agents for query generation and summarization
4. **database.py**: Vector database wrapper for ChromaDB integration
5. **vector_database.py**: ChromaDB implementation with sentence transformers
6. **telegram_client.py**: Local search client using vector database
7. **migrate_to_vector.py**: Migration script from MongoDB to ChromaDB
8. **ocr.py**: OCR functionality using EasyOCR
9. **bot.py**: Main bot implementation with commands

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

1. **Message Storage**: All text messages and images are stored in ChromaDB as vector embeddings
2. **OCR Processing**: Images are processed in background queue (2 workers max)
3. **Search**: User sends `/ask <question>` to the bot
4. **Query Generation**: Pydantic AI generates search query from natural language
5. **Vector Search**: ChromaDB performs semantic similarity search using embeddings
6. **Summarization**: Pydantic AI summarizes results in user's language
7. **Response**: Bot returns answer with links to original messages

## Queue System

- **OCR Queue**: Max 100 images, processes 2 at a time
- **Workers**: 2 asyncio workers + 2 thread pool workers
- **Backpressure**: Drops images if queue is full
- **Graceful Shutdown**: Waits for pending OCR tasks

## Setup

1. Start databases: `docker-compose up -d` (starts both MongoDB and ChromaDB)
2. Install Python dependencies: `uv sync` (downloads models automatically)
3. Copy `.env.example` to `.env` and fill in the required values
4. Migrate existing data: `uv run python migrate_to_vector.py` (if upgrading from MongoDB)
5. Run the bot: `uv run python bot.py`

## Migration from MongoDB

If you have existing MongoDB data, run the migration script:
```bash
uv run python migrate_to_vector.py
```

This will:
- Transfer all messages from MongoDB to ChromaDB
- Create vector embeddings for each message
- Verify the migration was successful

## Important Notes

- Bot stores ALL messages as vector embeddings in ChromaDB for semantic search
- Since bots can't use Telegram's `messages.Search` API, we use local storage
- OCR processing happens in background to avoid blocking the bot
- Vector search provides better results for multilingual and OCR text
- DeepSeek is configured as the LLM provider through Pydantic AI
- Embedding model (all-MiniLM-L6-v2) supports Ukrainian, Russian, and English