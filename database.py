from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, TEXT
from datetime import datetime
from typing import List, Optional
from config import Config
from models import TelegramMessage


class MessageDatabase:
    def __init__(self, config: Config):
        self.client = AsyncIOMotorClient(config.mongodb_url)
        self.db = self.client[config.mongodb_database]
        self.messages_collection = self.db.messages
        
    async def setup_indexes(self):
        """Create necessary indexes for efficient searching"""
        # Text index for message search
        await self.messages_collection.create_index([("text", TEXT)])
        # Compound index for chat_id and date
        await self.messages_collection.create_index([("chat_id", ASCENDING), ("date", ASCENDING)])
        # Index for message_id to avoid duplicates
        await self.messages_collection.create_index([("chat_id", ASCENDING), ("message_id", ASCENDING)], unique=True)
        
    async def save_message(self, message: TelegramMessage):
        """Save a message to the database"""
        try:
            await self.messages_collection.insert_one({
                "message_id": message.id,
                "chat_id": message.chat_id,
                "chat_username": message.chat_username,
                "text": message.text,
                "sender": message.sender,
                "date": message.date,
                "created_at": datetime.utcnow()
            })
        except Exception as e:
            if "duplicate key error" not in str(e):
                print(f"Error saving message: {e}")
                
    async def search_messages(self, chat_id: int, query: str, limit: int = 10) -> List[TelegramMessage]:
        """Search messages in the database"""
        messages = []
        
        # Use text search for the query
        cursor = self.messages_collection.find(
            {
                "chat_id": chat_id,
                "$text": {"$search": query}
            },
            {"score": {"$meta": "textScore"}}
        ).sort([("score", {"$meta": "textScore"})]).limit(limit)
        
        async for doc in cursor:
            messages.append(TelegramMessage(
                id=doc["message_id"],
                text=doc["text"],
                sender=doc["sender"],
                date=doc["date"],
                chat_id=doc["chat_id"],
                chat_username=doc.get("chat_username")
            ))
            
        return messages
    
    async def search_messages_regex(self, chat_id: int, query: str, limit: int = 10) -> List[TelegramMessage]:
        """Search messages using regex (fallback if text search doesn't work well)"""
        messages = []
        
        # Case-insensitive regex search
        cursor = self.messages_collection.find(
            {
                "chat_id": chat_id,
                "text": {"$regex": query, "$options": "i"}
            }
        ).sort("date", -1).limit(limit)
        
        async for doc in cursor:
            messages.append(TelegramMessage(
                id=doc["message_id"],
                text=doc["text"],
                sender=doc["sender"],
                date=doc["date"],
                chat_id=doc["chat_id"]
            ))
            
        return messages
        
    async def close(self):
        """Close the database connection"""
        self.client.close()