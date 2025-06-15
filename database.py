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
                
    async def get_recent_messages(self, chat_id: int, limit: int = 300) -> List[TelegramMessage]:
        """Get the most recent messages from a chat"""
        messages = []
        
        cursor = self.messages_collection.find(
            {"chat_id": chat_id}
        ).sort("date", -1).limit(limit)
        
        async for doc in cursor:
            messages.append(TelegramMessage(
                id=doc["message_id"],
                text=doc["text"],
                sender=doc["sender"],
                date=doc["date"],
                chat_id=doc["chat_id"],
                chat_username=doc.get("chat_username")
            ))
        
        # Return in chronological order (oldest first)
        return list(reversed(messages))
    
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
        """Search messages using regex with OCR error handling"""
        messages = []
        
        # Create fuzzy patterns to handle OCR errors
        def create_fuzzy_patterns(text):
            # Common OCR character substitutions for Ukrainian
            substitutions = {
                'з': '[зц]',  # з can be misread as ц
                'ц': '[цз]',  # ц can be misread as з  
                'и': '[иі]',  # и can be misread as і
                'і': '[іи]',  # і can be misread as и
                'а': '[ао]',  # а can be misread as о
                'о': '[оа]',  # о can be misread as а
                'е': '[ее]',  # handle е variations
                'н': '[нп]',  # н can be misread as п
                'п': '[пн]',  # п can be misread as н
                'р': '[рp]',  # р can be misread as p
                'у': '[уy]',  # у can be misread as y
            }
            
            patterns = []
            
            # Add original patterns
            patterns.extend([text, text.lower(), text.upper(), text.capitalize()])
            
            # Create fuzzy pattern with substitutions
            fuzzy_text = text.lower()
            for original, replacement in substitutions.items():
                fuzzy_text = fuzzy_text.replace(original, replacement)
            
            patterns.append(fuzzy_text)
            
            # Also try partial word matching (useful for longer words)
            if len(text) > 4:
                # Create pattern that matches if most characters are present
                core_text = text[1:-1].lower()  # Remove first and last char
                patterns.append(f".*{core_text}.*")
            
            return patterns
        
        # Generate search patterns with OCR error handling
        search_patterns = create_fuzzy_patterns(query)
        
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
        ).sort("date", -1).limit(5)  # Get latest 5 messages
        
        async for doc in sample_cursor:
            text = doc.get("text", "")
            # Show first 200 chars instead of 100 for better debugging
            sample_text = text[:200] + "..." if len(text) > 200 else text
            result["sample_texts"].append(f"ID: {doc.get('message_id', 'unknown')} - {sample_text}")
        
        return result
        
    async def close(self):
        """Close the database connection"""
        self.client.close()