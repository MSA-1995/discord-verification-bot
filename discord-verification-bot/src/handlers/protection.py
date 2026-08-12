import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio
import logging
import re
import os
from src.utils.embed_utils import build_log_embed, get_audit_entry

logger = logging.getLogger(__name__)

# إعدادات الحماية
SPAM_THRESHOLD = 5
SPAM_TIMEFRAME = 10
MUTE_DURATION = 30

DISCORD_INVITE_PATTERN = re.compile(
    r'(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/\S+',
    re.IGNORECASE
)

LINK_PATTERN = re.compile(
    r'https?://\S+'           # http:// أو https://
    r'|discord\.gg/\S+'       # discord.gg/invite
    r'|www\.\S+'              # www.example.com
    r'|\S+\.(com|net|org|io|me|cc|gg|xyz|tk|ml|ga|cf|gq|ru|cn|info|biz|co|tv|ly|link|click|top|online|site|website|store|shop)\b'
, re.IGNORECASE)


def is_discord_invite(content):
    return bool(DISCORD_INVITE_PATTERN.search(content or ""))


def can_send_invite(member):
    return bool(member.guild_permissions.administrator)


def get_invite_create_action(member, invite):
    if member is None:
        return "log_unknown"
    if can_send_invite(member):
        if getattr(invite, "max_uses", 0) != 1:
            return "replace_with_single_use"
        return "log_only"
    return "delete_and_log"


def format_invite_max_uses(invite):
    max_uses = getattr(invite, "max_uses", 0)
    return "غير محدود" if not max_uses else str(max_uses)


def format_invite_max_age(invite):
    max_age = getattr(invite, "max_age", 0)
    return "لا تنتهي" if not max_age else f"{max_age} ثانية"


def format_invite_temporary(invite):
    return "Yes" if getattr(invite, "temporary", False) else "No"


