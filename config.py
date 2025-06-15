from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Config(BaseSettings):
    bot_token: str = Field(..., description="Telegram Bot API token")
    deepseek_api_key: str = Field(..., description="DeepSeek API key")
    deepseek_model: str = Field(default="deepseek-chat", description="DeepSeek model name")
    max_messages_to_fetch: int = Field(default=10, description="Maximum messages to fetch from search")
    
    # MongoDB settings (kept for migration)
    mongodb_url: str = Field(default="mongodb://admin:password@localhost:27017", description="MongoDB connection URL")
    mongodb_database: str = Field(default="telegram_bot", description="MongoDB database name")
    
    # Vector database settings
    chroma_host: str = Field(default="localhost", description="ChromaDB host")
    chroma_port: int = Field(default=8000, description="ChromaDB port")
    embedding_model: str = Field(default="all-MiniLM-L6-v2", description="Sentence transformer model for embeddings")
    vector_search_limit: int = Field(default=10, description="Maximum results to return from vector search")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"