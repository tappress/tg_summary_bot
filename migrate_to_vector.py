#!/usr/bin/env python3
"""
Migration script to transfer data from MongoDB to ChromaDB vector database
"""

import asyncio
import logging
from datetime import datetime
from config import Config
from database import MessageDatabase
from vector_database import VectorDatabase
from models import TelegramMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate_data():
    """Migrate all messages from MongoDB to ChromaDB"""
    config = Config()
    
    # Initialize databases
    mongo_db = MessageDatabase(config)
    vector_db = VectorDatabase(config)
    
    try:
        logger.info("Starting migration from MongoDB to ChromaDB...")
        
        # Get all unique chat IDs from MongoDB
        pipeline = [{"$group": {"_id": "$chat_id"}}]
        chat_ids = []
        
        async for doc in mongo_db.messages_collection.aggregate(pipeline):
            chat_ids.append(doc["_id"])
        
        logger.info(f"Found {len(chat_ids)} chats to migrate")
        
        total_messages = 0
        migrated_messages = 0
        
        for chat_id in chat_ids:
            logger.info(f"Migrating chat {chat_id}...")
            
            # Get all messages from this chat
            cursor = mongo_db.messages_collection.find({"chat_id": chat_id})
            chat_message_count = 0
            
            async for doc in cursor:
                try:
                    # Convert to TelegramMessage
                    message = TelegramMessage(
                        id=doc["message_id"],
                        text=doc["text"],
                        sender=doc["sender"],
                        date=doc["date"],
                        chat_id=doc["chat_id"],
                        chat_username=doc.get("chat_username")
                    )
                    
                    # Save to vector database
                    await vector_db.save_message(message)
                    chat_message_count += 1
                    migrated_messages += 1
                    
                    if chat_message_count % 100 == 0:
                        logger.info(f"  Migrated {chat_message_count} messages from chat {chat_id}")
                        
                except Exception as e:
                    logger.error(f"Error migrating message {doc.get('message_id', 'unknown')}: {e}")
                    continue
            
            total_messages += chat_message_count
            logger.info(f"Completed chat {chat_id}: {chat_message_count} messages")
        
        logger.info(f"Migration completed: {migrated_messages}/{total_messages} messages migrated")
        
        # Verify migration
        logger.info("Verifying migration...")
        for chat_id in chat_ids[:3]:  # Check first 3 chats
            mongo_count = await mongo_db.messages_collection.count_documents({"chat_id": chat_id})
            vector_count = await vector_db.get_message_count(chat_id)
            logger.info(f"Chat {chat_id}: MongoDB={mongo_count}, ChromaDB={vector_count}")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        await mongo_db.close()
        vector_db.close()


if __name__ == "__main__":
    asyncio.run(migrate_data())