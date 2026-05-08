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
import time
import discord
from discord.ext import commands, tasks
import asyncio
import aiohttp
import http.server
import threading
import signal
from datetime import datetime, timezone
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
        {"name": "Timestamp",  "value": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), "inline": True},
        {"name": "Message",    "value": message,                                      "inline": False},
    ]
    if details:
        fields.append({"name": "Details", "value": str(details)[:1000], "inline": False})

    embed = {
        "title": "🚨 CRITICAL ALERT",
        "color": 0xff0000,
        "fields": fields,
        "footer": {"text": "MSA Verification Bot • System Alerts"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
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

        # التأكد من تنظيف أي جلسة سابقة عالقة
        global _alert_session
        if _alert_session and not _alert_session.closed:
            await _alert_session.close()
            _alert_session = None

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
        try:
            if keep_alive_task.is_running():
                keep_alive_task.stop()
                print("✅ Keep-Alive task stopped")
        except Exception:
            pass
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

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"❌ ليس لديك صلاحية لاستخدام هذا الأمر. المطلوب: {error.missing_permissions}", delete_after=7)
        else:
            print(f"❌ Command Error in {ctx.command}: {error}")
            traceback.print_exc()

# تعريف المتغير عالمياً وتهيئته لاحقاً داخل الحلقة
bot: MSABot = None

# ========================= KEEP ALIVE =========================
@tasks.loop(minutes=10)
async def keep_alive_task():
    if bot is None:
        return
    url = os.getenv("SPACE_URL")
    if not url:
        return

    try:
        if bot._http_session and not bot._http_session.closed:
            async with bot._http_session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                        print(f"📡 Keep-Alive: Ping successful - {datetime.now(timezone.utc).strftime('%H:%M:%S')}")
    except Exception:
        pass

@keep_alive_task.before_loop
async def before_keep_alive():
    if bot is None:
        return
    await bot.wait_until_ready()


import json
from pathlib import Path

# ========================= RECONNECT GUARD =========================
LOCK_FILE = Path("/tmp/bot_last_connect.json")

async def check_reconnect_guard():
    """Prevent reconnect storm - wait between connections"""
    now = time.time()
    
    try:
        if LOCK_FILE.exists():
            data = json.loads(LOCK_FILE.read_text())
            last_connect = data.get("last_connect", 0)
            connect_count = data.get("count_last_hour", 0)
            first_connect = data.get("first_connect_hour", now)
            
            wait_time = 60 - (now - last_connect)
            if wait_time > 0:
                print(f"⏳ Reconnect Guard: Waiting {int(wait_time)}s before connecting...")
                await asyncio.sleep(wait_time)
            
            if now - first_connect < 3600:
                connect_count += 1
                if connect_count > 20:
                    print(f"🚫 Too many connects ({connect_count}/hr)! Waiting 15 min...")
                    await asyncio.sleep(900)
                    connect_count = 0
                    first_connect = now
            else:
                connect_count = 1
                first_connect = now
        else:
            connect_count = 1
            first_connect = now
    except Exception:
        connect_count = 1
        first_connect = now
    
    try:
        LOCK_FILE.write_text(json.dumps({
            "last_connect": now,
            "count_last_hour": connect_count,
            "first_connect_hour": first_connect
        }))
    except Exception:
        pass
    
    print(f"✅ Reconnect Guard: OK (connect #{connect_count} this hour)")

# ========================= START BOT =========================
print("🚀 Starting verification & protection bot...")

async def main():
    global bot
    loop = asyncio.get_running_loop()
    
    # FIX: إغلاق البوت بشكل نظيف ليختفي من ديسكورد فوراً
    def handle_exit():
        print("🛑 Shutdown signal received. Closing bot gracefully...")
        if bot:
            asyncio.create_task(bot.close())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig, handle_exit)
        except NotImplementedError: pass

    retry_delay = 5
    while True:
        try:
            await check_reconnect_guard()
            
            if bot is not None:
                try: await bot.close()
                except: pass

            bot = MSABot()
            
            print("🔄 Connecting to Discord...")
            async with bot:
                await bot.start(TOKEN)
            
            # Reset retry delay on successful connection closure
            retry_delay = 5

        except discord.HTTPException as e:
            if e.status == 429:
                # Discord Rate Limit - Global or Route specific
                retry_after = getattr(e, 'retry_after', 120)  # Default to 2 mins if not provided
                print(f"🚨 Discord Rate Limit (429): Waiting {retry_after}s before retrying...")
                await send_critical_alert("Rate Limit", f"Bot is being rate limited by Discord. Waiting {retry_after}s", str(e))
                await asyncio.sleep(retry_after + 5)
            else:
                print(f"❌ Discord HTTP Error {e.status}: {e}")
                traceback.print_exc()
                await asyncio.sleep(retry_delay)

        except discord.LoginFailure:
            print("❌ Invalid Token! Please check DISCORD_TOKEN.")
            traceback.print_exc()
            await send_critical_alert("Login Failure", "Invalid Discord Token", None)
            break  # توقف تماماً لأن التوكن خطأ
        except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, ConnectionResetError) as e:
            print(f"⚠️ Network error: {e}. Retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # زيادة وقت الانتظار تدريجياً حتى دقيقة
            continue
        except Exception as e:
            print(f"❌ Bot crashed: {e}")
            traceback.print_exc()
            await send_critical_alert("Bot Crash", "Verification Bot stopped unexpectedly", str(e))
            # في حالة الأخطاء الأخرى، انتظر قليلاً ثم حاول مرة أخرى
            await asyncio.sleep(20)
            continue

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("🛑 Bot stopped manually.")
