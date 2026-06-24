import asyncio
import os
import random
import re
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks
from src.config.config_encrypted import get_hadith_api_key


AZKAR_CHANNEL_NAME = os.getenv("AZKAR_CHANNEL_NAME", "اذكار")
AZKAR_INTERVAL_MINUTES = max(1, int(os.getenv("AZKAR_INTERVAL_MINUTES", "5")))
QURAN_AYAH_COUNT = 6236
QURAN_API_URL = "https://api.alquran.cloud/v1/ayah/{ayah_number}/quran-simple-clean"
HADITH_API_URL = os.getenv("HADITH_API_URL", "https://hadithapi.com/api/hadiths")
HADITH_API_KEY = get_hadith_api_key()
HADITH_BOOKS = ("sahih-bukhari", "sahih-muslim")
ARABIC_DIACRITICS_PATTERN = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")


def _clean_text(value):
    value = re.sub(r"<[^>]+>", "", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _strip_arabic_diacritics(value):
    return ARABIC_DIACRITICS_PATTERN.sub("", value)


def _format_surah_name(value):
    value = _strip_arabic_diacritics(_clean_text(value))
    value = re.sub(r"^سورة\s+", "", value).strip()
    return value


def _display_text(value):
    if isinstance(value, dict):
        value = _first_present(
            value,
            (
                "chapterArabic",
                "bookName",
                "bookSlug",
                "chapterEnglish",
                "englishName",
                "name",
                "title",
            ),
        )
    return _clean_text(value)


def _first_present(data, keys):
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if value:
                return value
        for value in data.values():
            found = _first_present(value, keys)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _first_present(value, keys)
            if found:
                return found
    return None


def extract_quran_text(payload):
    data = payload.get("data", payload)
    text = _clean_text(data.get("text"))
    if not text:
        raise ValueError("Quran API response did not include ayah text")

    surah = data.get("surah") or {}
    surah_name = _format_surah_name(surah.get("name") or surah.get("englishName") or "غير معروف")
    ayah_number = data.get("numberInSurah") or data.get("number")

    return {
        "kind": "آية قرآنية",
        "text": text,
        "source": f"سورة {surah_name} - آية {ayah_number}",
    }


def extract_hadith_text(payload):
    text = _first_present(
        payload,
        (
            "arabic",
            "arabicText",
            "hadithArabic",
            "bodyArabic",
            "body",
            "text",
        ),
    )
    text = _strip_arabic_diacritics(_clean_text(text))
    if not text:
        raise ValueError("Hadith API response did not include hadith text")

    collection = _display_text(
        _first_present(payload, ("collection", "collectionName", "bookSlug", "bookName", "book")) or "Hadith API"
    )
    hadith_number = _display_text(_first_present(payload, ("hadithNumber", "hadithNo", "number")) or "")
    chapter = _display_text(_first_present(payload, ("chapterTitle", "chapter", "bookName")) or "")

    source_parts = [part for part in (collection, chapter, hadith_number and f"رقم {hadith_number}") if part]

    return {
        "kind": "حديث شريف",
        "text": text,
        "source": " - ".join(source_parts),
    }


def build_azkar_embed(item, *, bot_name, bot_avatar_url):
    embed = discord.Embed(
        title=item["kind"],
        color=0x2B2D31,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=bot_name, icon_url=bot_avatar_url)
    embed.add_field(name="النص", value=item["text"][:1024], inline=False)
    embed.add_field(name="المصدر", value=item["source"][:1024], inline=False)
    embed.set_footer(text="نظام الحماية | MSA")
    return embed


class AzkarSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._next_kind = "quran"
        self.azkar_task.start()

    def cog_unload(self):
        self.azkar_task.cancel()

    @tasks.loop(minutes=AZKAR_INTERVAL_MINUTES)
    async def azkar_task(self):
        for guild in self.bot.guilds:
            channel = await self._get_or_create_azkar_channel(guild)
            if not channel:
                continue

            item = await self._get_next_item()
            if not item:
                continue

            avatar_url = self.bot.user.avatar.url if self.bot.user and self.bot.user.avatar else None
            embed = build_azkar_embed(
                item,
                bot_name="نظام الحماية",
                bot_avatar_url=avatar_url,
            )

            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                print(f"⚠️ Missing permission to send azkar in {guild.name}.")
            except discord.HTTPException as e:
                print(f"⚠️ Failed to send azkar in {guild.name}: {e}")

    @azkar_task.before_loop
    async def before_azkar_task(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)

    async def _get_or_create_azkar_channel(self, guild):
        channel_id = os.getenv("AZKAR_CHANNEL_ID")
        if channel_id and channel_id.isdigit():
            channel = guild.get_channel(int(channel_id))
            if channel:
                return channel

        channel = discord.utils.get(guild.text_channels, name=AZKAR_CHANNEL_NAME)
        if channel:
            return channel

        me = guild.me or guild.get_member(self.bot.user.id)
        if not me or not me.guild_permissions.manage_channels:
            print(f"⚠️ Missing Manage Channels permission to create {AZKAR_CHANNEL_NAME} in {guild.name}.")
            return None

        try:
            return await guild.create_text_channel(
                name=AZKAR_CHANNEL_NAME,
                reason="Azkar channel - MSA",
            )
        except discord.Forbidden:
            print(f"⚠️ Forbidden: cannot create {AZKAR_CHANNEL_NAME} in {guild.name}.")
        except discord.HTTPException as e:
            print(f"⚠️ Failed to create {AZKAR_CHANNEL_NAME} in {guild.name}: {e}")
        return None

    async def _get_next_item(self):
        if self._next_kind == "quran":
            self._next_kind = "hadith"
            item = await self._fetch_quran_item()
            if item:
                return item

        self._next_kind = "quran"
        item = await self._fetch_hadith_item()
        if item:
            return item

        return await self._fetch_quran_item()

    async def _fetch_quran_item(self):
        ayah_number = random.randint(1, QURAN_AYAH_COUNT)
        url = QURAN_API_URL.format(ayah_number=ayah_number)
        try:
            payload = await self._fetch_json(url)
            return extract_quran_text(payload)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            print(f"⚠️ Failed to fetch Quran ayah: {e}")
            return None

    async def _fetch_hadith_item(self):
        if not HADITH_API_KEY:
            print("ℹ️ HADITH_API_KEY is not set; skipping hadith fetch.")
            return None

        try:
            params = {
                "apiKey": HADITH_API_KEY,
                "book": random.choice(HADITH_BOOKS),
                "status": "Sahih",
                "paginate": 200,
                "page": random.randint(1, 40),
            }
            payload = await self._fetch_json(HADITH_API_URL, params=params)
            return extract_hadith_text(payload)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            print(f"⚠️ Failed to fetch hadith: {e}")
            return None

    async def _fetch_json(self, url, headers=None, params=None):
        session = getattr(self.bot, "_http_session", None)
        if not session or session.closed:
            raise aiohttp.ClientError("HTTP session is not available")

        timeout = aiohttp.ClientTimeout(total=10)
        async with session.get(url, headers=headers, params=params, timeout=timeout) as response:
            response.raise_for_status()
            return await response.json()


async def setup(bot):
    await bot.add_cog(AzkarSystem(bot))
