import discord
from discord.ext import commands
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio
from config_encrypted import get_discord_token

# قراءة الـ Token من التشفير
TOKEN = get_discord_token()

if not TOKEN:
    print("❌ Error: Failed to decrypt DISCORD_TOKEN!")
    print("Please check ENCRYPTION_KEY.")
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
    # لوق دخول السيرفر
    embed = discord.Embed(
        title="🟢 دخول السيرفر",
        color=0x00ff00,
        timestamp=datetime.now()
    )
    embed.add_field(name="👤 العضو", value=f"{member.mention} ({member.id})", inline=False)
    embed.add_field(name="📅 تاريخ إنشاء الحساب", value=member.created_at.strftime("%Y-%m-%d %H:%M"), inline=True)
    embed.add_field(name="📊 عدد الأعضاء", value=member.guild.member_count, inline=True)
    await send_log(member.guild, embed)
    
    # منع البوتات نهائياً (إلا إذا أضافها المالك)
    if member.bot:
        await asyncio.sleep(1)
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
            if entry.target.id == member.id:
                # لو المالك أضافه = سماح
                if entry.user.id == member.guild.owner_id:
                    print(f"✅ Owner added bot: {member.name}")
                    return
                # لو غير المالك = طرد
                else:
                    try:
                        await member.kick(reason="🚫 Only owner can add bots")
                        # لوق حماية - طرد بوت
                        embed = discord.Embed(
                            title="🛡️ لوق الحماية - طرد بوت",
                            color=0xff0000,
                            timestamp=datetime.now()
                        )
                        embed.add_field(name="🤖 البوت", value=f"{member.name} ({member.id})", inline=False)
                        embed.add_field(name="👤 من أضافه", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                        embed.add_field(name="📝 السبب", value="فقط المالك يمكنه إضافة بوتات", inline=False)
                        await send_log(member.guild, embed)
                        print(f"🚫 Kicked bot: {member.name} (added by {entry.user.name})")
                    except:
                        pass
                break
        return
    
    # إعطاء رول Welcome تلقائياً للأعضاء الجدد
    try:
        welcome_role = discord.utils.get(member.guild.roles, name="Welcome")
        if not welcome_role:
            # إنشاء الرول إذا لم يكن موجود
            welcome_role = await member.guild.create_role(
                name="Welcome",
                color=discord.Color.blue(),
                reason="رول ترحيب تلقائي للأعضاء الجدد"
            )
            print(f"✅ Created Welcome role")
        
        await member.add_roles(welcome_role)
        print(f"✅ Gave Welcome role to {member.name}")
    except Exception as e:
        print(f"⚠️ Error giving Welcome role: {e}")

@bot.event
async def on_guild_channel_create(channel):
    """حماية من إنشاء رومات غير مصرح بها"""
    await asyncio.sleep(1)
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
        if entry.target.id == channel.id:
            creator = entry.user
            
            # لوق إنشاء روم
            embed = discord.Embed(
                title="🟢 إنشاء روم",
                color=0x00ff00,
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 الشخص", value=f"{creator.mention} ({creator.id})", inline=False)
            embed.add_field(name="📝 اسم الروم", value=channel.name, inline=True)
            embed.add_field(name="🆔 ID الروم", value=channel.id, inline=True)
            await send_log(channel.guild, embed)
            
            # لو مو Admin
            if not creator.guild_permissions.administrator and not creator.bot:
                try:
                    await channel.delete(reason="🚫 Unauthorized channel creation")
                    await creator.ban(reason="🚫 Unauthorized channel creation - Security threat")
                    # لوق حماية - باند
                    embed = discord.Embed(
                        title="🛡️ لوق الحماية - باند",
                        color=0xff0000,
                        timestamp=datetime.now()
                    )
                    embed.add_field(name="👤 الشخص", value=f"{creator.mention} ({creator.id})", inline=False)
                    embed.add_field(name="📝 السبب", value="إنشاء روم غير مصرح به", inline=False)
                    await send_log(channel.guild, embed)
                    print(f"🚫 Banned {creator.name} for creating unauthorized channel")
                except:
                    pass
            break

@bot.event
async def on_guild_role_create(role):
    """حماية من إنشاء رتب غير مصرح بها"""
    await asyncio.sleep(1)
    async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
        if entry.target.id == role.id:
            creator = entry.user
            
            # لوق إنشاء رول
            embed = discord.Embed(
                title="🟢 إنشاء رول",
                color=0x00ff00,
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 الشخص", value=f"{creator.mention} ({creator.id})", inline=False)
            embed.add_field(name="📝 اسم الرول", value=role.name, inline=True)
            embed.add_field(name="🆔 ID الرول", value=role.id, inline=True)
            await send_log(role.guild, embed)
            
            # لو مو Admin ومو البوت نفسه
            if not creator.guild_permissions.administrator and creator.id != bot.user.id:
                try:
                    await role.delete(reason="🚫 Unauthorized role creation")
                    member = role.guild.get_member(creator.id)
                    if member:
                        await member.ban(reason="🚫 Unauthorized role creation - Security threat")
                        # لوق حماية - باند
                        embed = discord.Embed(
                            title="🛡️ لوق الحماية - باند",
                            color=0xff0000,
                            timestamp=datetime.now()
                        )
                        embed.add_field(name="👤 الشخص", value=f"{creator.mention} ({creator.id})", inline=False)
                        embed.add_field(name="📝 السبب", value="إنشاء رول غير مصرح به", inline=False)
                        await send_log(role.guild, embed)
                        print(f"🚫 Banned {creator.name} for creating unauthorized role")
                except:
                    pass
            break

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
            # لوق حماية - ميوت روابط
            embed = discord.Embed(
                title="🛡️ لوق الحماية - ميوت روابط",
                color=0xff6600,
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 العضو", value=f"{member.mention} ({member.id})", inline=False)
            embed.add_field(name="📝 المحتوى", value=message.content[:1024], inline=False)
            embed.add_field(name="⏰ المدة", value=f"{MUTE_DURATION} دقيقة", inline=True)
            await send_log(message.guild, embed)
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
            # لوق حماية - ميوت سبام
            embed = discord.Embed(
                title="🛡️ لوق الحماية - ميوت سبام",
                color=0xff6600,
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 العضو", value=f"{member.mention} ({member.id})", inline=False)
            embed.add_field(name="📝 السبب", value=f"إرسال {SPAM_THRESHOLD} رسائل في {SPAM_TIMEFRAME} ثواني", inline=False)
            embed.add_field(name="⏰ المدة", value=f"{MUTE_DURATION} دقيقة", inline=True)
            await send_log(message.guild, embed)
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
        title="🔐 توثيق السيرفر",
        description="اضغط على زر **✅ توثيق** أدناه للحصول على صلاحية الوصول لبقية السيرفر!\n\n🛡️ **الحماية النشطة**",
        color=0x00ff00
    )
    embed.set_footer(text="نظام التوثيق والحماية MSA")
    
    await ctx.send(embed=embed, view=VerifyButton())
    print(f"✅ Verification message created in #{ctx.channel.name}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_logs(ctx):
    """إنشاء روم اللوقات المخفي"""
    await ctx.message.delete()
    
    # إنشاء الروم مع صلاحيات مخفية
    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    
    log_channel = await ctx.guild.create_text_channel(
        name="📋・logs",
        overwrites=overwrites,
        reason="نظام اللوقات - MSA"
    )
    
    embed = discord.Embed(
        title="✅ تم إنشاء نظام اللوقات",
        description=f"روم اللوقات: {log_channel.mention}\n🔒 مخفي عن الجميع ما عدا الأدمن",
        color=0x00ff00
    )
    await ctx.send(embed=embed, delete_after=10)
    print(f"✅ Logs channel created: #{log_channel.name}")

async def send_log(guild, embed):
    """إرسال لوق للروم المخصص"""
    log_channel = discord.utils.get(guild.text_channels, name="📋・logs")
    if log_channel:
        await log_channel.send(embed=embed)

@bot.event
async def on_guild_channel_delete(channel):
    """لوق حذف روم"""
    await asyncio.sleep(1)
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        if entry.target.id == channel.id:
            embed = discord.Embed(
                title="🔴 حذف روم",
                color=0xff0000,
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 الشخص", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="📝 اسم الروم", value=channel.name, inline=True)
            embed.add_field(name="🆔 ID الروم", value=channel.id, inline=True)
            await send_log(channel.guild, embed)
            break

@bot.event
async def on_member_ban(guild, user):
    """لوق باند"""
    await asyncio.sleep(1)
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        if entry.target.id == user.id:
            embed = discord.Embed(
                title="🔴 باند عضو",
                color=0xff0000,
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="🎯 العضو", value=f"{user.mention} ({user.id})", inline=False)
            embed.add_field(name="📝 السبب", value=entry.reason or "لا يوجد", inline=False)
            await send_log(guild, embed)
            break

@bot.event
async def on_member_unban(guild, user):
    """لوق فك باند"""
    await asyncio.sleep(1)
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
        if entry.target.id == user.id:
            embed = discord.Embed(
                title="🟢 فك باند",
                color=0x00ff00,
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="🎯 العضو", value=f"{user.name} ({user.id})", inline=False)
            await send_log(guild, embed)
            break

@bot.event
async def on_member_kick(member):
    """لوق كيك"""
    await asyncio.sleep(1)
    async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
        if entry.target.id == member.id:
            embed = discord.Embed(
                title="🔴 طرد عضو",
                color=0xff0000,
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="🎯 العضو", value=f"{member.mention} ({member.id})", inline=False)
            embed.add_field(name="📝 السبب", value=entry.reason or "لا يوجد", inline=False)
            await send_log(member.guild, embed)
            break

@bot.event
async def on_message_delete(message):
    """لوق حذف رسالة"""
    if message.author.bot:
        return
    
    await asyncio.sleep(1)
    async for entry in message.guild.audit_logs(limit=1, action=discord.AuditLogAction.message_delete):
        embed = discord.Embed(
            title="🔴 حذف رسالة",
            color=0xff0000,
            timestamp=datetime.now()
        )
        embed.add_field(name="👤 الكاتب", value=f"{message.author.mention} ({message.author.id})", inline=False)
        embed.add_field(name="📝 المحتوى", value=message.content[:1024] if message.content else "لا يوجد", inline=False)
        embed.add_field(name="📍 الروم", value=message.channel.mention, inline=True)
        await send_log(message.guild, embed)
        break

@bot.event
async def on_message_edit(before, after):
    """لوق تعديل رسالة"""
    if before.author.bot or before.content == after.content:
        return
    
    embed = discord.Embed(
        title="🟡 تعديل رسالة",
        color=0xffff00,
        timestamp=datetime.now()
    )
    embed.add_field(name="👤 الشخص", value=f"{before.author.mention} ({before.author.id})", inline=False)
    embed.add_field(name="📝 قبل", value=before.content[:1024] if before.content else "لا يوجد", inline=False)
    embed.add_field(name="📝 بعد", value=after.content[:1024] if after.content else "لا يوجد", inline=False)
    embed.add_field(name="📍 الروم", value=before.channel.mention, inline=True)
    await send_log(before.guild, embed)

@bot.event
async def on_member_update(before, after):
    """لوق تغيير الاسم أو الرولات"""
    # تغيير الاسم
    if before.nick != after.nick:
        embed = discord.Embed(
            title="🟡 تغيير الاسم",
            color=0xffff00,
            timestamp=datetime.now()
        )
        embed.add_field(name="👤 العضو", value=f"{after.mention} ({after.id})", inline=False)
        embed.add_field(name="📝 قبل", value=before.nick or before.name, inline=True)
        embed.add_field(name="📝 بعد", value=after.nick or after.name, inline=True)
        await send_log(after.guild, embed)
    
    # إضافة رول
    if len(before.roles) < len(after.roles):
        new_role = list(set(after.roles) - set(before.roles))[0]
        await asyncio.sleep(1)
        async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
            embed = discord.Embed(
                title="🟢 إعطاء رول",
                color=0x00ff00,
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="🎯 العضو", value=f"{after.mention} ({after.id})", inline=False)
            embed.add_field(name="📝 الرول", value=new_role.mention, inline=True)
            await send_log(after.guild, embed)
            break
    
    # سحب رول
    if len(before.roles) > len(after.roles):
        removed_role = list(set(before.roles) - set(after.roles))[0]
        await asyncio.sleep(1)
        async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
            embed = discord.Embed(
                title="🔴 سحب رول",
                color=0xff0000,
                timestamp=datetime.now()
            )
            embed.add_field(name="👤 المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="🎯 العضو", value=f"{after.mention} ({after.id})", inline=False)
            embed.add_field(name="📝 الرول", value=removed_role.name, inline=True)
            await send_log(after.guild, embed)
            break

@bot.event
async def on_voice_state_update(member, before, after):
    """لوق الرومات الصوتية"""
    # دخول روم صوتي
    if before.channel is None and after.channel is not None:
        embed = discord.Embed(
            title="🟢 دخول روم صوتي",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        embed.add_field(name="👤 العضو", value=f"{member.mention} ({member.id})", inline=False)
        embed.add_field(name="🔊 الروم", value=after.channel.name, inline=True)
        await send_log(member.guild, embed)
    
    # خروج من روم صوتي
    elif before.channel is not None and after.channel is None:
        embed = discord.Embed(
            title="🔴 خروج من روم صوتي",
            color=0xff0000,
            timestamp=datetime.now()
        )
        embed.add_field(name="👤 العضو", value=f"{member.mention} ({member.id})", inline=False)
        embed.add_field(name="🔊 الروم", value=before.channel.name, inline=True)
        await send_log(member.guild, embed)
    
    # تنقل بين رومات
    elif before.channel != after.channel and before.channel is not None and after.channel is not None:
        embed = discord.Embed(
            title="🟡 تنقل بين رومات صوتية",
            color=0xffff00,
            timestamp=datetime.now()
        )
        embed.add_field(name="👤 العضو", value=f"{member.mention} ({member.id})", inline=False)
        embed.add_field(name="🔊 من", value=before.channel.name, inline=True)
        embed.add_field(name="🔊 إلى", value=after.channel.name, inline=True)
        await send_log(member.guild, embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx):
    """حذف كل الرسائل من الروم الحالي
    
    الاستخدام:
    !clear - حذف كل الرسائل
    """
    try:
        # حذف كل الرسائل
        deleted = await ctx.channel.purge(limit=None)
        msg = await ctx.send(f"✅ تم حذف {len(deleted)} رسالة من {ctx.channel.mention}")
        
        # حذف رسالة التأكيد بعد 3 ثواني
        await asyncio.sleep(3)
        await msg.delete()
        
        # لوق حذف الرسائل
        embed = discord.Embed(
            title="🗑️ حذف رسائل",
            color=0xff6600,
            timestamp=datetime.now()
        )
        embed.add_field(name="👤 المسؤول", value=f"{ctx.author.mention} ({ctx.author.id})", inline=False)
        embed.add_field(name="📍 الروم", value=ctx.channel.mention, inline=True)
        embed.add_field(name="📊 العدد", value=len(deleted), inline=True)
        await send_log(ctx.guild, embed)
        
        print(f"🗑️ {ctx.author.name} cleared {len(deleted)} messages from #{ctx.channel.name}")
    except discord.Forbidden:
        await ctx.send("❌ ليس لدي صلاحية حذف الرسائل!", delete_after=5)
    except Exception as e:
        await ctx.send(f"❌ خطأ: {e}", delete_after=5)

@bot.command()
@commands.has_permissions(administrator=True)
async def restart(ctx):
    """إعادة تشغيل البوت"""
    await ctx.send("🔄 إعادة تشغيل البوت...")
    await bot.close()
    os.execv(sys.executable, ['python'] + sys.argv)

@clear.error
async def clear_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ تحتاج صلاحية Manage Messages لاستخدام هذا الأمر!", delete_after=5)
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ استخدام خاطئ! مثال: `!clear` أو `!clear 50`", delete_after=5)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need Administrator permissions to use this command!", delete_after=5)

# تشغيل البوت
print("🚀 Starting verification & protection bot...")
bot.run(TOKEN)
