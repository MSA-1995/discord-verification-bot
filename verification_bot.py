import discord
from discord.ext import commands
import os
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio

# قراءة الـ Token من Environment Variable
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("❌ Error: DISCORD_TOKEN not found!")
    print("Please set DISCORD_TOKEN in Railway/Render settings.")
    exit(1)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# نظام تتبع الرسائل (للسبام)
user_messages = defaultdict(list)
user_warnings = defaultdict(int)

# إعدادات الحماية
SPAM_THRESHOLD = 5  # 5 رسائل في 10 ثواني
SPAM_TIMEFRAME = 10  # ثواني
NEW_ACCOUNT_DAYS = 30  # الحسابات الأحدث من 30 يوم
MUTE_DURATION = 30  # 30 دقيقة

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="✅ Verify Me", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        
        # فحص إذا كان بوت
        if member.bot:
            await interaction.response.send_message("❌ Bots cannot be verified!", ephemeral=True)
            return
        
        # فحص عمر الحساب
        account_age = (datetime.now(member.created_at.tzinfo) - member.created_at).days
        is_new = account_age < NEW_ACCOUNT_DAYS
        has_avatar = member.avatar is not None
        
        # إعطاء رول Verified
        verified_role = discord.utils.get(interaction.guild.roles, name="Verified")
        if not verified_role:
            verified_role = await interaction.guild.create_role(name="Verified")
        
        await member.add_roles(verified_role)
        
        # إضافة رول مراقبة للحسابات الجديدة/بدون صورة
        if is_new or not has_avatar:
            watched_role = discord.utils.get(interaction.guild.roles, name="Watched")
            if not watched_role:
                watched_role = await interaction.guild.create_role(
                    name="Watched",
                    color=discord.Color.orange()
                )
            await member.add_roles(watched_role)
            
            msg = "✅ Verified! ⚠️ You are under strict monitoring."
        else:
            msg = "✅ You have been verified!"
        
        await interaction.response.send_message(msg, ephemeral=True)

@bot.event
async def on_ready():
    bot.add_view(VerifyButton())
    print(f"✅ {bot.user} is online and ready!")
    print(f"📊 Connected to {len(bot.guilds)} server(s)")
    print("🛡️ Protection System: ACTIVE")

@bot.event
async def on_member_join(member):
    """فحص الأعضاء الجدد عند الدخول"""
    # منع البوتات نهائياً
    if member.bot:
        try:
            await member.kick(reason="🚫 Bots are not allowed")
            print(f"🚫 Kicked bot: {member.name}")
        except:
            pass
        return

@bot.event
async def on_message(message):
    # تجاهل رسائل البوت
    if message.author.bot:
        return
    
    # تجاهل المسؤولين
    if message.author.guild_permissions.administrator:
        await bot.process_commands(message)
        return
    
    member = message.author
    
    # فحص الروابط
    if any(word in message.content.lower() for word in ['http://', 'https://', 'discord.gg/', '.com', '.net', '.org']):
        try:
            await message.delete()
            await member.timeout(timedelta(minutes=MUTE_DURATION), reason="🚫 Posted links")
            await message.channel.send(
                f"⚠️ {member.mention} has been muted for {MUTE_DURATION} minutes for posting links!",
                delete_after=10
            )
            print(f"🚫 Muted {member.name} for posting links")
        except:
            pass
        return
    
    # فحص السبام
    now = datetime.now()
    user_messages[member.id].append(now)
    user_messages[member.id] = [msg_time for msg_time in user_messages[member.id] 
                                 if (now - msg_time).seconds < SPAM_TIMEFRAME]
    
    if len(user_messages[member.id]) >= SPAM_THRESHOLD:
        try:
            await member.timeout(timedelta(minutes=MUTE_DURATION), reason="🚫 Spamming")
            await message.channel.send(
                f"⚠️ {member.mention} has been muted for {MUTE_DURATION} minutes for spamming!",
                delete_after=10
            )
            user_messages[member.id].clear()
            print(f"🚫 Muted {member.name} for spamming")
        except:
            pass
        return
    
    await bot.process_commands(message)

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_verify(ctx):
    """أمر لإنشاء رسالة التوثيق مع زر"""
    await ctx.message.delete()
    
    embed = discord.Embed(
        title="🔐 Server Verification",
        description="Click the **✅ Verify Me** button below to gain access to the rest of the server!\n\n🛡️ **Protection Active:**\n• Anti-Spam\n• Anti-Bot\n• Link Protection\n• New Account Monitoring",
        color=0x00ff00
    )
    embed.set_footer(text="MSA Verification & Protection System")
    
    await ctx.send(embed=embed, view=VerifyButton())
    print(f"✅ Verification message created in #{ctx.channel.name}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need Administrator permissions to use this command!", delete_after=5)

# تشغيل البوت
print("🚀 Starting verification & protection bot...")
bot.run(TOKEN)
