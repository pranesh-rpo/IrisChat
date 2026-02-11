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
                privacy_mode BOOLEAN DEFAULT 0,
                log_retention INTEGER DEFAULT 30,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Migration: Add privacy_mode if it doesn't exist
        try:
            cursor.execute('ALTER TABLE chat_settings ADD COLUMN privacy_mode BOOLEAN DEFAULT 0')
        except sqlite3.OperationalError:
            pass

        # Migration: Add log_retention if it doesn't exist
        try:
            cursor.execute('ALTER TABLE chat_settings ADD COLUMN log_retention INTEGER DEFAULT 30')
        except sqlite3.OperationalError:
            pass

        # Create economy table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS economy (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT,
                balance INTEGER DEFAULT 0,
                last_daily TIMESTAMP,
                last_beg TIMESTAMP,
                last_work TIMESTAMP,
                last_rob TIMESTAMP,
                inventory TEXT
            )
        ''')
        
        # Migration: Add user_name if it doesn't exist
        try:
            cursor.execute('ALTER TABLE economy ADD COLUMN user_name TEXT')
        except sqlite3.OperationalError:
            pass

        # Create moderation tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS moderation (
                chat_id INTEGER,
                user_id INTEGER,
                warns INTEGER DEFAULT 0,
                is_muted BOOLEAN DEFAULT 0,
                mute_until TIMESTAMP,
                is_banned BOOLEAN DEFAULT 0,
                reason TEXT,
                PRIMARY KEY (chat_id, user_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mod_settings (
                chat_id INTEGER PRIMARY KEY,
                auto_mod BOOLEAN DEFAULT 1,
                warn_limit INTEGER DEFAULT 3,
                ban_on_limit BOOLEAN DEFAULT 1
            )
        ''')

        # Create mod_filters table for keyword blocks
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mod_filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                keyword TEXT NOT NULL,
                is_regex BOOLEAN DEFAULT 0,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create admin_actions table for group health tools
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                admin_id INTEGER,
                action_type TEXT,
                target_id INTEGER,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()
        logging.info("Database initialized successfully.")
    except Exception as e:
        logging.error(f"Database initialization error: {e}")

# --- Economy Functions ---

