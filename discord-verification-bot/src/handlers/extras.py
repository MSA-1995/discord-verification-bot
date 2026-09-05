import discord
from discord.ext import commands
from datetime import datetime, timezone
from collections import defaultdict
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

WELCOME_CHANNEL_NAME = "👋・ترحيب"
MASS_ACTION_THRESHOLD = 3
MASS_ACTION_WINDOW = 60


class Extras(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # تتبع عمليات الباند/الكيك لكل مسؤول
        self.ban_tracker: dict[int, list[float]] = defaultdict(list)
        self.kick_tracker: dict[int, list[float]] = defaultdict(list)

    # =====================================================
    # دالة مساعدة لإيجاد روم اللوقات
    # =====================================================
    async def _get_log_channel(self, guild):
        log_channel_id = os.getenv("LOG_CHANNEL_ID")
        if log_channel_id and log_channel_id.isdigit():
            channel = guild.get_channel(int(log_channel_id))
            if channel:
                return channel
        return discord.utils.get(guild.text_channels, name="📋・logs")

    # =====================================================
    # 1. نظام الترحيب
    # =====================================================
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return

        guild = member.guild

        # إيجاد أو إنشاء روم الترحيب
        welcome_channel = discord.utils.get(guild.text_channels, name=WELCOME_CHANNEL_NAME)
        if not welcome_channel:
            try:
                welcome_channel = await guild.create_text_channel(
                    name=WELCOME_CHANNEL_NAME,
                    reason="روم الترحيب - MSA"
                )
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("Failed to create welcome channel: %s", e)
                return

        # embed الترحيب
        embed = discord.Embed(
            title="🎉 عضو جديد!",
            description=f"أهلاً وسهلاً {member.mention} في **{guild.name}**!",
            color=0x2ecc71,
            timestamp=datetime.now(timezone.utc)
        )

        avatar_url = member.display_avatar.url if member.display_avatar else None
        embed.set_thumbnail(url=avatar_url)
        embed.add_field(name="الاسم", value=str(member), inline=True)
        embed.add_field(name="الآيدي", value=f"`{member.id}`", inline=True)
        embed.add_field(name="عدد الأعضاء", value=str(guild.member_count), inline=True)
        embed.set_footer(text="نظام الحماية | MSA")

        try:
            await welcome_channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Failed to send welcome message: %s", e)

        # =====================================================
        # 2. معلومات العضو في اللوقات
        # =====================================================
        log_channel = await self._get_log_channel(guild)
        if not log_channel:
            return

        now = discord.utils.utcnow()
        account_age = (now - member.created_at).days
        joined_at = member.joined_at.strftime("%Y-%m-%d %H:%M") if member.joined_at else "غير معروف"

        # تحديد إذا الحساب جديد
        account_status = "⚠️ حساب جديد" if account_age < 30 else "✅ حساب قديم"
        has_avatar = "✅ يوجد" if member.avatar else "❌ لا يوجد"

        info_embed = discord.Embed(
            title="📋 معلومات العضو الجديد",
            color=0x3498db,
            timestamp=datetime.now(timezone.utc)
        )
        info_embed.set_thumbnail(url=avatar_url)
        info_embed.add_field(name="العضو", value=f"{member.mention}", inline=True)
        info_embed.add_field(name="الآيدي", value=f"`{member.id}`", inline=True)
        info_embed.add_field(name="صورة الملف", value=has_avatar, inline=True)
        info_embed.add_field(name="تاريخ إنشاء الحساب", value=member.created_at.strftime("%Y-%m-%d %H:%M"), inline=True)
        info_embed.add_field(name="عمر الحساب", value=f"{account_age} يوم", inline=True)
        info_embed.add_field(name="حالة الحساب", value=account_status, inline=True)
        info_embed.add_field(name="تاريخ الانضمام", value=joined_at, inline=True)
        info_embed.add_field(name="عدد الأعضاء", value=str(guild.member_count), inline=True)
        info_embed.set_footer(text="نظام الحماية | MSA")

        try:
            await log_channel.send(embed=info_embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Failed to send member info to log: %s", e)

    # =====================================================
    # 3. تنبيه Mass Ban
    # =====================================================
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await asyncio.sleep(1)

        try:
            entry = None
            async for e in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                if e.target.id == user.id:
                    entry = e
                    break
        except (discord.Forbidden, discord.HTTPException):
            return

        if not entry or entry.user.id == self.bot.user.id:
            return

        moderator_id = entry.user.id
        now = datetime.now(timezone.utc).timestamp()

        # تنظيف القديم وإضافة الجديد
        self.ban_tracker[moderator_id] = [
            t for t in self.ban_tracker[moderator_id]
            if now - t < MASS_ACTION_WINDOW
        ]
        self.ban_tracker[moderator_id].append(now)

        if len(self.ban_tracker[moderator_id]) >= MASS_ACTION_THRESHOLD:
            self.ban_tracker[moderator_id].clear()
            await self._send_mass_alert(guild, entry.user, "باند", len(self.ban_tracker[moderator_id]))

    # =====================================================
    # 4. تنبيه Mass Kick
    # =====================================================
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await asyncio.sleep(1)

        try:
            entry = None
            async for e in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
                if e.target.id == member.id:
                    entry = e
                    break
        except (discord.Forbidden, discord.HTTPException):
            return

        if not entry or entry.user.id == self.bot.user.id:
            return

        moderator_id = entry.user.id
        now = datetime.now(timezone.utc).timestamp()

        self.kick_tracker[moderator_id] = [
            t for t in self.kick_tracker[moderator_id]
            if now - t < MASS_ACTION_WINDOW
        ]
        self.kick_tracker[moderator_id].append(now)

        if len(self.kick_tracker[moderator_id]) >= MASS_ACTION_THRESHOLD:
            self.kick_tracker[moderator_id].clear()
            await self._send_mass_alert(member.guild, entry.user, "كيك", len(self.kick_tracker[moderator_id]))

    # =====================================================
    # دالة إرسال تنبيه Mass Action
    # =====================================================
    async def _send_mass_alert(self, guild, moderator, action_type, count):
        embed = discord.Embed(
            title=f"🚨 تحذير | Mass {action_type}",
            description=f"**{moderator}** قام بعمليات {action_type} متعددة في وقت قصير!",
            color=0xff0000,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="المسؤول", value=f"{moderator.mention}", inline=True)
        embed.add_field(name="الآيدي", value=f"`{moderator.id}`", inline=True)
        embed.add_field(name="النوع", value=f"Mass {action_type}", inline=True)
        embed.add_field(name="العدد", value=f"{MASS_ACTION_THRESHOLD}+ في {MASS_ACTION_WINDOW} ثانية", inline=True)
        embed.set_footer(text="نظام الحماية | MSA")

        # إرسال في اللوقات
        log_channel = await self._get_log_channel(guild)
        if log_channel:
            try:
                await log_channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("Failed to send mass alert to log: %s", e)

        # إرسال DM للأونر
        owner = guild.owner
        if owner:
            try:
                dm_embed = discord.Embed(
                    title=f"🚨 تحذير عاجل | Mass {action_type}",
                    description=(
                        f"**سيرفر:** {guild.name}\n"
                        f"**المسؤول:** {moderator} (`{moderator.id}`)\n"
                        f"قام بعمليات {action_type} متعددة في وقت قصير!\n"
                        f"**{MASS_ACTION_THRESHOLD}+ عمليات في {MASS_ACTION_WINDOW} ثانية**"
                    ),
                    color=0xff0000,
                    timestamp=datetime.now(timezone.utc)
                )
                dm_embed.set_footer(text="نظام الحماية | MSA")
                await owner.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("Failed to send DM to owner: %s", e)


async def setup(bot):
    await bot.add_cog(Extras(bot))
