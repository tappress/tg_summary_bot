from typing import List, Optional
from datetime import datetime
from config import Config
from models import TelegramMessage, SearchResult
from database import MessageDatabase


class TelegramSearchClient:
    def __init__(self, config: Config, db: MessageDatabase):
        self.config = config
        self.db = db
        
    async def search_messages(
        self, 
        chat_id: int, 
        query: str, 
        limit: Optional[int] = None
    ) -> SearchResult:
        """Search messages in MongoDB"""
        limit = limit or self.config.max_messages_to_fetch
        
        # Search messages using vector database
        messages = await self.db.search_messages(chat_id, query, limit)
        
        return SearchResult(
            query=query,
            messages=messages,
            total_found=len(messages)
        )