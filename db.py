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
                username TEXT,
                warns INTEGER DEFAULT 0,
                is_muted BOOLEAN DEFAULT 0,
                mute_until TIMESTAMP,
                is_banned BOOLEAN DEFAULT 0,
                reason TEXT,
                PRIMARY KEY (chat_id, user_id)
            )
        ''')
        
        # Migration: Add username if it doesn't exist
        try:
            cursor.execute('ALTER TABLE moderation ADD COLUMN username TEXT')
        except sqlite3.OperationalError:
            pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mod_settings (
                chat_id INTEGER PRIMARY KEY,
                auto_mod BOOLEAN DEFAULT 1,
                warn_limit INTEGER DEFAULT 3,
                ban_on_limit BOOLEAN DEFAULT 1,
                warn_action TEXT DEFAULT 'ban',
                warn_action_duration INTEGER DEFAULT 0,
                antiflood_enabled BOOLEAN DEFAULT 1,
                antiflood_threshold INTEGER DEFAULT 5,
                antiflood_timeframe INTEGER DEFAULT 5,
                antiflood_action TEXT DEFAULT 'mute'
            )
        ''')
        
        # Migration: Add warn_action and warn_action_duration if they don't exist
        try:
            cursor.execute('ALTER TABLE mod_settings ADD COLUMN warn_action TEXT DEFAULT "ban"')
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute('ALTER TABLE mod_settings ADD COLUMN warn_action_duration INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        
        # Migration: Add antiflood settings
        try:
            cursor.execute('ALTER TABLE mod_settings ADD COLUMN antiflood_enabled BOOLEAN DEFAULT 1')
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute('ALTER TABLE mod_settings ADD COLUMN antiflood_threshold INTEGER DEFAULT 5')
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute('ALTER TABLE mod_settings ADD COLUMN antiflood_timeframe INTEGER DEFAULT 5')
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute('ALTER TABLE mod_settings ADD COLUMN antiflood_action TEXT DEFAULT "mute"')
        except sqlite3.OperationalError:
            pass

        # Create notes/rules table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                note_name TEXT NOT NULL,
                note_content TEXT NOT NULL,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, note_name)
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

        # Create users table for username lookup
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_username ON users(username)')
        except:
            pass

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

def add_warn(chat_id, user_id, reason=None, username=None):
    """Increment warning count for a user and return the total count."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO moderation (chat_id, user_id, warns, reason, username)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                warns = warns + 1,
                reason = COALESCE(excluded.reason, moderation.reason),
                username = COALESCE(excluded.username, moderation.username)
        ''', (chat_id, user_id, reason, username))
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

def set_mute(chat_id, user_id, is_muted, until=None, username=None):
    """Set mute status for a user."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO moderation (chat_id, user_id, is_muted, mute_until, username)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                is_muted = excluded.is_muted,
                mute_until = excluded.mute_until,
                username = COALESCE(excluded.username, moderation.username)
        ''', (chat_id, user_id, is_muted, until, username))
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

def get_user_id_by_username(username, chat_id=None):
    """Get a user's ID from their username (looks in users and moderation)."""
    if not username: return None
    username = username.lstrip('@').lower()
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # 1. Check users table (global lookup)
        cursor.execute('SELECT user_id FROM users WHERE LOWER(username) = ?', (username,))
        result = cursor.fetchone()
        if result:
            conn.close()
            return result[0]
            
        # 2. Check moderation table (chat-specific lookup if chat_id provided)
        if chat_id:
            cursor.execute('SELECT user_id FROM moderation WHERE chat_id = ? AND LOWER(username) = ?', (chat_id, username))
            result = cursor.fetchone()
            if result:
                conn.close()
                return result[0]
            
        conn.close()
        return None
    except Exception as e:
        logging.error(f"Error getting user by username: {e}")
        return None

def track_user(user_id, username=None, first_name=None):
    """Update user info in the users table."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, last_seen)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                username = COALESCE(excluded.username, users.username),
                first_name = COALESCE(excluded.first_name, users.first_name),
                last_seen = CURRENT_TIMESTAMP
        ''', (user_id, username, first_name))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error tracking user: {e}")

def update_user_record(chat_id, user_id, username):
    """Update or create a user record in the moderation table to track username."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO moderation (chat_id, user_id, username)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                username = excluded.username
        ''', (chat_id, user_id, username))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error updating user record: {e}")

def get_mod_settings(chat_id):
    """Get moderation settings for a chat."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM mod_settings WHERE chat_id = ?', (chat_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {
            "auto_mod": 1, 
            "warn_limit": 3, 
            "ban_on_limit": 1, 
            "warn_action": "ban", 
            "warn_action_duration": 0,
            "antiflood_enabled": 1,
            "antiflood_threshold": 5,
            "antiflood_timeframe": 5,
            "antiflood_action": "mute"
        }
    except Exception as e:
        logging.error(f"Error getting mod settings: {e}")
        return {
            "auto_mod": 1, 
            "warn_limit": 3, 
            "ban_on_limit": 1, 
            "warn_action": "ban", 
            "warn_action_duration": 0,
            "antiflood_enabled": 1,
            "antiflood_threshold": 5,
            "antiflood_timeframe": 5,
            "antiflood_action": "mute"
        }

def save_note(chat_id, note_name, note_content, created_by):
    """Save or update a note/rule"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO notes (chat_id, note_name, note_content, created_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, note_name) DO UPDATE SET
                note_content = excluded.note_content,
                created_by = excluded.created_by,
                created_at = CURRENT_TIMESTAMP
        ''', (chat_id, note_name.lower(), note_content, created_by))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error saving note: {e}")
        return False

def get_note(chat_id, note_name):
    """Get a specific note"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT note_content FROM notes WHERE chat_id = ? AND LOWER(note_name) = ?', 
                      (chat_id, note_name.lower()))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logging.error(f"Error getting note: {e}")
        return None

def get_all_notes(chat_id):
    """Get all notes for a chat"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT note_name, note_content FROM notes WHERE chat_id = ? ORDER BY note_name', (chat_id,))
        notes = cursor.fetchall()
        conn.close()
        return notes
    except Exception as e:
        logging.error(f"Error getting notes: {e}")
        return []

def delete_note(chat_id, note_name):
    """Delete a note"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM notes WHERE chat_id = ? AND LOWER(note_name) = ?', 
                      (chat_id, note_name.lower()))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
    except Exception as e:
        logging.error(f"Error deleting note: {e}")
        return False

def set_antiflood(chat_id, enabled=True, threshold=5, timeframe=5, action="mute"):
    """Configure anti-flood settings for a chat."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO mod_settings (chat_id, antiflood_enabled, antiflood_threshold, antiflood_timeframe, antiflood_action)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                antiflood_enabled = excluded.antiflood_enabled,
                antiflood_threshold = excluded.antiflood_threshold,
                antiflood_timeframe = excluded.antiflood_timeframe,
                antiflood_action = excluded.antiflood_action
        ''', (chat_id, enabled, threshold, timeframe, action))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error setting antiflood: {e}")
        return False

def set_warn_action(chat_id, action, duration=0):
    """Set the warn action for a chat. Actions: ban, kick, mute"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO mod_settings (chat_id, warn_action, warn_action_duration)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                warn_action = excluded.warn_action,
                warn_action_duration = excluded.warn_action_duration
        ''', (chat_id, action, duration))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error setting warn action: {e}")
        return False

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
