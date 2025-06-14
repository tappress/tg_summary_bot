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
        """Search messages in the database with improved search logic"""
        messages = []
        
        # First try exact text search
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
        
        # If no results, try case-insensitive regex search as fallback
        if not messages:
            messages = await self.search_messages_regex(chat_id, query, limit)
            
        return messages
    
    async def search_messages_regex(self, chat_id: int, query: str, limit: int = 10) -> List[TelegramMessage]:
        """Search messages using regex (fallback if text search doesn't work well)"""
        messages = []
        
        # Try multiple search patterns for better matching
        search_patterns = [
            query,  # Original query
            query.lower(),  # Lowercase
            query.upper(),  # Uppercase
            query.capitalize(),  # Capitalized
        ]
        
        # Remove duplicates while preserving order
        unique_patterns = []
        for pattern in search_patterns:
            if pattern not in unique_patterns:
                unique_patterns.append(pattern)
        
        # Try each pattern until we find results
        for pattern in unique_patterns:
            cursor = self.messages_collection.find(
                {
                    "chat_id": chat_id,
                    "text": {"$regex": pattern, "$options": "i"}
                }
            ).sort("date", -1).limit(limit)
            
            pattern_messages = []
            async for doc in cursor:
                pattern_messages.append(TelegramMessage(
                    id=doc["message_id"],
                    text=doc["text"],
                    sender=doc["sender"],
                    date=doc["date"],
                    chat_id=doc["chat_id"],
                    chat_username=doc.get("chat_username")
                ))
            
            if pattern_messages:
                messages.extend(pattern_messages)
                break  # Found results, stop trying other patterns
                
        return messages
    
    async def debug_search(self, chat_id: int, query: str) -> dict:
        """Debug search to see what's happening"""
        result = {
            "chat_id": chat_id,
            "query": query,
            "total_messages": 0,
            "text_search_results": 0,
            "regex_search_results": 0,
            "sample_texts": []
        }
        
        # Count total messages in chat
        total = await self.messages_collection.count_documents({"chat_id": chat_id})
        result["total_messages"] = total
        
        # Test text search
        text_cursor = self.messages_collection.find(
            {"chat_id": chat_id, "$text": {"$search": query}}
        )
        result["text_search_results"] = len(await text_cursor.to_list(length=None))
        
        # Test regex search
        regex_cursor = self.messages_collection.find(
            {"chat_id": chat_id, "text": {"$regex": query, "$options": "i"}}
        )
        result["regex_search_results"] = len(await regex_cursor.to_list(length=None))
        
        # Get sample texts to see what we have
        sample_cursor = self.messages_collection.find(
            {"chat_id": chat_id}
        ).limit(3)
        
        async for doc in sample_cursor:
            result["sample_texts"].append(doc.get("text", "")[:100] + "...")
        
        return result
        
    async def close(self):
        """Close the database connection"""
        self.client.close()