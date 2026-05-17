import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio
import re
import os

# إعدادات الحماية
SPAM_THRESHOLD = 5
SPAM_TIMEFRAME = 10
MUTE_DURATION = 30

LINK_PATTERN = re.compile(r'https?://\S+|discord\.gg/\S+', re.IGNORECASE)

class Protection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_messages = defaultdict(list)
        self.cleanup_messages_task.start()

    def cog_unload(self):
        self.cleanup_messages_task.cancel()

    # =====================================================
    # FIX 1: تنظيف دوري لـ user_messages كل 5 دقائق
    # =====================================================
    @tasks.loop(minutes=5)
    async def cleanup_messages_task(self):
        now = datetime.now()
        to_delete = []
        for user_id, timestamps in self.user_messages.items():
            # FIX 2: total_seconds() بدل .seconds
            valid = [t for t in timestamps if (now - t).total_seconds() < SPAM_TIMEFRAME]
            if valid:
                self.user_messages[user_id] = valid
            else:
                to_delete.append(user_id)
        for user_id in to_delete:
            del self.user_messages[user_id]

    @cleanup_messages_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # =====================================================
    # FIX 3: error handling لـ send_security_log
    # =====================================================
    async def send_security_log(self, guild, embed):
        log_channel_id = os.getenv("LOG_CHANNEL_ID")
        log_channel = None
        if log_channel_id and log_channel_id.isdigit():
            log_channel = guild.get_channel(int(log_channel_id))
        if not log_channel:
            log_channel = discord.utils.get(guild.text_channels, name="📋・logs")
        if log_channel:
            try:
                await log_channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
            except Exception:
                pass  # ConnectionReset/DNS errors - skip silently

    # =====================================================
    # FIX 4: دالة مساعدة لجلب audit log مع filter زمني
    # =====================================================
    async def _get_audit_entry(self, guild, action, target_id: int):
        after_time = datetime.utcnow() - timedelta(seconds=5)
        try:
            async for entry in guild.audit_logs(limit=5, action=action, after=after_time):
                if entry.target.id == target_id:
                    return entry
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    # =====================================================
    # on_message
    # =====================================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        if message.author.guild_permissions.administrator:
            return

        member = message.author

        # 1. فحص الروابط
        if LINK_PATTERN.search(message.content):
            try:
                await message.delete()
                await member.timeout(timedelta(minutes=MUTE_DURATION), reason="🚫 Posted links")
                await message.channel.send(
                    f"⚠️ {member.mention} تم إعطاؤك تايم أوت لمدة {MUTE_DURATION} دقيقة بسبب إرسال روابط.",
                    delete_after=10
                )

                embed = discord.Embed(title="لوق الحماية - ميوت روابط", color=0xff6600, timestamp=datetime.now())
                embed.add_field(name="العضو",   value=f"{member.mention} ({member.id})", inline=False)
                embed.add_field(name="المحتوى", value=message.content[:1024],             inline=False)
                embed.add_field(name="المدة",   value=f"{MUTE_DURATION} دقيقة",           inline=True)
                embed.set_thumbnail(url=message.guild.icon.url if message.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_security_log(message.guild, embed)
            except discord.Forbidden:
                pass
            except discord.HTTPException:
                pass

            return

        # 2. فحص السبام
        now = datetime.now()
        self.user_messages[member.id].append(now)

        # FIX 2: total_seconds() بدل .seconds
        self.user_messages[member.id] = [
            t for t in self.user_messages[member.id]
            if (now - t).total_seconds() < SPAM_TIMEFRAME
        ]

        if len(self.user_messages[member.id]) >= SPAM_THRESHOLD:
            try:
                await member.timeout(timedelta(minutes=MUTE_DURATION), reason="🚫 Spamming")
                await message.channel.send(
                    f"⚠️ {member.mention} تم إعطاؤك تايم أوت لمدة {MUTE_DURATION} دقيقة بسبب السبام.",
                    delete_after=10
                )

                embed = discord.Embed(title="لوق الحماية - ميوت سبام", color=0xff6600, timestamp=datetime.now())
                embed.add_field(name="العضو",  value=f"{member.mention} ({member.id})",                         inline=False)
                embed.add_field(name="السبب",  value=f"إرسال {SPAM_THRESHOLD} رسائل في {SPAM_TIMEFRAME} ثواني", inline=False)
                embed.add_field(name="المدة",  value=f"{MUTE_DURATION} دقيقة",                                   inline=True)
                embed.set_thumbnail(url=message.guild.icon.url if message.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_security_log(message.guild, embed)

                self.user_messages[member.id].clear()
            except discord.Forbidden:
                pass
            except discord.HTTPException:
                pass

    # =====================================================
    # on_member_join - منع البوتات
    # =====================================================
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not member.bot:
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(member.guild, discord.AuditLogAction.bot_add, member.id)
        if not entry:
            return

        if entry.user.id == member.guild.owner_id:
            print(f"✅ Owner added bot: {member.name}")
            return

        try:
            await member.kick(reason="🚫 Only owner can add bots")

            embed = discord.Embed(title="لوق الحماية - طرد بوت", color=0xff0000, timestamp=datetime.now())
            embed.add_field(name="البوت",    value=f"{member.name} ({member.id})",           inline=False)
            embed.add_field(name="من أضافه", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_security_log(member.guild, embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # =====================================================
    # FIX 6: on_guild_channel_create - تحذير قبل الباند
    # =====================================================
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await asyncio.sleep(1)
        entry = await self._get_audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        if not entry:
            return

        creator = entry.user

        if creator.id == self.bot.user.id:
            return

        # FIX 6: فقط من ليس أدمن وليس بوت = إجراء
        if creator.guild_permissions.administrator or creator.bot:
            return

        try:
            await channel.delete(reason="🚫 Unauthorized channel creation")

            # تحذير أول مرة بدل باند مباشر
            member = channel.guild.get_member(creator.id)
            if member:
                try:
                    await member.send(
                        f"⚠️ تحذير: قمت بإنشاء روم غير مصرح به في **{channel.guild.name}**.\n"
                        f"سيتم حظرك إذا تكررت هذه العملية."
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

                await member.timeout(timedelta(minutes=60), reason="🚫 Unauthorized channel creation")

            embed = discord.Embed(title="لوق الحماية - إنشاء روم غير مصرح", color=0xff0000, timestamp=datetime.now())
            embed.add_field(name="الشخص",    value=f"{creator.mention} ({creator.id})", inline=False)
            embed.add_field(name="الروم",    value=channel.name,                        inline=True)
            embed.add_field(name="الإجراء",  value="حذف الروم + تايم أوت 60 دقيقة",   inline=False)
            embed.set_thumbnail(url=channel.guild.icon.url if channel.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_security_log(channel.guild, embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # =====================================================
    # FIX 6: on_guild_role_create - تحذير قبل الباند
    # =====================================================
    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await asyncio.sleep(1)
        entry = await self._get_audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        if not entry:
            return

        creator = entry.user

        if creator.id == self.bot.user.id:
            return

        if creator.guild_permissions.administrator:
            return

        try:
            await role.delete(reason="🚫 Unauthorized role creation")

            member = role.guild.get_member(creator.id)
            if member:
                try:
                    await member.send(
                        f"⚠️ تحذير: قمت بإنشاء رول غير مصرح به في **{role.guild.name}**.\n"
                        f"سيتم حظرك إذا تكررت هذه العملية."
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

                await member.timeout(timedelta(minutes=60), reason="🚫 Unauthorized role creation")

            embed = discord.Embed(title="لوق الحماية - إنشاء رول غير مصرح", color=0xff0000, timestamp=datetime.now())
            embed.add_field(name="الشخص",   value=f"{creator.mention} ({creator.id})", inline=False)
            embed.add_field(name="الرول",   value=role.name,                            inline=True)
            embed.add_field(name="الإجراء", value="حذف الرول + تايم أوت 60 دقيقة",    inline=False)
            embed.set_thumbnail(url=role.guild.icon.url if role.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_security_log(role.guild, embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

async def setup(bot):
    await bot.add_cog(Protection(bot))
