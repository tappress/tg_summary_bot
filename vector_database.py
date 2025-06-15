import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from datetime import datetime
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
        return {
            "message_id": message.id,
            "chat_id": message.chat_id,
            "chat_username": message.chat_username or "",
            "sender": message.sender,
            "date": message.date.isoformat(),
            "created_at": datetime.utcnow().isoformat()
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
                    
                    message = TelegramMessage(
                        id=metadata['message_id'],
                        text=document,
                        sender=metadata['sender'],
                        date=datetime.fromisoformat(metadata['date']),
                        chat_id=metadata['chat_id'],
                        chat_username=metadata['chat_username'] if metadata['chat_username'] else None
                    )
                    messages.append(message)
            
            logger.info(f"Vector search found {len(messages)} messages for query: {query}")
            return messages
            
        except Exception as e:
            logger.error(f"Error searching messages in vector database: {e}")
            return []
    
    async def get_recent_messages(self, chat_id: int, limit: int = 300) -> List[TelegramMessage]:
        """Get recent messages from chat (sorted by date)"""
        try:
            # Get all messages for chat
            results = self.collection.get(
                where={"chat_id": chat_id},
                include=["documents", "metadatas"]
            )
            
            messages = []
            
            if results['ids']:
                for i, doc_id in enumerate(results['ids']):
                    metadata = results['metadatas'][i]
                    document = results['documents'][i]
                    
                    message = TelegramMessage(
                        id=metadata['message_id'],
                        text=document,
                        sender=metadata['sender'],
                        date=datetime.fromisoformat(metadata['date']),
                        chat_id=metadata['chat_id'],
                        chat_username=metadata['chat_username'] if metadata['chat_username'] else None
                    )
                    messages.append(message)
            
            # Sort by date (newest first) and limit
            messages.sort(key=lambda x: x.date, reverse=True)
            messages = messages[:limit]
            
            # Return in chronological order (oldest first)
            return list(reversed(messages))
            
        except Exception as e:
            logger.error(f"Error getting recent messages from vector database: {e}")
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