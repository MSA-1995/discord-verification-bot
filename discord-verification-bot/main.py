# ========== AUTO-UPDATE PIP ==========
import subprocess
import sys
try:
    print("Checking pip updates...")
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'],
                            capture_output=True, check=False, timeout=30, text=True)
    if "Successfully installed" in result.stdout:
        print("pip updated successfully")
    else:
        print("pip is up to date")
except Exception as e:
    print(f"pip update skipped: {e}")

# ========== AUTO-INSTALL DEPENDENCIES ==========
def install_dependencies():
    required = ['discord.py', 'cryptography', 'aiohttp']
    for package in required:
        try:
            if package == 'discord.py':
                __import__('discord')
            else:
                __import__(package)
        except ImportError:
            print(f"📦 Installing {package}...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', package],
                           shell=False, capture_output=True)

install_dependencies()

import os
import traceback
import discord
from discord.ext import commands, tasks
import asyncio
import aiohttp
import http.server
import threading
from datetime import datetime
from src.config.config_encrypted import get_discord_token, get_critical_webhook

# ========================= HEALTH CHECK SERVER =========================
class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Verification Bot is Healthy")

    def log_message(self, format, *args):
        return

def run_health_check():
    server = http.server.HTTPServer(('0.0.0.0', 7860), HealthCheckHandler)
    server.serve_forever()

TOKEN = get_discord_token()
CRITICAL_WEBHOOK = get_critical_webhook()

_alert_session: aiohttp.ClientSession | None = None

async def get_alert_session() -> aiohttp.ClientSession:
    global _alert_session
    if _alert_session is None or _alert_session.closed:
        _alert_session = aiohttp.ClientSession()
    return _alert_session

async def send_critical_alert(error_type, message, details=None):
    if not CRITICAL_WEBHOOK:
        return

    fields = [
        {"name": "Bot",        "value": "Verification Bot",                          "inline": True},
        {"name": "Error Type", "value": error_type,                                   "inline": True},
        {"name": "Timestamp",  "value": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "inline": True},
        {"name": "Message",    "value": message,                                      "inline": False},
    ]
    if details:
        fields.append({"name": "Details", "value": str(details)[:1000], "inline": False})

    embed = {
        "title": "🚨 CRITICAL ALERT",
        "color": 0xff0000,
        "fields": fields,
        "footer": {"text": "MSA Verification Bot • System Alerts"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        session = await get_alert_session()
        await session.post(CRITICAL_WEBHOOK, json={"embeds": [embed]},
                           timeout=aiohttp.ClientTimeout(total=5))
    except Exception:
        pass

if not TOKEN:
    print("❌ ERROR: Failed to decrypt DISCORD_TOKEN!")
    print("Please check ENCRYPTION_KEY.")
    exit(1)

print(f"✅ Token loaded successfully")

class MSABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self._http_session: aiohttp.ClientSession | None = None
        print("✅ MSABot __init__ done")

    async def setup_hook(self):
        print("🔄 setup_hook started...")

        try:
            self._http_session = aiohttp.ClientSession()
            print("✅ HTTP session created")
        except Exception as e:
            print(f"❌ Failed to create HTTP session: {e}")
            traceback.print_exc()

        extensions = [
            'src.models.verification',
            'src.handlers.protection',
            'src.core.log_system'
        ]

        for ext in extensions:
            try:
                print(f"🔄 Loading: {ext}...")
                if ext in self.extensions:
                    await self.reload_extension(ext)
                    print(f"✅ Reloaded: {ext}")
                else:
                    await self.load_extension(ext)
                    print(f"✅ Loaded: {ext}")
            except Exception as e:
                print(f"❌ FAILED to load {ext}: {e}")
                traceback.print_exc()  # يطبع الخطأ كامل مع السطر

        print("✅ setup_hook finished")

    async def close(self):
        print("🔄 Bot closing...")
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            print("✅ HTTP session closed")
        if _alert_session and not _alert_session.closed:
            await _alert_session.close()
            print("✅ Alert session closed")
        await super().close()
        print("✅ Bot closed")

    async def on_ready(self):
        print(f"✅ {self.user} is online and ready!")
        print(f"Connected to {len(self.guilds)} server(s)")
        print("Protection System: ACTIVE (Cogs Mode)")

        if not keep_alive_task.is_running():
            keep_alive_task.start()
            print("⏰ Keep-Alive (Self-Ping): STARTED")

    async def on_error(self, event_method, *args, **kwargs):
        print(f"❌ Error in event {event_method}:")
        traceback.print_exc()

bot = MSABot()

# ========================= KEEP ALIVE =========================
@tasks.loop(minutes=10)
async def keep_alive_task():
    url = os.getenv("SPACE_URL")
    if not url:
        return

    try:
        if bot._http_session and not bot._http_session.closed:
            async with bot._http_session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    print(f"📡 Keep-Alive: Ping successful - {datetime.now().strftime('%H:%M:%S')}")
    except Exception:
        pass

@keep_alive_task.before_loop
async def before_keep_alive():
    await bot.wait_until_ready()

# ========================= START BOT =========================
print("🚀 Starting verification & protection bot...")

threading.Thread(target=run_health_check, daemon=True).start()
print("✅ Health check server started on port 7860")

async def main():
    try:
        print("🔄 Connecting to Discord...")
        async with bot:
            await bot.start(TOKEN)
    except discord.LoginFailure:
        print("❌ Invalid Token! Please check DISCORD_TOKEN.")
        traceback.print_exc()
        await send_critical_alert("Login Failure", "Invalid Discord Token", None)
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
        traceback.print_exc()
        await send_critical_alert("Bot Crash", "Verification Bot stopped unexpectedly", str(e))

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("🛑 Bot stopped manually.")