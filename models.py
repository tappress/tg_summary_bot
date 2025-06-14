from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class SearchQuery(BaseModel):
    """Model for search query generation"""
    query: str = Field(..., description="Search query to find relevant messages in Telegram chat")
    
    
class TelegramMessage(BaseModel):
    """Model for a Telegram message"""
    id: int
    text: str
    sender: str
    date: datetime
    chat_id: int
    chat_username: Optional[str] = None
    
    
class SearchResult(BaseModel):
    """Model for search results"""
    query: str
    messages: List[TelegramMessage]
    total_found: int
    summary: Optional[str] = None