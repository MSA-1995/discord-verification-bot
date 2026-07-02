import discord
import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone


def build_log_embed(bot, *, action_type=None, title, color=None, member=None, user=None,
                    reason=None, channel=None, extra_fields=None, fields=None):
    """
    embed موحد للوقات - يدعم صيغة protection.py و log_system.py معاً
    - protection.py: action_type, title, member, reason, channel, extra_fields
    - log_system.py: title, color, member/user, fields (list of tuples: name, value, inline)
    """
    if color is None:
        colors = {
            "ban": 0xff0000,
            "timeout": 0xff6600,
            "kick": 0xffaa00,
            "info": 0x3498db,
        }
        color = colors.get(action_type, 0xff0000)

    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))

    bot_avatar = bot.user.avatar.url if bot.user.avatar else None
    embed.set_author(name="نظام الحماية", icon_url=bot_avatar)

    target = member or user
    if target:
        if hasattr(target, 'avatar') and target.avatar:
            embed.set_thumbnail(url=target.avatar.url)
        elif hasattr(target, 'default_avatar'):
            embed.set_thumbnail(url=target.default_avatar.url)

    # صيغة protection.py
    if reason is not None:
        if member:
            embed.add_field(name="العضو", value=member.mention, inline=True)
            embed.add_field(name="الآيدي", value=f"`{member.id}`", inline=True)
        if channel:
            embed.add_field(
                name="القناة",
                value=channel.mention if hasattr(channel, 'mention') else str(channel),
                inline=True
            )
        embed.add_field(name="السبب", value=reason[:1024], inline=False)
        if extra_fields:
            for name, value in extra_fields:
                embed.add_field(name=name, value=value, inline=True)

    # صيغة log_system.py
    elif fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)

    embed.set_footer(text="نظام الحماية | MSA")
    return embed


async def get_audit_entry(guild, action, target_id: int):
    """جلب audit log entry خلال آخر 5 ثواني"""
    after_time = datetime.now(timezone.utc) - timedelta(seconds=5)
    try:
        async def fetch():
            async for entry in guild.audit_logs(limit=5, action=action, after=after_time):
                if entry.target and entry.target.id == target_id:
                    return entry
            return None
        return await asyncio.wait_for(fetch(), timeout=3.0)
    except (discord.Forbidden, discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError):
        pass
    return None
