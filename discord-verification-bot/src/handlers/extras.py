import discord
from discord.ext import commands
from datetime import datetime, timezone
from collections import defaultdict
import asyncio
import logging

logger = logging.getLogger(__name__)

from src.config import channels_config

MASS_BAN_THRESHOLD = 2
MASS_BAN_WINDOW = 20
MASS_KICK_THRESHOLD = 2
MASS_KICK_WINDOW = 20


class Extras(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # تتبع عمليات الباند/الكيك لكل مسؤول
        self.ban_tracker: dict[tuple[int, int], list[float]] = defaultdict(list)
        self.kick_tracker: dict[tuple[int, int], list[float]] = defaultdict(list)

    # =====================================================
    # 1. نظام الترحيب
    # =====================================================
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return

        guild = member.guild

        welcome_channel = channels_config.get_welcome_channel(guild)
        if not welcome_channel:
            try:
                welcome_channel = await guild.create_text_channel(
                    name=channels_config.WELCOME_CHANNEL_NAME,
                    reason="روم الترحيب - ᴹˢᴬ"
                )
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("Failed to create welcome channel: %s", e)
                return

        avatar_url = member.display_avatar.url if member.display_avatar else None
        embed = discord.Embed(
            title="🎉 عضو جديد!",
            description=f"أهلاً وسهلاً {member.mention} في **{guild.name}**!",
            color=0x2ecc71,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=avatar_url)
        embed.add_field(name="الاسم", value=str(member), inline=True)
        embed.add_field(name="الآيدي", value=f"`{member.id}`", inline=True)
        embed.add_field(name="عدد الأعضاء", value=str(guild.member_count), inline=True)
        embed.set_image(url=avatar_url)
        embed.set_footer(text="نظام الحماية | ᴹˢᴬ")

        try:
            await welcome_channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Failed to send welcome message: %s", e)

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

        await self._record_mass_action(guild, entry.user, "باند", self.ban_tracker)

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

        await self._record_mass_action(member.guild, entry.user, "كيك", self.kick_tracker)

    async def _record_mass_action(self, guild, moderator, action_type, tracker):
        threshold = MASS_BAN_THRESHOLD if action_type == "باند" else MASS_KICK_THRESHOLD
        window = MASS_BAN_WINDOW if action_type == "باند" else MASS_KICK_WINDOW
        key = (guild.id, moderator.id)
        now = datetime.now(timezone.utc).timestamp()

        tracker[key] = [
            t for t in tracker[key]
            if now - t < window
        ]
        tracker[key].append(now)

        if len(tracker[key]) < threshold:
            return

        count = len(tracker[key])
        tracker[key].clear()
        await self._send_mass_alert(guild, moderator, action_type, count, threshold, window)

        # نفس إجراء الباند التلقائي يطبّق على Mass Ban وMass Kick معاً
        # (الاستثناء الوحيد هو البوت نفسه والأونر)
        if moderator.id == self.bot.user.id or moderator.id == guild.owner_id:
            return

        member = guild.get_member(moderator.id)
        if not member:
            return

        action_label = "bans" if action_type == "باند" else "kicks"
        try:
            await member.ban(
                reason=f"🚫 Mass {action_type}: {count} {action_label} within {window} seconds",
                delete_message_seconds=86400,
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Failed to ban mass-%s moderator %s: %s", action_type, moderator.id, e)

    # =====================================================
    # دالة إرسال تنبيه Mass Action
    # =====================================================
    async def _send_mass_alert(self, guild, moderator, action_type, count, threshold, window):
        embed = discord.Embed(
            title=f"🚨 تحذير | Mass {action_type}",
            description=f"**{moderator}** قام بعمليات {action_type} متعددة في وقت قصير!",
            color=0xff0000,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="المسؤول", value=f"{moderator.mention}", inline=True)
        embed.add_field(name="الآيدي", value=f"`{moderator.id}`", inline=True)
        embed.add_field(name="النوع", value=f"Mass {action_type}", inline=True)
        embed.add_field(name="العدد", value=f"{threshold}+ في {window} ثانية", inline=True)
        embed.set_footer(text="نظام الحماية | ᴹˢᴬ")

        # إرسال في اللوقات
        log_channel = channels_config.get_log_channel(guild)
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
                        f"**{threshold}+ عمليات في {window} ثانية**"
                    ),
                    color=0xff0000,
                    timestamp=datetime.now(timezone.utc)
                )
                dm_embed.set_footer(text="نظام الحماية | ᴹˢᴬ")
                await owner.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("Failed to send DM to owner: %s", e)


async def setup(bot):
    await bot.add_cog(Extras(bot))
