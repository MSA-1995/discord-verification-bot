# ========== AUTO-UPDATE PIP ==========
import subprocess
import sys
try:
    print("🔄 Checking pip updates...")
    # Make subprocess verbose to see output in logs and fail on error
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'], 
                   check=True, timeout=60)
    print("✅ pip updated successfully")
except Exception as e:
    print(f"⚠️ pip update skipped: {e}")

# ========== AUTO-INSTALL DEPENDENCIES ==========
def install_dependencies():
    required = ['discord.py', 'cryptography', 'requests']
    for package in required:
        try:
            if package == 'discord.py':
                __import__('discord')
            else:
                __import__(package)
        except ImportError:
            print(f"📦 Installing {package}...")
            # Make subprocess verbose and fail on error
            subprocess.run([sys.executable, '-m', 'pip', 'install', package], 
                         check=True)

install_dependencies()

import discord
from discord.ext import commands
import os
import asyncio
import requests
from datetime import datetime
from config_encrypted import get_discord_token, get_critical_webhook

# قراءة الـ Token من التشفير
TOKEN = get_discord_token()
CRITICAL_WEBHOOK = get_critical_webhook()

def send_critical_alert(error_type, message, details=None):
    """Send critical error alert to Discord"""
    if not CRITICAL_WEBHOOK:
        return
    
    fields = [
        {"name": "Bot", "value": "Verification Bot", "inline": True},
        {"name": "Error Type", "value": error_type, "inline": True},
        {"name": "Timestamp", "value": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "inline": True},
        {"name": "Message", "value": message, "inline": False}
    ]
    
    if details:
        fields.append({"name": "Details", "value": str(details)[:1000], "inline": False})
    
    embed = {
        "title": "🚨 CRITICAL ALERT",
        "color": 0xff0000,
        "fields": fields,
        "footer": {"text": "MSA Verification Bot • System Alerts"},
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        requests.post(CRITICAL_WEBHOOK, json={"embeds": [embed]}, timeout=5)
    except:
        pass

if not TOKEN:
    print("❌ Error: Failed to decrypt DISCORD_TOKEN!")
    print("Please check ENCRYPTION_KEY.")
    exit(1)

class MSABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        # تحميل الـ Cogs
        extensions = ['verification', 'protection', 'log_system']
        for ext in extensions:
            try:
                await self.load_extension(ext)
                print(f"✅ Loaded extension: {ext}")
            except Exception as e:
                print(f"❌ Failed to load extension {ext}: {e}")
        
        # إعادة تحميل زر التوثيق (Persistent View)
        # ملاحظة: يجب استيراد VerifyButton هنا ليعمل الزر بعد إعادة التشغيل
        try:
            from verification import VerifyButton
            self.add_view(VerifyButton())
            print("✅ Persistent views loaded")
        except Exception as e:
            print(f"⚠️ Could not load persistent views: {e}")

    async def on_ready(self):
        print(f"✅ {self.user} is online and ready!")
        print(f"📊 Connected to {len(self.guilds)} server(s)")
        print("🛡️ Protection System: ACTIVE (Cogs Mode)")

from threading import Thread
from flask import Flask

# ========== WEB SERVER (for Health Checks) ==========
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ... (rest of the bot code)

bot = MSABot()

# تشغيل البوت
print("🚀 Starting verification & protection bot...")
try:
    # Start the web server in a background thread
    web_thread = Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    print(f"🌐 Health check server started on port {os.environ.get('PORT', 8080)}")
    
    print("🤖 Attempting to connect to Discord...")
    bot.run(TOKEN)
    # If the script reaches here, it means bot.run() exited cleanly.
    print("🔴 WARN: bot.run() has exited. The bot is no longer running.")

except Exception as e:
    print(f"❌ Bot crashed: {e}")
    send_critical_alert("Bot Crash", "Verification Bot stopped unexpectedly", str(e))

finally:
    print("🏁 Script execution finished.")
