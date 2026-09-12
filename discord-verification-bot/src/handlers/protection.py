import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import asyncio
import logging
import re
import os
import unicodedata
from src.utils.embed_utils import build_log_embed, get_audit_entry
from src.config import channels_config

logger = logging.getLogger(__name__)

# إعدادات الحماية
SPAM_THRESHOLD = 5
SPAM_TIMEFRAME = 10
MUTE_DURATION = 30

# إعدادات Raid Detection
JOIN_RAID_THRESHOLD = 10   # عدد الأعضاء
JOIN_RAID_WINDOW     = 15  # ثانية
BOT_RAID_THRESHOLD   = 3   # عدد البوتات
BOT_RAID_WINDOW      = 30  # ثانية
LOCKDOWN_AUTO_LIFT   = 600 # ثانية (10 دقائق)
DELETE_ABUSE_THRESHOLD = 2
DELETE_ABUSE_WINDOW = 20

LINK_PATTERN = re.compile(
    r'discord\.gg/\S+'
    r'|discord\.com/invite/\S+'
    # روابط مختصرة مشبوهة
    r'|bit\.ly/\S+'
    r'|tinyurl\.com/\S+'
    r'|t\.co/\S+'
    r'|ow\.ly/\S+'
    r'|is\.gd/\S+'
    r'|buff\.ly/\S+'
    r'|rb\.gy/\S+'
    r'|cutt\.ly/\S+'
    r'|shorturl\.at/\S+'
    # مواقع phishing / trojan معروفة
    r'|grabify\.link/\S+'
    r'|iplogger\.org/\S+'
    r'|iplogger\.com/\S+'
    r'|2no\.co/\S+'
    r'|yip\.su/\S+'
    r'|ps3cfw\.com/\S+'
    r'|freegiftcards?\.\S+'
    r'|steamcommunit[yi]\.\S+'
    r'|steampowerd\.\S+'
    r'|discordapp\.net/\S+'
    r'|discordgift\.\S+'
    r'|discord-gift\.\S+'
    r'|discord-nitro\.\S+'
    r'|dlscord\.\S+'
    r'|discordnitro\.\S+'
    r'|nitro-discord\.\S+'
    r'|free-nitro\.\S+'
    r'|freenitr[o0]\.\S+'
, re.IGNORECASE)

# محارف invisible / zero-width شائعة تستخدم للتحايل على فلاتر الروابط
# (مثال: "discord\u200b.gg/xxx" يفوت الـ regex بدون تطبيع)
_ZERO_WIDTH_CHARS = re.compile(
    r'[\u200b\u200c\u200d\u200e\u200f\ufeff\u2060\u00ad]'
)


def _normalize_for_link_scan(text: str) -> str:
    """يطبّع النص عشان يصعّب التحايل على فلتر الروابط:
    - يشيل المحارف invisible/zero-width
    - يحول محارف يونيكود المشابهة (homoglyphs) لأقرب شكل ASCII عبر NFKC
    """
    if not text:
        return ""
    text = _ZERO_WIDTH_CHARS.sub("", text)
    text = unicodedata.normalize("NFKC", text)
    return text


def _collect_scannable_text(message: discord.Message) -> str:
    """يجمع كل النصوص اللي ممكن يكون فيها رابط بالرسالة: المحتوى + عناوين
    وأوصاف ووصلات أي embed مرفق، عشان رابط مخفي داخل embed ما يفوت الفحص."""
    parts = [message.content or ""]
    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        if embed.url:
            parts.append(embed.url)
    return "\n".join(parts)


