import json
import asyncio
import logging
import random
from pathlib import Path

import discord
from discord.ext import commands

from src.config import channels_config

_logger = logging.getLogger(__name__)

GAME_CHANNEL     = "game"
QUESTION_TIMEOUT = 30
QUESTIONS_FILE   = Path(__file__).parent / "trivia_questions_ar.json"


def _load_questions() -> list[dict]:
    try:
        data = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return data
    except (json.JSONDecodeError, OSError) as e:
        _logger.error("trivia: failed to load question bank: %s", e)
    return []


# Loaded once at import time; this file never changes at runtime.
_ALL_QUESTIONS: list[dict] = _load_questions()


class TriviaSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot   = bot
        self._games: dict[int, asyncio.Task] = {}   # guild_id → running game task
        # per-guild set of question texts already asked THIS process run
        # (in-memory only; resets on redeploy/restart, which is fine)
        self._used_by_guild: dict[int, set[str]] = {}

    # ------------------------------------------------------------------ #
    async def _get_or_create_game_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel = guild.get_channel(channels_config.GAME_CHANNEL_ID)
        if channel:
            return channel
        channel = discord.utils.get(guild.text_channels, name=GAME_CHANNEL)
        if channel:
            return channel
        try:
            channel = await guild.create_text_channel(name=GAME_CHANNEL, reason="Trivia game channel")
            _logger.info("trivia: created #%s in %s", GAME_CHANNEL, guild.name)
            return channel
        except discord.Forbidden:
            _logger.warning("trivia: no permission to create #%s in %s", GAME_CHANNEL, guild.name)
        except discord.HTTPException as e:
            _logger.warning("trivia: failed to create channel: %s", e)
        return None

    # ------------------------------------------------------------------ #
    def _pick_question(self, guild_id: int) -> dict | None:
        if not _ALL_QUESTIONS:
            return None
        used = self._used_by_guild.setdefault(guild_id, set())
        available = [q for q in _ALL_QUESTIONS if q["question"] not in used]
        if not available:
            # exhausted the bank this run — start over
            used.clear()
            available = _ALL_QUESTIONS

        q = random.choice(available)
        used.add(q["question"])

        choices = list(q["wrong"]) + [q["correct"]]
        random.shuffle(choices)
        return {
            "question": q["question"],
            "correct":  q["correct"],
            "choices":  choices,
            "category": q.get("category", "عام"),
            "flag":     q.get("flag"),
        }

    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if not (message.author.guild_permissions.administrator or message.guild.owner_id == message.author.id):
            return

        content = message.content.strip()
        if content == "ابدا":
            await self._handle_start(message)
        elif content == "انتهى" and message.channel.name == GAME_CHANNEL:
            await self._handle_stop(message)

    # ------------------------------------------------------------------ #
    async def _handle_start(self, message: discord.Message):
        guild_id = message.guild.id
        if guild_id in self._games and not self._games[guild_id].done():
            await message.channel.send("⚠️ اللعبة شغالة بالفعل! اكتب **انتهى** لإيقافها.", delete_after=5)
            return
        if not _ALL_QUESTIONS:
            await message.channel.send("❌ بنك الأسئلة فارغ أو تعذّر تحميله. تأكد من وجود ملف trivia_questions_ar.json.")
            return

        placeholder = asyncio.create_task(asyncio.sleep(0))
        self._games[guild_id] = placeholder

        channel = await self._get_or_create_game_channel(message.guild)
        if not channel:
            self._games.pop(guild_id, None)
            await message.channel.send("❌ تعذّر إنشاء روم اللعبة. تأكد من صلاحيات البوت.")
            return
        task = asyncio.create_task(self._run_game(channel))
        self._games[guild_id] = task

    async def _handle_stop(self, message: discord.Message):
        guild_id = message.guild.id
        task = self._games.get(guild_id)
        if not task or task.done():
            await message.channel.send("⚠️ ما في لعبة تشتغل الآن.", delete_after=5)
            return
        task.cancel()

    # ------------------------------------------------------------------ #
    async def _run_game(self, channel: discord.TextChannel):
        scores: dict[int, int] = {}
        loop = asyncio.get_running_loop()
        guild_id = channel.guild.id

        start_embed = discord.Embed(
            description="**بدأت اللعبة!** اكتب **انتهى** في أي وقت لإيقافها.",
            color=0x2ecc71,
        )
        await channel.send(embed=start_embed)

        try:
            while True:
                q = self._pick_question(guild_id)
                if not q:
                    await channel.send("❌ تعذّر جلب سؤال جديد.")
                    break

                labels = ["ا", "ب", "ج", "د"]
                choices_text = "\n".join(
                    f"**{labels[i]}**. {c}" for i, c in enumerate(q["choices"])
                )
                embed = discord.Embed(
                    title=f"❓ {q['question']}",
                    description=choices_text,
                    color=0x5865F2,
                )
                embed.set_footer(text=f"الفئة: {q['category']} • {QUESTION_TIMEOUT} ثانية للإجابة")
                if q.get("flag"):
                    embed.set_thumbnail(url=f"https://flagcdn.com/w320/{q['flag']}.png")
                await channel.send(embed=embed)

                correct_lower = q["correct"].strip().lower()
                correct_label = labels[q["choices"].index(q["correct"])]
                answered: set[int] = set()
                winner_uid: int | None = None

                def normalize(text: str) -> str:
                    t = text.strip().lower()
                    if len(t) > 2 and t[1] in (".", "،", "-", " ") and t[0] in ("ا", "ب", "ج", "د"):
                        t = t[2:].strip()
                    return t

                deadline = loop.time() + QUESTION_TIMEOUT
                while loop.time() < deadline:
                    remaining = deadline - loop.time()
                    try:
                        msg: discord.Message = await self.bot.wait_for(
                            "message",
                            check=lambda m: m.channel.id == channel.id and not m.author.bot,
                            timeout=remaining,
                        )
                    except asyncio.TimeoutError:
                        break

                    if msg.content.strip() == "انتهى":
                        raise asyncio.CancelledError

                    if msg.author.id in answered:
                        continue
                    answered.add(msg.author.id)

                    answer = normalize(msg.content)
                    if answer in (correct_lower, correct_label):
                        winner_uid = msg.author.id
                        scores[winner_uid] = scores.get(winner_uid, 0) + 1
                        await channel.send(
                            f"✅ {msg.author.mention} أجاب صح! "
                            f"**(+1 نقطة — المجموع: {scores[winner_uid]})**"
                        )
                        break

                if winner_uid is None:
                    await channel.send(
                        f"⏰ انتهى الوقت! الإجابة الصحيحة كانت: **{q['correct']}**"
                    )

                await asyncio.sleep(3)

        except asyncio.CancelledError:
            pass
        finally:
            if not self.bot.is_closed():
                try:
                    await self._show_scores(channel, scores)
                except discord.HTTPException as e:
                    _logger.warning("trivia: failed to show scores: %s", e)
            self._games.pop(channel.guild.id, None)

    # ------------------------------------------------------------------ #
    async def _show_scores(self, channel: discord.TextChannel, scores: dict[int, int]):
        if not scores:
            await channel.send("🏁 **انتهت اللعبة!** لم يسجّل أحد نقاط.")
            return

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        medals = ["🥇", "🥈", "🥉"]

        lines = []
        for i, (uid, pts) in enumerate(sorted_scores):
            medal  = medals[i] if i < 3 else f"{i+1}."
            member = channel.guild.get_member(uid)
            name   = member.display_name if member else f"<@{uid}>"
            lines.append(f"{medal} **{name}** — {pts} نقطة")

        embed = discord.Embed(
            title="🏁 انتهت اللعبة — النتائج النهائية",
            description="\n".join(lines),
            color=0xF1C40F,
        )
        await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TriviaSystem(bot))