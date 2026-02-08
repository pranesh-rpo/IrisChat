import sqlite3
import logging
from datetime import datetime

DB_FILE = "chat_history.db"

def init_db():
    """Initialize the database table if it doesn't exist."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sender_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Attempt to add sender_name column if it doesn't exist (migration for existing DBs)
        try:
            cursor.execute('ALTER TABLE messages ADD COLUMN sender_name TEXT')
        except sqlite3.OperationalError:
            # Column likely already exists
            pass

        # Create index for faster retrieval by chat_id
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_chat_id ON messages(chat_id)
        ''')
        conn.commit()
        conn.close()
        logging.info("Database initialized successfully.")
    except Exception as e:
        logging.error(f"Database initialization error: {e}")

def add_message(chat_id, role, content, sender_name=None):
    """Add a message to the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO messages (chat_id, role, content, sender_name)
            VALUES (?, ?, ?, ?)
        ''', (chat_id, role, content, sender_name))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error adding message to DB: {e}")

def get_history(chat_id, limit=20):
    """Retrieve the last N messages for a chat_id."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get last N messages (we need to order by id DESC to get latest, then reverse back)
        cursor.execute('''
            SELECT role, content, sender_name FROM (
                SELECT role, content, sender_name, id 
                FROM messages 
                WHERE chat_id = ? 
                ORDER BY id DESC 
                LIMIT ?
            ) ORDER BY id ASC
        ''', (chat_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        # Convert to list of dicts
        history = [{"role": row["role"], "content": row["content"], "sender_name": row["sender_name"]} for row in rows]
        return history
    except Exception as e:
        logging.error(f"Error retrieving history from DB: {e}")
        return []

def clear_history(chat_id):
    """Clear history for a specific chat_id."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM messages WHERE chat_id = ?', (chat_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error clearing history from DB: {e}")
