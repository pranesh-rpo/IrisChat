import logging
import asyncio
import os
import yt_dlp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import Pyrogram and PyTgCalls
try:
    from pyrogram import Client
    from pytgcalls import PyTgCalls
    from pytgcalls.types import MediaStream
    MUSIC_AVAILABLE = True
except ImportError:
    MUSIC_AVAILABLE = False
    logger.warning("PyTgCalls or Pyrogram not found. Music features will be disabled.")

class MusicPlayer:
    def __init__(self):
        self.app = None
        self.call_client = None
        self.is_running = False
        
        # Load credentials
        self.api_id = os.getenv("API_ID")
        self.api_hash = os.getenv("API_HASH")
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

        if MUSIC_AVAILABLE and self.api_id and self.api_hash:
            try:
                self.app = Client(
                    "iris_music_session",
                    api_id=self.api_id,
                    api_hash=self.api_hash,
                    bot_token=self.bot_token
                )
                self.call_client = PyTgCalls(self.app)
                self.is_running = True
            except Exception as e:
                logger.error(f"Failed to initialize Music Player: {e}")
                self.is_running = False
        else:
            logger.warning("Music Player not initialized (Missing API_ID/HASH or dependencies)")

    async def start(self):
        """Start the Pyrogram client and PyTgCalls."""
        if self.is_running and self.app and self.call_client:
            try:
                await self.app.start()
                await self.call_client.start()
                logger.info("Music Player Started! 🎵")
            except Exception as e:
                logger.error(f"Error starting Music Player: {e}")

    async def search_song(self, query):
        """Search for a song on YouTube using yt-dlp."""
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'default_search': 'ytsearch',
            'extract_flat': False,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, query, download=False)
                if 'entries' in info:
                    video = info['entries'][0]
                else:
                    video = info
                
                return {
                    'title': video['title'],
                    'url': video['url'], # Direct stream URL or webpage URL
                    'duration': video.get('duration'),
                    'webpage_url': video.get('webpage_url')
                }
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return None

    async def play(self, chat_id, query):
        """Play a song in the voice chat."""
        if not self.is_running:
            return "❌ Music system is not active. Check server logs or config."

        song_info = await self.search_song(query)
        if not song_info:
            return "❌ Could not find song."

        try:
            # Join the group call and play
            # Note: Streaming directly from URL usually requires ffmpeg
            stream = MediaStream(
                song_info['url'],
            )
            await self.call_client.play(chat_id, stream)
            return f"🎵 **Playing:** [{song_info['title']}]({song_info['webpage_url']})"
        except Exception as e:
            logger.error(f"Play error: {e}")
            return f"❌ Failed to play: {e}\n(Make sure the bot is an Admin and Voice Chat is on)"

    async def stop(self, chat_id):
        """Stop playback and leave voice chat."""
        if not self.is_running:
            return "❌ Music system inactive."
        
        try:
            await self.call_client.leave_call(chat_id)
            return "⏹️ Stopped playback."
        except Exception as e:
            return f"❌ Error stopping: {e}"

    async def pause(self, chat_id):
        if not self.is_running: return "❌ Music system inactive."
        try:
            await self.call_client.pause_stream(chat_id)
            return "paused ⏸️"
        except: return "❌ Not playing."

    async def resume(self, chat_id):
        if not self.is_running: return "❌ Music system inactive."
        try:
            await self.call_client.resume_stream(chat_id)
            return "resumed ▶️"
        except: return "❌ Error."