class Protection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_messages = defaultdict(list)
        # Raid tracking
        self._join_timestamps: dict[int, list[float]] = defaultdict(list)
        self._bot_timestamps: dict[int, list[float]] = defaultdict(list)
        self._channel_delete_timestamps: dict[tuple[int, int], list[float]] = defaultdict(list)
        self._role_delete_timestamps: dict[tuple[int, int], list[float]] = defaultdict(list)
        self._lockdown_guilds: dict[int, asyncio.Task] = {}  # guild_id → auto-lift task
        self._original_verification: dict[int, discord.VerificationLevel] = {}  # guild_id → original level
        # Bot Raid: نتتبع البوتات اللي دخلت فعلاً بالنافذة الزمنية (مو كل بوتات السيرفر)
        self._recent_bot_joins: dict[int, list[discord.Member]] = defaultdict(list)
        # نخزن ID الروم الهانيبوت الفعلي لكل سيرفر بعد أول تحديد/إنشاء له،
        # عشان نعتمد على الـ ID (أدق وما ينكسر بتغيير الاسم) مو مقارنة الاسم فقط.
        # ملاحظة: هذا بالذاكرة فقط، يشتغل تلقائياً لأي عدد سيرفرات بدون أي تهيئة يدوية.
        self._honeypot_channel_ids: dict[int, int] = {}
        self._webhook_ban_timestamps: dict[int, float] = {}
        self.cleanup_messages_task.start()

    def cog_unload(self):
        self.cleanup_messages_task.cancel()
        for task in self._lockdown_guilds.values():
            task.cancel()

    def _spam_key(self, member):
        return (member.guild.id, member.id)

    # ================================================================
    # Raid Detection Helpers
    # ================================================================
    async def _check_join_raid(self, guild: discord.Guild):
        """يفحص إذا صار Join Raid ويقفل السيرفر"""
        now = datetime.now(timezone.utc).timestamp()
        timestamps = [
            t for t in self._join_timestamps[guild.id]
            if now - t < JOIN_RAID_WINDOW
        ]
        timestamps.append(now)
        self._join_timestamps[guild.id] = timestamps

        if len(timestamps) >= JOIN_RAID_THRESHOLD:
            if guild.id not in self._lockdown_guilds:
                self._join_timestamps[guild.id].clear()
                await self._activate_lockdown(guild, reason=f"🚨 Join Raid: {JOIN_RAID_THRESHOLD}+ أعضاء خلال {JOIN_RAID_WINDOW} ثانية")

    async def _check_bot_raid(self, guild: discord.Guild, new_bot: discord.Member):
        """يفحص إذا صار Bot Raid ويبند بس البوتات اللي دخلت فعلاً ضمن هذي
        النافذة الزمنية (مو كل بوتات السيرفر - عشان ما نبند بوتات موجودة
        من قبل أو بوتات ضافها الأونر نفسه بالغلط)."""
        now = datetime.now(timezone.utc).timestamp()

        # نحدّث قائمة (timestamp, member) سوا عشان نعرف بالضبط مين دخل بالنافذة
        kept = [
            (t, m) for t, m in zip(
                self._bot_timestamps[guild.id],
                self._recent_bot_joins[guild.id],
            )
            if now - t < BOT_RAID_WINDOW
        ]
        kept.append((now, new_bot))
        self._bot_timestamps[guild.id] = [t for t, _ in kept]
        self._recent_bot_joins[guild.id] = [m for _, m in kept]

        if len(kept) < BOT_RAID_THRESHOLD:
            return

        raid_bots = list(self._recent_bot_joins[guild.id])
        self._bot_timestamps[guild.id].clear()
        self._recent_bot_joins[guild.id].clear()
        count = len(raid_bots)

        banned = 0
        skipped_owner = 0
        for bot_member in raid_bots:
            if bot_member.id == self.bot.user.id:
                continue
            # نتحقق مين ضاف هالبوت بالذات - لو الأونر هو اللي ضافه نتجاهله
            entry = await self._get_audit_entry(guild, discord.AuditLogAction.bot_add, bot_member.id)
            if entry and entry.user.id == guild.owner_id:
                skipped_owner += 1
                continue
            try:
                await bot_member.ban(reason="🚫 Bot Raid - batch ban", delete_message_seconds=86400)
                banned += 1
            except (discord.Forbidden, discord.HTTPException):
                pass

        await self._activate_lockdown(guild, reason=f"🤖 Bot Raid: {count} بوت دخلوا خلال {BOT_RAID_WINDOW} ثانية")

        extra = [("Bot Raid", f"تم باند {banned}/{count} بوت فوراً")]
        if skipped_owner:
            extra.append(("تم تجاهلهم", f"{skipped_owner} بوت أضافهم الأونر"))

        embed = self._build_log_embed(
            action_type="ban",
            title=f"🤖 Bot Raid | باند {banned} بوت",
            member=new_bot,
            reason=f"دخل {count} بوت خلال {BOT_RAID_WINDOW} ثانية",
            extra_fields=extra
        )
        await self.send_security_log(guild, embed)
        await self._dm_owner(guild, f"🤖 **Bot Raid!**\n{count} بوت دخلوا خلال {BOT_RAID_WINDOW} ثانية.\nتم باند {banned} منهم فوراً وقفل السيرفر.")

    def _track_delete_abuse(self, tracker, guild_id: int, user_id: int) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        key = (guild_id, user_id)
        timestamps = [
            t for t in tracker[key]
            if now - t < DELETE_ABUSE_WINDOW
        ]
        timestamps.append(now)
        tracker[key] = timestamps
        return len(timestamps) >= DELETE_ABUSE_THRESHOLD

    def _is_protected_actor(self, guild: discord.Guild, actor) -> bool:
        return (
            actor.id == self.bot.user.id
            or actor.id == guild.owner_id
        )

    async def _handle_delete_abuse(self, guild, actor, item_name, item_type, tracker):
        if self._is_protected_actor(guild, actor):
            return

        triggered = self._track_delete_abuse(tracker, guild.id, actor.id)
        if not triggered:
            embed = self._build_log_embed(
                action_type="warn",
                title=f"تحذير | حذف {item_type}",
                member=actor,
                reason=f"حذف {item_type}: **{item_name}**",
                extra_fields=[("الإجراء", "مراقبة أول حذف")]
            )
            await self.send_security_log(guild, embed)
            return

        member = guild.get_member(actor.id)
        if not member:
            return

        banned = await self._queue_ban(member, f"🚫 Deleted 2 {item_type}s within {DELETE_ABUSE_WINDOW} seconds")

        if banned:
            embed = self._build_log_embed(
                action_type="ban",
                title=f"باند | حذف {item_type} متكرر",
                member=member,
                reason=f"حذف {DELETE_ABUSE_THRESHOLD} {item_type} خلال {DELETE_ABUSE_WINDOW} ثانية. آخر حذف: **{item_name}**",
                extra_fields=[("الإجراء", "باند نهائي")]
            )
        else:
            embed = self._build_ban_failed_embed(
                member,
                f"حذف {item_type} متكرر",
                f"حذف {DELETE_ABUSE_THRESHOLD} {item_type} خلال {DELETE_ABUSE_WINDOW} ثانية. آخر حذف: **{item_name}**"
            )
        await self.send_security_log(guild, embed)

    async def _activate_lockdown(self, guild: discord.Guild, reason: str):
        """يرفع verification level للسيرفر ويرسل تنبيه"""
        if guild.id in self._lockdown_guilds:
            return

        # حفظ المستوى الأصلي قبل القفل
        self._original_verification[guild.id] = guild.verification_level

        try:
            await guild.edit(
                verification_level=discord.VerificationLevel.highest,
                reason=reason
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Lockdown failed: %s", e)
            self._original_verification.pop(guild.id, None)
            return

        embed = self._build_log_embed(
            action_type="ban",
            title="🔒 قفل السيرفر | Lockdown",
            member=guild.me,
            reason=reason,
            extra_fields=[
                ("الإجراء", "Verification Level → Highest"),
                ("رفع تلقائي", f"بعد {LOCKDOWN_AUTO_LIFT//60} دقائق أو بأمر !unlock")
            ]
        )
        await self.send_security_log(guild, embed)
        await self._dm_owner(guild, f"🔒 **تم قفل السيرفر!**\nالسبب: {reason}\nاستخدم `!unlock` لرفع القفل يدوياً.")

        # auto-lift بعد LOCKDOWN_AUTO_LIFT ثانية
        task = asyncio.create_task(self._auto_lift_lockdown(guild))
        self._lockdown_guilds[guild.id] = task

    async def _auto_lift_lockdown(self, guild: discord.Guild):
        await asyncio.sleep(LOCKDOWN_AUTO_LIFT)
        await self._lift_lockdown(guild, auto=True)

    async def _lift_lockdown(self, guild: discord.Guild, auto=False):
        self._lockdown_guilds.pop(guild.id, None)
        # رجوع للمستوى الأصلي قبل القفل
        original = self._original_verification.pop(guild.id, discord.VerificationLevel.low)
        try:
            await guild.edit(
                verification_level=original,
                reason="رفع قفل السيرفر"
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Lift lockdown failed: %s", e)
            return

        msg = "تلقائياً" if auto else "يدوياً"
        embed = self._build_log_embed(
            action_type="info",
            title=f"🔓 رفع قفل السيرفر ({msg})",
            member=guild.me,
            reason=f"تم رفع القفل {msg}",
            extra_fields=[("الإجراء", f"Verification Level → {original.name}")]
        )
        await self.send_security_log(guild, embed)

    async def _dm_owner(self, guild: discord.Guild, message: str):
        owner = guild.owner
        if not owner:
            return
        try:
            embed = discord.Embed(
                title="🚨 تنبيه عاجل",
                description=f"**سيرفر:** {guild.name}\n\n{message}",
                color=0xff0000,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="نظام الحماية | ᴹˢᴬ")
            await owner.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ================================================================
    # أمر !unlock
    # ================================================================
    @commands.command(name="unlock")
    async def unlock_cmd(self, ctx):
        if ctx.author.id != ctx.guild.owner_id:
            await ctx.message.delete()
            return
        await ctx.message.delete()
        task = self._lockdown_guilds.get(ctx.guild.id)
        if task:
            task.cancel()
        await self._lift_lockdown(ctx.guild, auto=False)
        await ctx.send("🔓 تم رفع قفل السيرفر.", delete_after=5)

    # ------------------------------------------------------------------ #
    def _get_honeypot_channel(self, guild: discord.Guild):
        """يرجع روم الهانيبوت لهذا السيرفر: يعتمد على الـ ID المخزّن بالذاكرة
        أولاً (أدق، ما ينكسر لو تغيّر اسم الروم)، ولو مو مخزّن بعد يرجع
        لمطابقة الاسم عبر channels_config ويخزّن الـ ID لأول مرة."""
        cached_id = self._honeypot_channel_ids.get(guild.id)
        if cached_id:
            channel = guild.get_channel(cached_id)
            if isinstance(channel, discord.TextChannel):
                return channel
            # الروم المخزّن انحذف أو تغيّر - نشيله من الكاش ونرجع نبحث بالاسم
            self._honeypot_channel_ids.pop(guild.id, None)

        channel = channels_config.get_honeypot_channel(guild)
        if channel:
            self._honeypot_channel_ids[guild.id] = channel.id
        return channel

    async def _setup_honeypot_message(self, guild: discord.Guild):
        channel = self._get_honeypot_channel(guild)
        if not channel:
            return
        # تحقق إذا الرسالة موجودة بالفعل
        async for msg in channel.history(limit=20):
            if msg.author.id == self.bot.user.id and msg.embeds:
                return  # موجودة، ما نرسل مرة ثانية
        embed = discord.Embed(
            title="تحذير",
            description="ممنوع الكتابة بهذا الروم، اي شخص يرسل هنا باند فوري",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        bot_avatar = self.bot.user.avatar.url if self.bot.user.avatar else None
        embed.set_author(name="نظام الحماية", icon_url=bot_avatar)
        embed.set_footer(text="نظام الحماية | ᴹˢᴬ")
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning("honeypot: failed to send warning message: %s", e)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._setup_honeypot_message(guild)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        # نستخدم النسخة الـ raw لأنها تشتغل دايماً حتى لو الرسالة مو موجودة
        # بالكاش الداخلي للبوت (زي بعد إعادة تشغيل البوت أو امتلاء الكاش)
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
        honeypot_channel = self._get_honeypot_channel(guild)
        if not honeypot_channel or channel.id != honeypot_channel.id:
            return
        # لو عندنا الرسالة بالكاش نتأكد إنها من البوت، غير كذا نتحقق فقط من الروم
        cached = payload.cached_message
        if cached and cached.author.id != self.bot.user.id:
            return
        # _setup_honeypot_message نفسها تتحقق إذا فيه embed من البوت موجود
        # بآخر 20 رسالة، فما راح ترسل مكررة لو ما احتاجت
        await self._setup_honeypot_message(guild)

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
        log_channel = channels_config.get_log_channel(guild)
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
    # تعيد True لو انبند فعلياً، False لو فشل أو تم تجاهله
    # =====================================================
    async def _queue_ban(self, member, reason, delete_message_seconds=86400):
        """يرسل عملية الباند للـ shared queue في main.py"""
        verification_cog = self.bot.get_cog('Verification')
        if verification_cog:
            return await verification_cog.queue_task(self._do_ban, member, reason, delete_message_seconds)
        else:
            # fallback مباشر إذا لم يكن الـ cog موجوداً
            return await self._do_ban(member, reason, delete_message_seconds)

    async def _do_ban(self, member, reason, delete_message_seconds=86400):
        # حماية: منع حظر مالك السيرفر الفعلي نهائياً مهما كان السبب
        if member.id == member.guild.owner_id:
            logger.warning("Blocked ban attempt on server owner: %s (reason: %s)", member.id, reason)
            return False

        try:
            # delete_message_seconds هو البارامتر الحديث (delete_message_days
            # صار deprecated من ديسكورد نفسها لصالحه)
            await member.ban(reason=reason, delete_message_seconds=delete_message_seconds)
            logger.info("Banned %s successfully (reason: %s)", member.id, reason)
            return True
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Ban failed for %s: %s", member.id, e)
            return False

    # =====================================================
    # مساعد: يبني ايمبد "فشل الباند" موحّد
    # =====================================================
    def _build_ban_failed_embed(self, member, title, original_reason, channel=None):
        return self._build_log_embed(
            action_type="ban",
            title=f"⚠️ فشل الباند | {title}",
            member=member,
            reason=f"{original_reason}\n\n**السبب:** فشل تنفيذ الباند (مالك السيرفر أو رتبة العضو أعلى من رتبة البوت)",
            channel=channel,
            extra_fields=[("الإجراء", "لم يتم تنفيذ الباند")]
        )

    # =====================================================
    # on_message
    # =====================================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        # Honeypot - باند فوري لأي شخص يكتب في روم بترقوري شات
        honeypot_channel = self._get_honeypot_channel(message.guild)
        if honeypot_channel and message.channel.id == honeypot_channel.id:
            member = message.author
            try:
                await message.delete()
                banned = await self._queue_ban(member, "🚫 Honeypot triggered - auto ban")

                if banned:
                    embed = self._build_log_embed(
                        action_type="ban",
                        title="باند | Honeypot",
                        member=member,
                        reason=f"كتب في روم الـ Honeypot: `{message.content[:200]}`",
                        channel=message.channel,
                        extra_fields=[("الإجراء", "باند فوري")]
                    )
                else:
                    embed = self._build_ban_failed_embed(
                        member, "Honeypot",
                        f"كتب في روم الـ Honeypot: `{message.content[:200]}`",
                        channel=message.channel
                    )
                await self.send_security_log(message.guild, embed)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("Honeypot ban error: %s", e)
            return

        member = message.author

        # 0. فحص الأوامر - فقط الأونر يستخدم أوامر البوت المسجلة
        if message.content.startswith("!") or message.content.startswith("/"):
            if message.author.id != message.guild.owner_id:
                # نتحقق إذا هو أمر مسجل فعلاً في البوت
                # نستخدم split() ونتأكد من وجود عنصر قبل الوصول لـ [0]، عشان
                # رسالة زي "! " (علامة + مسافات بدون كلمة) ما ترمي IndexError
                # وتوقف بقية فحوصات الرسالة (السبام والروابط) بدون قصد.
                cmd_parts = message.content[1:].split()
                cmd_name = cmd_parts[0].lower() if cmd_parts else ""
                is_registered_cmd = cmd_name in [c.name for c in self.bot.commands]
                if is_registered_cmd:
                    try:
                        await message.delete()
                        await message.channel.send(
                            f"{member.mention} هذا الأمر مخصص للأونر فقط.",
                            delete_after=8
                        )
                        embed = self._build_log_embed(
                            action_type="warn",
                            title="تحذير | استخدام أمر",
                            member=member,
                            reason=f"حاول استخدام أمر: `{message.content[:200]}`",
                            channel=message.channel,
                            extra_fields=[("الإجراء", "حذف الرسالة + تحذير")]
                        )
                        await self.send_security_log(message.guild, embed)
                    except (discord.Forbidden, discord.HTTPException) as e:
                        logger.error("on_message command warn error: %s", e)
                    return

        # 1. فحص الروابط - باند مباشر
        # نطبّع النص (نشيل zero-width/invisible ونحول homoglyphs) ونفحص
        # المحتوى + أي embed مرفق، عشان التحايل بمسافات/رموز خفية ما يفوت الفلتر
        scan_text = _normalize_for_link_scan(_collect_scannable_text(message))
        if LINK_PATTERN.search(scan_text):
            try:
                await message.delete()
                banned = await self._queue_ban(member, "🚫 Posted links - auto ban")

                if banned:
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
                else:
                    embed = self._build_ban_failed_embed(
                        member, "إرسال روابط",
                        message.content[:500],
                        channel=message.channel
                    )
                await self.send_security_log(message.guild, embed)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("on_message link ban error: %s", e)
            return

        # 2. فحص السبام
        now = datetime.now()
        spam_key = self._spam_key(member)
        self.user_messages[spam_key].append(now)
        self.user_messages[spam_key] = [
            t for t in self.user_messages[spam_key]
            if (now - t).total_seconds() < SPAM_TIMEFRAME
        ]

        if len(self.user_messages[spam_key]) >= SPAM_THRESHOLD:
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
                self.user_messages[spam_key].clear()
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("on_message spam timeout error: %s", e)

    # =====================================================
    # on_member_join - منع البوتات
    # =====================================================
    @commands.Cog.listener()
    async def on_member_join(self, member):
        # فحص Join Raid لكل الأعضاء (بشر وبوتات)
        await self._check_join_raid(member.guild)

        if not member.bot:
            return

        # فحص Bot Raid
        await self._check_bot_raid(member.guild, member)

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(member.guild, discord.AuditLogAction.bot_add, member.id)
        if not entry:
            return

        if entry.user.id == member.guild.owner_id:
            print(f"✅ Owner added bot: {member.name}")
            return

        try:
            # ملاحظة: هذا حظر للبوت نفسه (member هنا هو البوت المضاف)، ليس عضواً عادياً
            # فلا يحتاج فحص owner لأن البوتات لا تكون أونر للسيرفر
            await member.ban(reason="🚫 Unauthorized bot - only owner can add bots")

            adder = entry.user
            adder_member = member.guild.get_member(adder.id)
            if adder_member:
                banned = await self._queue_ban(adder_member, "🚫 Added unauthorized bot - only owner can add bots")

                if banned:
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
                else:
                    embed = self._build_ban_failed_embed(
                        adder_member, "إضافة بوت غير مصرح",
                        f"أضاف بوت: {member.name} ({member.id})"
                    )
                await self.send_security_log(member.guild, embed)
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
                banned = await self._queue_ban(member, "🚫 Unauthorized channel creation - auto ban")

                if banned:
                    embed = self._build_log_embed(
                        action_type="ban",
                        title="باند | إنشاء روم",
                        member=member,
                        reason=f"أنشأ روم: **{channel.name}**",
                        extra_fields=[("الإجراء", "حذف الروم + باند نهائي")]
                    )
                else:
                    embed = self._build_ban_failed_embed(
                        member, "إنشاء روم",
                        f"أنشأ روم: **{channel.name}**"
                    )
                await self.send_security_log(channel.guild, embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("on_guild_channel_create ban error: %s", e)

    # =====================================================
    # on_guild_channel_delete
    # =====================================================
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await asyncio.sleep(1)
        entry = await self._get_audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if not entry:
            return

        await self._handle_delete_abuse(
            channel.guild,
            entry.user,
            channel.name,
            "روم",
            self._channel_delete_timestamps,
        )

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
                banned = await self._queue_ban(member, "🚫 Unauthorized role creation - auto ban")

                if banned:
                    embed = self._build_log_embed(
                        action_type="ban",
                        title="باند | إنشاء رول",
                        member=member,
                        reason=f"أنشأ رول: **{role.name}**",
                        extra_fields=[("الإجراء", "حذف الرول + باند نهائي")]
                    )
                else:
                    embed = self._build_ban_failed_embed(
                        member, "إنشاء رول",
                        f"أنشأ رول: **{role.name}**"
                    )
                await self.send_security_log(role.guild, embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("on_guild_role_create ban error: %s", e)

    # =====================================================
    # on_webhooks_update - حماية من إنشاء ويب هوك غير مصرح
    # =====================================================
    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        now = datetime.now(timezone.utc).timestamp()
        last = self._webhook_ban_timestamps.get(channel.id, 0)
        if now - last < 10.0:
            return
        self._webhook_ban_timestamps[channel.id] = now

        await asyncio.sleep(1)

        # نجيب آخر entry إنشاء ويب هوك بدون فلتر ID لأن target هو الويب هوك مو الروم
        entry = None
        try:
            async for e in channel.guild.audit_logs(limit=5, action=discord.AuditLogAction.webhook_create):
                entry = e
                break
        except (discord.Forbidden, discord.HTTPException):
            return

        if not entry:
            return

        actor = entry.user
        if actor.id == channel.guild.owner_id or actor.id == self.bot.user.id:
            return

        # حذف الويب هوك فوراً
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.user and wh.user.id == actor.id:
                    await wh.delete(reason="🚫 Unauthorized webhook creation")
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Failed to delete unauthorized webhook: %s", e)

        member = channel.guild.get_member(actor.id)
        if not member:
            return

        banned = await self._queue_ban(member, "🚫 Unauthorized webhook creation - only owner allowed")
        if banned:
            embed = self._build_log_embed(
                action_type="ban",
                title="باند | إنشاء ويب هوك",
                member=member,
                reason=f"أنشأ ويب هوك في: {channel.mention}",
                extra_fields=[("الإجراء", "حذف الويب هوك + باند نهائي")]
            )
        else:
            embed = self._build_ban_failed_embed(
                member, "إنشاء ويب هوك",
                f"أنشأ ويب هوك في: {channel.mention}"
            )
        await self.send_security_log(channel.guild, embed)
        await self._dm_owner(channel.guild, f"⚠️ **{member.mention} حاول ينشئ ويب هوك!**\nالروم: {channel.mention}\nتم حذف الويب هوك وباند العضو فوراً.")

    # =====================================================
    # on_guild_role_delete
    # =====================================================
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await asyncio.sleep(1)
        entry = await self._get_audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
        if not entry:
            return

        await self._handle_delete_abuse(
            role.guild,
            entry.user,
            role.name,
            "رول",
            self._role_delete_timestamps,
        )

    # =====================================================
    # on_guild_role_update - حماية من تغيير صلاحيات الرولات
    # =====================================================
    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        # نتحقق فقط لو صارت تغيير في الصلاحيات
        if before.permissions == after.permissions:
            return

        # لو أضيفت صلاحية المدير للرول بعد ما كانت غير موجودة
        gained_admin = after.permissions.administrator and not before.permissions.administrator
        if not gained_admin:
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(after.guild, discord.AuditLogAction.role_update, after.id)
        if not entry:
            return

        actor = entry.user
        if self._is_protected_actor(after.guild, actor):
            return

        member = after.guild.get_member(actor.id)
        if not member:
            return

        # نسحب صلاحية المدير من الرول فوراً
        try:
            new_perms = discord.Permissions(after.permissions.value)
            new_perms.administrator = False
            await after.edit(permissions=new_perms, reason="🚫 سحب صلاحية المدير غير المصرح بها")
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Failed to remove admin perm from role %s: %s", after.name, e)

        banned = await self._queue_ban(member, "🚫 أضاف صلاحية مدير لرول - غير مصرح")
        if banned:
            embed = self._build_log_embed(
                action_type="ban",
                title="باند | تغيير صلاحيات رول",
                member=member,
                reason=f"أضاف صلاحية المدير لرول: **{after.name}**",
                extra_fields=[("\u0627لإجراء", "سحب الصلاحية + باند نهائي")]
            )
        else:
            embed = self._build_ban_failed_embed(
                member, "تغيير صلاحيات رول",
                f"أضاف صلاحية المدير لرول: **{after.name}**"
            )
        await self.send_security_log(after.guild, embed)
        await self._dm_owner(after.guild, f"⚠️ **تحذير!**\n{member.mention} حاول يضيف صلاحية المدير لرول **{after.name}**.\nتم سحب الصلاحية وبانده.")

    # =====================================================
    # on_guild_update - حماية من تغيير اسم السيرفر أو أيقونته
    # =====================================================
    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        if before.name == after.name and before.icon == after.icon:
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(after, discord.AuditLogAction.guild_update, after.id)
        if not entry:
            return

        actor = entry.user
        if self._is_protected_actor(after, actor):
            return

        member = after.get_member(actor.id)
        if not member:
            return

        banned = await self._queue_ban(member, "🚫 عدّل بيانات السيرفر بدون إذن")
        changes = []
        if before.name != after.name:
            changes.append(f"الاسم: {before.name} ← {after.name}")
        if before.icon != after.icon:
            changes.append("الأيقونة: تم تغييرها")

        if banned:
            embed = self._build_log_embed(
                action_type="ban",
                title="باند | تغيير بيانات السيرفر",
                member=member,
                reason="\n".join(changes),
                extra_fields=[("\u0627لإجراء", "باند نهائي")]
            )
        else:
            embed = self._build_ban_failed_embed(member, "تغيير بيانات السيرفر", "\n".join(changes))
        await self.send_security_log(after, embed)

async def setup(bot):
    await bot.add_cog(Protection(bot))
