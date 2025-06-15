import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from config import Config
from models import TelegramMessage
import logging

logger = logging.getLogger(__name__)


class VectorDatabase:
    def __init__(self, config: Config):
        self.config = config
        
        # Initialize ChromaDB client
        self.client = chromadb.HttpClient(
            host=config.chroma_host,
            port=config.chroma_port,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Initialize embedding model
        self.embedding_model = SentenceTransformer(config.embedding_model)
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="telegram_messages",
            metadata={"hnsw:space": "cosine"}
        )
        
    def _create_document_id(self, message: TelegramMessage) -> str:
        """Create unique document ID from message"""
        return f"{message.chat_id}_{message.id}"
    
    def _create_metadata(self, message: TelegramMessage) -> dict:
        """Create metadata for the message"""
        # Ensure date is timezone-aware
        msg_date = message.date
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
            
        return {
            "message_id": message.id,
            "chat_id": message.chat_id,
            "chat_username": message.chat_username or "",
            "sender": message.sender,
            "date": msg_date.isoformat(),
            "date_timestamp": int(msg_date.timestamp()),  # Numeric timestamp for filtering
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def save_message(self, message: TelegramMessage):
        """Save a message to the vector database"""
        try:
            # Skip empty messages
            if not message.text.strip():
                return
                
            doc_id = self._create_document_id(message)
            
            # Check if document already exists
            try:
                existing = self.collection.get(ids=[doc_id])
                if existing['ids']:
                    logger.debug(f"Message {doc_id} already exists, skipping")
                    return
            except Exception:
                # Document doesn't exist, continue with insertion
                pass
            
            # Create embedding
            embedding = self.embedding_model.encode(message.text).tolist()
            
            # Add to collection
            self.collection.add(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[message.text],
                metadatas=[self._create_metadata(message)]
            )
            
            logger.debug(f"Saved message {doc_id} to vector database")
            
        except Exception as e:
            logger.error(f"Error saving message to vector database: {e}")
    
    async def search_messages(self, chat_id: int, query: str, limit: int = 10) -> List[TelegramMessage]:
        """Search messages using vector similarity"""
        try:
            # Create query embedding
            query_embedding = self.embedding_model.encode(query).tolist()
            
            # Search in collection
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(limit, self.config.vector_search_limit),
                where={"chat_id": chat_id}
            )
            
            messages = []
            
            # Convert results to TelegramMessage objects
            if results['ids'] and results['ids'][0]:
                for i, doc_id in enumerate(results['ids'][0]):
                    metadata = results['metadatas'][0][i]
                    document = results['documents'][0][i]
                    
                    # Parse date and ensure it's timezone-aware
                    msg_date = datetime.fromisoformat(metadata['date'])
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                    
                    message = TelegramMessage(
                        id=metadata['message_id'],
                        text=document,
                        sender=metadata['sender'],
                        date=msg_date,
                        chat_id=metadata['chat_id'],
                        chat_username=metadata['chat_username'] if metadata['chat_username'] else None
                    )
                    messages.append(message)
            
            logger.info(f"Vector search found {len(messages)} messages for query: {query}")
            return messages
            
        except Exception as e:
            logger.error(f"Error searching messages in vector database: {e}")
            return []
    
    async def get_recent_messages(self, chat_id: int, limit: int = 300, days_back: int = 7) -> List[TelegramMessage]:
        """Get recent messages from chat (sorted by date)
        
        Args:
            chat_id: The chat ID to get messages from
            limit: Maximum number of messages to return
            days_back: How many days back to look for messages (default: 7)
        """
        try:
            # Calculate the timestamp threshold (in seconds)
            date_threshold = datetime.now(timezone.utc) - timedelta(days=days_back)
            timestamp_threshold = int(date_threshold.timestamp())
            
            # First try to get messages from the last N days using timestamp filter
            # Check if date_timestamp field exists in metadata
            results = self.collection.get(
                where={
                    "$and": [
                        {"chat_id": chat_id},
                        {"date_timestamp": {"$gte": timestamp_threshold}}
                    ]
                },
                include=["documents", "metadatas"]
            )
            
            messages = []
            
            if results['ids']:
                for i, doc_id in enumerate(results['ids']):
                    metadata = results['metadatas'][i]
                    document = results['documents'][i]
                    
                    # Parse date and ensure it's timezone-aware
                    msg_date = datetime.fromisoformat(metadata['date'])
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                    
                    message = TelegramMessage(
                        id=metadata['message_id'],
                        text=document,
                        sender=metadata['sender'],
                        date=msg_date,
                        chat_id=metadata['chat_id'],
                        chat_username=metadata['chat_username'] if metadata['chat_username'] else None
                    )
                    messages.append(message)
            
            # Sort by date (newest first) and limit
            messages.sort(key=lambda x: x.date, reverse=True)
            
            # If we didn't get enough messages from the time filter, fall back to getting all
            if len(messages) < limit:
                logger.info(f"Only found {len(messages)} messages in last {days_back} days, fetching more...")
                # Get all messages for chat
                all_results = self.collection.get(
                    where={"chat_id": chat_id},
                    include=["documents", "metadatas"]
                )
                
                all_messages = []
                if all_results['ids']:
                    for i, doc_id in enumerate(all_results['ids']):
                        metadata = all_results['metadatas'][i]
                        document = all_results['documents'][i]
                        
                        # Parse date and ensure it's timezone-aware
                        msg_date = datetime.fromisoformat(metadata['date'])
                        if msg_date.tzinfo is None:
                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                        
                        message = TelegramMessage(
                            id=metadata['message_id'],
                            text=document,
                            sender=metadata['sender'],
                            date=msg_date,
                            chat_id=metadata['chat_id'],
                            chat_username=metadata['chat_username'] if metadata['chat_username'] else None
                        )
                        all_messages.append(message)
                
                # Sort by date and take the limit
                all_messages.sort(key=lambda x: x.date, reverse=True)
                messages = all_messages[:limit]
            else:
                # We have enough messages, just limit them
                messages = messages[:limit]
            
            # Return in chronological order (oldest first) for summary
            return list(reversed(messages))
            
        except Exception as e:
            logger.error(f"Error getting recent messages from vector database: {e}")
            # Fallback to simple approach if the complex query fails
            try:
                logger.info("Falling back to simple query without date filter")
                results = self.collection.get(
                    where={"chat_id": chat_id},
                    include=["documents", "metadatas"]
                )
                
                messages = []
                if results['ids']:
                    for i, doc_id in enumerate(results['ids']):
                        metadata = results['metadatas'][i]
                        document = results['documents'][i]
                        
                        # Handle legacy messages without date_timestamp
                        # Parse date and ensure it's timezone-aware
                        msg_date = datetime.fromisoformat(metadata['date'])
                        if msg_date.tzinfo is None:
                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                        
                        message = TelegramMessage(
                            id=metadata['message_id'],
                            text=document,
                            sender=metadata['sender'],
                            date=msg_date,
                            chat_id=metadata['chat_id'],
                            chat_username=metadata['chat_username'] if metadata['chat_username'] else None
                        )
                        messages.append(message)
                
                # Sort by date (newest first) and limit
                messages.sort(key=lambda x: x.date, reverse=True)
                messages = messages[:limit]
                
                # Return in chronological order (oldest first)
                return list(reversed(messages))
            except Exception as fallback_error:
                logger.error(f"Fallback query also failed: {fallback_error}")
                return []
    
    async def get_message_count(self, chat_id: int) -> int:
        """Get total message count for a chat"""
        try:
            results = self.collection.get(
                where={"chat_id": chat_id},
                include=[]  # Only get count, not data
            )
            return len(results['ids']) if results['ids'] else 0
        except Exception as e:
            logger.error(f"Error getting message count: {e}")
            return 0
    
    async def debug_search(self, chat_id: int, query: str) -> dict:
        """Debug search to see what's happening"""
        try:
            # Get total messages in chat
            total_messages = await self.get_message_count(chat_id)
            
            # Perform vector search
            search_results = await self.search_messages(chat_id, query, limit=20)
            
            # Get sample messages
            recent_messages = await self.get_recent_messages(chat_id, limit=5)
            sample_texts = []
            for msg in recent_messages:
                text = msg.text[:200] + "..." if len(msg.text) > 200 else msg.text
                sample_texts.append(f"ID: {msg.id} - {text}")
            
            return {
                "chat_id": chat_id,
                "query": query,
                "total_messages": total_messages,
                "vector_search_results": len(search_results),
                "sample_texts": sample_texts
            }
            
        except Exception as e:
            logger.error(f"Error in debug search: {e}")
            return {
                "chat_id": chat_id,
                "query": query,
                "total_messages": 0,
                "vector_search_results": 0,
                "sample_texts": [f"Error: {str(e)}"]
            }
    
    def close(self):
        """Close connections"""
        # ChromaDB HTTP client doesn't need explicit closing
        pass