import os
import traceback
import time
import uuid
import discord
from discord.ext import commands
import asyncio
import aiohttp
import http.server
import threading
import signal
import json
import re
from pathlib import Path
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
    port = int(os.getenv("PORT", "8000"))
    server = http.server.HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

TOKEN = get_discord_token()
CRITICAL_WEBHOOK = get_critical_webhook()
INSTANCE_ID = os.getenv("KOYEB_DEPLOYMENT_ID") or os.getenv("HOSTNAME") or str(uuid.uuid4())
INSTANCE_STARTED_AT = time.time()
LEASE_MARKER = "MSA_BOT_SINGLETON_LEASE"
LEASE_CHECK_SECONDS = int(os.getenv("LEASE_CHECK_SECONDS", "20"))
LEASE_STALE_SECONDS = int(os.getenv("LEASE_STALE_SECONDS", "90"))

shutdown_requested = False

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
        self._singleton_task: asyncio.Task | None = None
        self._lease_message_id: int | None = None
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
        if (
            self._singleton_task
            and not self._singleton_task.done()
            and self._singleton_task is not asyncio.current_task()
        ):
            self._singleton_task.cancel()
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
        print(f"Instance ID: {INSTANCE_ID}")

        if not self._singleton_task or self._singleton_task.done():
            self._singleton_task = asyncio.create_task(self._singleton_guard())

    async def _singleton_guard(self):
        await self.wait_until_ready()

        while not self.is_closed():
            try:
                lease_channel = self._get_lease_channel()
                if lease_channel:
                    should_stop = await self._sync_singleton_lease(lease_channel)
                    if should_stop:
                        await self._shutdown_for_newer_instance()
                        return
                else:
                    print("⚠️ Singleton guard disabled: LOG_CHANNEL_ID/SINGLETON_CHANNEL_ID channel not found.")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ Singleton guard error: {e}")
                traceback.print_exc()

            await asyncio.sleep(LEASE_CHECK_SECONDS)

    def _get_lease_channel(self):
        channel_id = os.getenv("SINGLETON_CHANNEL_ID") or os.getenv("LOG_CHANNEL_ID")
        if channel_id and channel_id.isdigit():
            channel = self.get_channel(int(channel_id))
            if channel:
                return channel

        for guild in self.guilds:
            channel = discord.utils.get(guild.text_channels, name="📋・logs")
            if channel:
                return channel
        return None

    async def _find_lease_message(self, channel):
        if self._lease_message_id:
            try:
                message = await channel.fetch_message(self._lease_message_id)
                if message.author.id == self.user.id and self._is_lease_message(message):
                    return message
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                self._lease_message_id = None

        async for message in channel.history(limit=50):
            if message.author.id == self.user.id and self._is_lease_message(message):
                self._lease_message_id = message.id
                return message
        return None

    def _is_lease_message(self, message):
        if message.content.startswith(LEASE_MARKER):
            return True

        for embed in message.embeds:
            footer_text = embed.footer.text if embed.footer else ""
            if LEASE_MARKER in footer_text:
                return True
        return False

    def _read_lease_payload(self, message):
        if not message or not self._is_lease_message(message):
            return {}

        if message.content.startswith(LEASE_MARKER):
            raw_payload = message.content[len(LEASE_MARKER):].strip()
            if raw_payload:
                try:
                    return json.loads(raw_payload)
                except json.JSONDecodeError:
                    pass

        if not message.embeds:
            return {}

        embed = message.embeds[0]
        fields = {field.name: field.value for field in embed.fields}
        started_at = self._extract_discord_timestamp(fields.get("وقت التشغيل", ""))
        heartbeat_at = self._extract_discord_timestamp(fields.get("آخر تحديث", ""))

        return {
            "instance_id": fields.get("معرف النسخة"),
            "started_at": started_at,
            "heartbeat_at": heartbeat_at,
        }

    def _extract_discord_timestamp(self, value):
        match = re.search(r"<t:(\d+):", value or "")
        if match:
            return float(match.group(1))
        return 0

    def _build_lease_embed(self, payload):
        started_at = int(float(payload["started_at"]))
        heartbeat_at = int(float(payload["heartbeat_at"]))

        embed = discord.Embed(
            title="حالة تشغيل البوت",
            description="النسخة الحالية تعمل الآن. إذا بدأ نشر جديد، النسخة الأقدم ستتوقف تلقائياً.",
            color=0x3498db,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="الحالة", value="Online", inline=True)
        embed.add_field(name="معرف النسخة", value=str(payload["instance_id"]), inline=True)
        embed.add_field(name="وقت التشغيل", value=f"<t:{started_at}:F>", inline=False)
        embed.add_field(name="آخر تحديث", value=f"<t:{heartbeat_at}:R>", inline=True)
        embed.set_footer(text=f"نظام التشغيل • {LEASE_MARKER}")
        return embed

    async def _sync_singleton_lease(self, channel):
        now = time.time()
        message = await self._find_lease_message(channel)
        payload = self._read_lease_payload(message)

        owner_id = payload.get("instance_id")
        owner_started_at = float(payload.get("started_at", 0) or 0)
        heartbeat_at = float(payload.get("heartbeat_at", 0) or 0)
        owner_is_newer = owner_id != INSTANCE_ID and owner_started_at > INSTANCE_STARTED_AT
        owner_is_alive = now - heartbeat_at < LEASE_STALE_SECONDS

        if owner_is_newer and owner_is_alive:
            print(f"🛑 Newer bot instance detected ({owner_id}). Stopping this instance.")
            return True

        lease_payload = {
            "instance_id": INSTANCE_ID,
            "started_at": INSTANCE_STARTED_AT,
            "heartbeat_at": now,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        embed = self._build_lease_embed(lease_payload)

        if message:
            await message.edit(content="", embed=embed)
        else:
            message = await channel.send(embed=embed)
            self._lease_message_id = message.id

        return False

    async def _shutdown_for_newer_instance(self):
        global shutdown_requested
        shutdown_requested = True
        print("✅ Closing old instance so the new deployment is the only active bot.")
        await self.close()

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
    global bot, shutdown_requested
    loop = asyncio.get_running_loop()
    
    threading.Thread(target=run_health_check, daemon=True).start()
    print(f"✅ Health check server started on port {os.getenv('PORT', '8000')}")
    
    # FIX: إغلاق البوت بشكل نظيف ليختفي من ديسكورد فوراً
    def handle_exit():
        global shutdown_requested
        shutdown_requested = True
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

            if shutdown_requested:
                print("✅ Shutdown requested. Exiting without reconnecting.")
                break
            
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
            if shutdown_requested:
                break
            # في حالة فشل الشبكة، ننتظر فترات أطول لأن المشكلة غالباً من السيرفر أو IP محظور مؤقتاً
            wait_time = max(retry_delay, 60)
            print(f"⚠️ Network error: {e}. Waiting {wait_time}s before next attempt...")
            await asyncio.sleep(wait_time)
            retry_delay = min(retry_delay + 30, 300)  # زيادة تدريجية حتى 5 دقائق لمنع الـ IP Ban
            continue
        except Exception as e:
            if shutdown_requested:
                break
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
