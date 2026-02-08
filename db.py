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
        
        # Create chat_settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                mode TEXT DEFAULT 'normal',
                persona_prompt TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
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

def update_chat_mode(chat_id, mode, persona_prompt=None):
    """Update the chat mode and persona prompt."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO chat_settings (chat_id, mode, persona_prompt, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                mode=excluded.mode,
                persona_prompt=excluded.persona_prompt,
                updated_at=CURRENT_TIMESTAMP
        ''', (chat_id, mode, persona_prompt))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error updating chat mode: {e}")

def get_chat_settings(chat_id):
    """Get the current settings for a chat."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT mode, persona_prompt FROM chat_settings WHERE chat_id = ?', (chat_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {"mode": row["mode"], "persona_prompt": row["persona_prompt"]}
        else:
            return {"mode": "normal", "persona_prompt": None}
    except Exception as e:
        logging.error(f"Error retrieving chat settings: {e}")
        return {"mode": "normal", "persona_prompt": None}