def get_balance(user_id):
    """Get the balance of a user."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT balance FROM economy WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception as e:
        logging.error(f"Error getting balance: {e}")
        return 0

def update_user_name(user_id, user_name):
    """Update the user's name in the economy table."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO economy (user_id) VALUES (?)', (user_id,))
        cursor.execute('UPDATE economy SET user_name = ? WHERE user_id = ?', (user_name, user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error updating user name: {e}")

def update_balance(user_id, amount, user_name=None):
    """Add (or subtract) coins from a user's balance."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Ensure user exists
        cursor.execute('INSERT OR IGNORE INTO economy (user_id) VALUES (?)', (user_id,))
        # Update balance
        cursor.execute('UPDATE economy SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
        # Update name if provided
        if user_name:
            cursor.execute('UPDATE economy SET user_name = ? WHERE user_id = ?', (user_name, user_id))
        
        conn.commit()
        conn.close()
        return get_balance(user_id)
    except Exception as e:
        logging.error(f"Error updating balance: {e}")
        return 0

def get_cooldown(user_id, action_type):
    """Get the timestamp of the last action."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(f'SELECT last_{action_type} FROM economy WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logging.error(f"Error getting cooldown: {e}")
        return None

def set_cooldown(user_id, action_type):
    """Update the timestamp for an action to now."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO economy (user_id) VALUES (?)', (user_id,))
        now = datetime.now().isoformat()
        cursor.execute(f'UPDATE economy SET last_{action_type} = ? WHERE user_id = ?', (now, user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error setting cooldown: {e}")

def get_leaderboard(limit=10):
    """Get the top richest users."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, balance, user_name FROM economy ORDER BY balance DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"Error getting leaderboard: {e}")
        return []

# --- Moderation Functions ---

def get_warns(chat_id, user_id):
    """Get warning count for a user in a chat."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT warns FROM moderation WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception as e:
        logging.error(f"Error getting warns: {e}")
        return 0

def add_warn(chat_id, user_id, reason=None):
    """Increment warning count for a user."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO moderation (chat_id, user_id, warns, reason)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                warns = warns + 1,
                reason = excluded.reason
        ''', (chat_id, user_id, reason))
        conn.commit()
        cursor.execute('SELECT warns FROM moderation WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logging.error(f"Error adding warn: {e}")
        return 0

def reset_warns(chat_id, user_id):
    """Reset warning count for a user."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('UPDATE moderation SET warns = 0 WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error resetting warns: {e}")

def set_mute(chat_id, user_id, is_muted, until=None):
    """Set mute status for a user."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO moderation (chat_id, user_id, is_muted, mute_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                is_muted = excluded.is_muted,
                mute_until = excluded.mute_until
        ''', (chat_id, user_id, is_muted, until))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error setting mute: {e}")

def is_muted(chat_id, user_id):
    """Check if a user is currently muted."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT is_muted, mute_until FROM moderation WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
        result = cursor.fetchone()
        conn.close()
        if not result or not result[0]:
            return False
        
        if result[1]: # Check timestamp
            until = datetime.fromisoformat(result[1])
            if datetime.now() > until:
                set_mute(chat_id, user_id, False) # Auto-unmute in DB
                return False
        return True
    except Exception as e:
        logging.error(f"Error checking mute: {e}")
        return False

def get_mod_settings(chat_id):
    """Get moderation settings for a chat."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT auto_mod, warn_limit, ban_on_limit FROM mod_settings WHERE chat_id = ?', (chat_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"auto_mod": 1, "warn_limit": 3, "ban_on_limit": 1}
    except Exception as e:
        logging.error(f"Error getting mod settings: {e}")
        return {"auto_mod": 1, "warn_limit": 3, "ban_on_limit": 1}

# --- Filter & Health Functions ---

def add_filter(chat_id, keyword, is_regex=0, expires_at=None):
    """Add a keyword filter."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO mod_filters (chat_id, keyword, is_regex, expires_at)
            VALUES (?, ?, ?, ?)
        ''', (chat_id, keyword, is_regex, expires_at))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error adding filter: {e}")
        return False

def get_filters(chat_id):
    """Get active filters for a chat."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            SELECT keyword, is_regex FROM mod_filters 
            WHERE chat_id = ? AND (expires_at IS NULL OR expires_at > ?)
        ''', (chat_id, now))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"Error getting filters: {e}")
        return []

def log_admin_action(chat_id, admin_id, action_type, target_id=None, reason=None):
    """Log an administrative action."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO admin_actions (chat_id, admin_id, action_type, target_id, reason)
            VALUES (?, ?, ?, ?, ?)
        ''', (chat_id, admin_id, action_type, target_id, reason))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error logging admin action: {e}")

def get_admin_summary(chat_id):
    """Get a summary of admin actions in a chat."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT admin_id, action_type, COUNT(*) as count 
            FROM admin_actions 
            WHERE chat_id = ? 
            GROUP BY admin_id, action_type
        ''', (chat_id,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"Error getting admin summary: {e}")
        return []

def delete_old_messages(days=30):
    """Delete messages older than X days."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE created_at < datetime('now', '-' || ? || ' days')", (days,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error deleting old messages: {e}")
        return False

def get_chat_settings(chat_id):
    """Get chat settings."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM chat_settings WHERE chat_id = ?', (chat_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"chat_id": chat_id, "mode": "normal", "persona_prompt": None}
    except Exception as e:
        logging.error(f"Error getting chat settings: {e}")
        return {"chat_id": chat_id, "mode": "normal", "persona_prompt": None}

def update_chat_setting(chat_id, key, value):
    """Update a specific chat setting."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Ensure row exists
        cursor.execute('INSERT OR IGNORE INTO chat_settings (chat_id) VALUES (?)', (chat_id,))
        cursor.execute(f'UPDATE chat_settings SET {key} = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?', (value, chat_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error updating chat setting: {e}")
        return False

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