class Protection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_messages = defaultdict(list)
        self.cleanup_messages_task.start()

    def cog_unload(self):
        self.cleanup_messages_task.cancel()

    @tasks.loop(minutes=5)
    async def cleanup_messages_task(self):
        now = datetime.now()
        to_delete = []
        for user_id, timestamps in self.user_messages.items():
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
    # نقطة 5: logging.error بدل except Exception: pass
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
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("send_security_log failed: %s", e)
            except Exception as e:
                logger.error("send_security_log unexpected error: %s", e)

    # =====================================================
    # نقطة 8: _build_log_embed و _get_audit_entry من embed_utils
    # =====================================================
    def _build_log_embed(self, **kwargs):
        return build_log_embed(self.bot, **kwargs)

    async def _get_audit_entry(self, guild, action, target_id: int):
        return await get_audit_entry(guild, action, target_id)

    # =====================================================
    # نقطة 9: دالة مساعدة للـ ban عبر queue
    # =====================================================
    async def _queue_ban(self, member, reason, delete_message_days=1):
        """يرسل عملية الباند للـ shared queue في main.py"""
        verification_cog = self.bot.get_cog('Verification')
        if verification_cog:
            await verification_cog.queue_task(self._do_ban, member, reason, delete_message_days)
        else:
            # fallback مباشر إذا لم يكن الـ cog موجوداً
            await self._do_ban(member, reason, delete_message_days)

    async def _do_ban(self, member, reason, delete_message_days=1):
        try:
            await member.ban(reason=reason, delete_message_days=delete_message_days)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Ban failed for %s: %s", member.id, e)

    # =====================================================
    # on_message
    # =====================================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        # Honeypot - باند فوري لأي شخص يكتب في روم بترقوري شات
        honeypot_channel = discord.utils.get(message.guild.text_channels, name="تحذير")
        if honeypot_channel and message.channel.id == honeypot_channel.id:
            member = message.author
            try:
                await message.delete()
                embed = self._build_log_embed(
                    action_type="ban",
                    title="باند | Honeypot",
                    member=member,
                    reason=f"كتب في روم الـ Honeypot: `{message.content[:200]}`",
                    channel=message.channel,
                    extra_fields=[("الإجراء", "باند فوري")]
                )
                await self.send_security_log(message.guild, embed)
                await self._queue_ban(member, "🚫 Honeypot triggered - auto ban")
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("Honeypot ban error: %s", e)
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
                    await self._queue_ban(member, "🚫 Unauthorized command usage - auto ban")
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error("on_message command ban error: %s", e)
                return

        # 1. فحص دعوات الديسكورد - فقط الأدمنستريتور يرسلها
        if is_discord_invite(message.content) and not can_send_invite(member):
            try:
                await message.delete()
                await message.channel.send(
                    f"{member.mention} تم حظرك نهائياً بسبب إرسال دعوة ديسكورد.",
                    delete_after=10
                )
                embed = self._build_log_embed(
                    action_type="ban",
                    title="باند | إرسال دعوة ديسكورد",
                    member=member,
                    reason="قام بإرسال دعوة ديسكورد",
                    channel=message.channel,
                    extra_fields=[
                        ("الدعوة", message.content[:500]),
                        ("الإجراء", "حذف الرسالة + باند نهائي")
                    ]
                )
                await self.send_security_log(message.guild, embed)
                await self._queue_ban(member, "🚫 Posted Discord invite - auto ban")
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("on_message discord invite ban error: %s", e)
            return

        # 2. فحص الروابط - باند مباشر
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
                await self._queue_ban(member, "🚫 Posted links - auto ban")
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("on_message link ban error: %s", e)
            return

        # 2. فحص السبام
        now = datetime.now()
        self.user_messages[member.id].append(now)
        self.user_messages[member.id] = [
            t for t in self.user_messages[member.id]
            if (now - t).total_seconds() < SPAM_TIMEFRAME
        ]

        if len(self.user_messages[member.id]) >= SPAM_THRESHOLD:
            try:
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
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("on_message spam timeout error: %s", e)

    # =====================================================
    # on_invite_create - تسجيل وإنفاذ إنشاء دعوات السيرفر
    # =====================================================
    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        guild = invite.guild
        inviter = getattr(invite, "inviter", None)
        if inviter and self.bot.user and inviter.id == self.bot.user.id:
            return

        member = guild.get_member(inviter.id) if inviter else None
        action = get_invite_create_action(member, invite)
        effective_invite = invite

        if action == "delete_and_log":
            try:
                await invite.delete(reason="🚫 Only administrators can create server invites")
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("invite delete failed for %s: %s", getattr(invite, "code", "unknown"), e)
        elif action == "replace_with_single_use":
            try:
                await invite.delete(reason="🚫 Server invites must be single-use")
                effective_invite = await invite.channel.create_invite(
                    max_age=getattr(invite, "max_age", 0) or 0,
                    max_uses=1,
                    temporary=getattr(invite, "temporary", False),
                    unique=True,
                    reason="✅ Replaced admin invite with a single-use invite",
                )
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("invite replace failed for %s: %s", getattr(invite, "code", "unknown"), e)

        title = "دعوة سيرفر | إنشاء دعوة"
        if action == "delete_and_log":
            title = "دعوة سيرفر | إنشاء دعوة غير مصرح"
        elif action == "replace_with_single_use":
            title = "دعوة سيرفر | استبدال بدعوة استخدام واحد"
        elif action == "log_unknown":
            title = "دعوة سيرفر | منشئ غير معروف"

        fields = [
            ("رمز الدعوة", getattr(effective_invite, "code", "غير معروف"), True),
            ("الحد الأقصى للاستخدامات", format_invite_max_uses(effective_invite), True),
            ("تنتهي بعد", format_invite_max_age(effective_invite), True),
            ("عضوية مؤقتة", format_invite_temporary(effective_invite), True),
        ]
        if inviter:
            fields.extend([
                ("المستخدم", inviter.mention, True),
                ("المُعرِّف", f"`{inviter.id}`", True),
            ])
        else:
            fields.append(("المستخدم", "غير معروف", True))

        fields.extend([
            ("الروم", effective_invite.channel.mention if effective_invite.channel else "غير معروف", True),
            ("الدعوة", getattr(effective_invite, "url", f"https://discord.gg/{effective_invite.code}"), False),
            (
                "الإجراء",
                "حذف الدعوة" if action == "delete_and_log"
                else "حذف الدعوة القديمة وإنشاء دعوة استخدام واحد" if action == "replace_with_single_use"
                else "تسجيل فقط",
                False,
            ),
        ])

        embed = self._build_log_embed(
            title=title,
            color=0xff0000 if action == "delete_and_log" else 0x3498db,
            member=member,
            user=inviter if not member else None,
            fields=fields,
        )
        await self.send_security_log(guild, embed)

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
                await self._queue_ban(adder_member, "🚫 Added unauthorized bot - only owner can add bots")
            else:
                embed = self._build_log_embed(
                    action_type="ban",
                    title="باند | بوت غير مصرح",
                    member=member,
                    reason=f"بوت غير مصرح أضافه: {adder.mention} ({adder.id})",
                    extra_fields=[("الإجراء", "باند البوت")]
                )
                await self.send_security_log(member.guild, embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("on_member_join bot ban error: %s", e)

    # =====================================================
    # on_guild_channel_create
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
                await self._queue_ban(member, "🚫 Unauthorized channel creation - auto ban")
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("on_guild_channel_create ban error: %s", e)

    # =====================================================
    # on_guild_role_create
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
                await self._queue_ban(member, "🚫 Unauthorized role creation - auto ban")
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("on_guild_role_create ban error: %s", e)

async def setup(bot):
    await bot.add_cog(Protection(bot))
