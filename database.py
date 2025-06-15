from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, TEXT
from datetime import datetime
from typing import List, Optional
from config import Config
from models import TelegramMessage
from vector_database import VectorDatabase


class MessageDatabase:
    def __init__(self, config: Config):
        # Keep MongoDB for migration purposes
        self.client = AsyncIOMotorClient(config.mongodb_url)
        self.db = self.client[config.mongodb_database]
        self.messages_collection = self.db.messages
        
        # Initialize vector database
        self.vector_db = VectorDatabase(config)
        
    async def setup_indexes(self):
        """Create necessary indexes for efficient searching"""
        # Text index for message search
        await self.messages_collection.create_index([("text", TEXT)])
        # Compound index for chat_id and date
        await self.messages_collection.create_index([("chat_id", ASCENDING), ("date", ASCENDING)])
        # Index for message_id to avoid duplicates
        await self.messages_collection.create_index([("chat_id", ASCENDING), ("message_id", ASCENDING)], unique=True)
        
    async def save_message(self, message: TelegramMessage):
        """Save a message to the vector database"""
        await self.vector_db.save_message(message)
                
    async def get_recent_messages(self, chat_id: int, limit: int = 300) -> List[TelegramMessage]:
        """Get the most recent messages from a chat"""
        return await self.vector_db.get_recent_messages(chat_id, limit)
    
    async def search_messages(self, chat_id: int, query: str, limit: int = 10) -> List[TelegramMessage]:
        """Search messages using vector similarity"""
        return await self.vector_db.search_messages(chat_id, query, limit)
    
    
    async def debug_search(self, chat_id: int, query: str) -> dict:
        """Debug search using vector database"""
        return await self.vector_db.debug_search(chat_id, query)
        
    async def close(self):
        """Close the database connections"""
        self.client.close()
        self.vector_db.close()