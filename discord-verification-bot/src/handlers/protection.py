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

LINK_PATTERN = re.compile(
    r'https?://\S+'           # http:// أو https://
    r'|discord\.gg/\S+'       # discord.gg/invite
    r'|www\.\S+'              # www.example.com
    r'|\S+\.(com|net|org|io|me|cc|gg|xyz|tk|ml|ga|cf|gq|ru|cn|info|biz|co|tv|ly|link|click|top|online|site|website|store|shop)\b'  # أي دومين معروف
, re.IGNORECASE)

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

    def _build_log_embed(self, *, action_type, title, member, reason, channel=None, extra_fields=None, guild=None):
        """بناء embed موحد للوقات الحماية"""
        # ألوان حسب نوع الإجراء
        colors = {
            "ban": 0xff0000,      # أحمر - باند
            "timeout": 0xff6600,  # برتقالي - تايم أوت
            "kick": 0xffaa00,     # أصفر - كيك
            "info": 0x3498db,     # أزرق - معلومات
        }
        color = colors.get(action_type, 0xff0000)

        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=datetime.now()
        )

        # Author row - اسم البوت + لوقو صغير
        bot_avatar = self.bot.user.avatar.url if self.bot.user.avatar else None
        embed.set_author(name="نظام الحماية", icon_url=bot_avatar)

        # صورة العضو كـ thumbnail
        if hasattr(member, 'avatar') and member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        elif hasattr(member, 'default_avatar'):
            embed.set_thumbnail(url=member.default_avatar.url)

        # الحقول الأساسية
        embed.add_field(name="العضو", value=f"{member.mention}", inline=True)
        embed.add_field(name="الآيدي", value=f"`{member.id}`", inline=True)

        if channel:
            embed.add_field(name="القناة", value=f"{channel.mention}" if hasattr(channel, 'mention') else str(channel), inline=True)

        embed.add_field(name="السبب", value=reason[:1024], inline=False)

        # حقول إضافية
        if extra_fields:
            for name, value in extra_fields:
                embed.add_field(name=name, value=value, inline=True)

        # Footer
        embed.set_footer(text="نظام الحماية | MSA")

        return embed

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
            if not message.content.startswith("!") and not message.content.startswith("/"):
                return

        member = message.author

        # 0. فحص الأوامر - فقط الأونر يستخدم أوامر
        if message.content.startswith("!") or message.content.startswith("/"):
            if message.author.id != message.guild.owner_id:
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{member.mention} تم حظرك نهائياً بسبب استخدام أوامر غير مصرح بها.",
                        delete_after=10
                    )

                    embed = self._build_log_embed(
                        action_type="ban",
                        title="باند | استخدام أوامر",
                        member=member,
                        reason=f"كتب أمر: `{message.content[:200]}`",
                        channel=message.channel,
                        extra_fields=[("الإجراء", "حذف + باند نهائي")]
                    )
                    await self.send_security_log(message.guild, embed)

                    await member.ban(reason="🚫 Unauthorized command usage - auto ban", delete_message_days=1)
                except discord.Forbidden:
                    pass
                except discord.HTTPException:
                    pass
                return

        # 1. فحص الروابط - باند مباشر
        if LINK_PATTERN.search(message.content):
            try:
                await message.delete()
                await message.channel.send(
                    f"{member.mention} تم حظرك نهائياً بسبب إرسال روابط.",
                    delete_after=10
                )

                embed = self._build_log_embed(
                    action_type="ban",
                    title="باند | إرسال روابط",
                    member=member,
                    reason=message.content[:500],
                    channel=message.channel,
                    extra_fields=[("الإجراء", "حذف الرسالة + باند نهائي")]
                )
                await self.send_security_log(message.guild, embed)

                await member.ban(reason="🚫 Posted links - auto ban", delete_message_days=1)
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
                # حذف رسائل الشخص من القناة
                def is_spammer(m):
                    return m.author.id == member.id
                await message.channel.purge(limit=50, check=is_spammer)

                await member.timeout(timedelta(minutes=MUTE_DURATION), reason="🚫 Spamming")
                await message.channel.send(
                    f"{member.mention} تم إعطاؤك تايم أوت لمدة {MUTE_DURATION} دقيقة بسبب السبام.",
                    delete_after=10
                )

                embed = self._build_log_embed(
                    action_type="timeout",
                    title="تايم أوت | سبام",
                    member=member,
                    reason=f"إرسال {SPAM_THRESHOLD} رسائل في {SPAM_TIMEFRAME} ثواني",
                    channel=message.channel,
                    extra_fields=[
                        ("الإجراء", "حذف رسائله + تايم أوت"),
                        ("المدة", f"{MUTE_DURATION} دقيقة")
                    ]
                )
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
            await member.ban(reason="🚫 Unauthorized bot - only owner can add bots")

            # باند الشخص اللي أضاف البوت
            adder = entry.user
            adder_member = member.guild.get_member(adder.id)
            if adder_member:
                embed = self._build_log_embed(
                    action_type="ban",
                    title="باند | إضافة بوت غير مصرح",
                    member=adder_member,
                    reason=f"أضاف بوت: {member.name} ({member.id})",
                    extra_fields=[
                        ("البوت", f"{member.name} (`{member.id}`)"),
                        ("الإجراء", "باند البوت + باند من أضافه")
                    ]
                )
                await self.send_security_log(member.guild, embed)

                await adder_member.ban(reason="🚫 Added unauthorized bot - only owner can add bots", delete_message_days=1)
            else:
                embed = self._build_log_embed(
                    action_type="ban",
                    title="باند | بوت غير مصرح",
                    member=member,
                    reason=f"بوت غير مصرح أضافه: {adder.mention} ({adder.id})",
                    extra_fields=[("الإجراء", "باند البوت")]
                )
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

            member = channel.guild.get_member(creator.id)
            if member:
                embed = self._build_log_embed(
                    action_type="ban",
                    title="باند | إنشاء روم",
                    member=member,
                    reason=f"أنشأ روم: **{channel.name}**",
                    extra_fields=[("الإجراء", "حذف الروم + باند نهائي")]
                )
                await self.send_security_log(channel.guild, embed)

                await member.ban(reason="🚫 Unauthorized channel creation - auto ban", delete_message_days=1)
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
                embed = self._build_log_embed(
                    action_type="ban",
                    title="باند | إنشاء رول",
                    member=member,
                    reason=f"أنشأ رول: **{role.name}**",
                    extra_fields=[("الإجراء", "حذف الرول + باند نهائي")]
                )
                await self.send_security_log(role.guild, embed)

                await member.ban(reason="🚫 Unauthorized role creation - auto ban", delete_message_days=1)
        except (discord.Forbidden, discord.HTTPException):
            pass

async def setup(bot):
    await bot.add_cog(Protection(bot))
