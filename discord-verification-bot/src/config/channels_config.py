"""
إعدادات الرومات والكاتيقوريات بمكان واحد.
الـ IDs اختيارية للسيرفر الأساسي، والأسماء هي الأساس لدعم أكثر من سيرفر.
"""
import os

import discord


def _get_optional_id(env_name: str, default: str = "") -> int | None:
    value = os.getenv(env_name, default)
    return int(value) if value and value.isdigit() else None


LOG_CHANNEL_NAME = os.getenv("LOG_CHANNEL_NAME", "لوقات")
VERIFY_CATEGORY_NAME = os.getenv("VERIFY_CATEGORY_NAME", "تفعيل")
AZKAR_CHANNEL_NAME = os.getenv("AZKAR_CHANNEL_NAME", "اذكار")
HONEYPOT_CHANNEL_NAME = os.getenv("HONEYPOT_CHANNEL_NAME", "تحذير")
WELCOME_CHANNEL_NAME = os.getenv("WELCOME_CHANNEL_NAME", "ترحيب")
GAME_CHANNEL_NAME = os.getenv("GAME_CHANNEL_NAME", "لعبة-الاسئلة")
SINGLETON_CHANNEL_NAME = os.getenv("SINGLETON_CHANNEL_NAME", "حالة-البوت")

VERIFIED_ROLE_NAME = os.getenv("VERIFIED_ROLE_NAME", "تفعيل")
WELCOME_ROLE_NAME = os.getenv("WELCOME_ROLE_NAME", "ترحيب")
WATCHED_ROLE_NAME = os.getenv("WATCHED_ROLE_NAME", "مراقبة")
BOT_ROLE_NAME = os.getenv("BOT_ROLE_NAME", "ᴹˢᴬ Core")

LEGACY_VERIFIED_ROLE_NAMES = ("Verified",)
LEGACY_WELCOME_ROLE_NAMES = ("Welcome",)
LEGACY_WATCHED_ROLE_NAMES = ("Watched",)

LOG_CHANNEL_ID = _get_optional_id("LOG_CHANNEL_ID")
SINGLETON_CHANNEL_ID = _get_optional_id("SINGLETON_CHANNEL_ID")
AZKAR_CHANNEL_ID = _get_optional_id("AZKAR_CHANNEL_ID")
VERIFY_CATEGORY_ID = _get_optional_id("VERIFY_CATEGORY_ID")
WELCOME_CHANNEL_ID = _get_optional_id("WELCOME_CHANNEL_ID")
HONEYPOT_CHANNEL_ID = _get_optional_id("HONEYPOT_CHANNEL_ID")
GAME_CHANNEL_ID = _get_optional_id("GAME_CHANNEL_ID")


def get_text_channel(guild: discord.Guild, channel_id: int | None, channel_name: str):
    if channel_id:
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
    return discord.utils.get(guild.text_channels, name=channel_name)


def get_category(guild: discord.Guild, category_id: int | None, category_name: str):
    if category_id:
        category = guild.get_channel(category_id)
        if isinstance(category, discord.CategoryChannel):
            return category
    return discord.utils.get(guild.categories, name=category_name)


def get_log_channel(guild: discord.Guild):
    return get_text_channel(guild, LOG_CHANNEL_ID, LOG_CHANNEL_NAME)


def get_singleton_channel(guild: discord.Guild):
    return get_text_channel(guild, SINGLETON_CHANNEL_ID, SINGLETON_CHANNEL_NAME)


def get_azkar_channel(guild: discord.Guild):
    return get_text_channel(guild, AZKAR_CHANNEL_ID, AZKAR_CHANNEL_NAME)


def get_verify_category(guild: discord.Guild):
    return get_category(guild, VERIFY_CATEGORY_ID, VERIFY_CATEGORY_NAME)


def get_welcome_channel(guild: discord.Guild):
    return get_text_channel(guild, WELCOME_CHANNEL_ID, WELCOME_CHANNEL_NAME)


def get_honeypot_channel(guild: discord.Guild):
    return get_text_channel(guild, HONEYPOT_CHANNEL_ID, HONEYPOT_CHANNEL_NAME)


def get_game_channel(guild: discord.Guild):
    return get_text_channel(guild, GAME_CHANNEL_ID, GAME_CHANNEL_NAME)


def get_role(guild: discord.Guild, role_name: str, legacy_names: tuple[str, ...] = ()):
    role = discord.utils.get(guild.roles, name=role_name)
    if role:
        return role

    for legacy_name in legacy_names:
        role = discord.utils.get(guild.roles, name=legacy_name)
        if role:
            return role

    return None
