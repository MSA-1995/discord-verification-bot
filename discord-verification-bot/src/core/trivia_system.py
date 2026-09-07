import json
import asyncio
import html
import logging
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands

_logger = logging.getLogger(__name__)

TRIVIA_API   = "https://opentdb.com/api.php?amount=1&type=multiple"
TRANSLATE_API = "https://translate.googleapis.com/translate_a/single"
GAME_CHANNEL  = "game"
GAME_CHANNEL_ID = 1546548300608438354
QUESTION_TIMEOUT = 30
COOLDOWN_DAYS    = 5
USED_FILE        = Path("trivia_used.json")


def _load_used() -> dict:
    if USED_FILE.exists():
        try:
            return json.loads(USED_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("trivia: failed to load used questions: %s", e)
    return {}


def _save_used(data: dict):
    try:
        USED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        _logger.warning("trivia: failed to save used questions: %s", e)


def _is_on_cooldown(used: dict, question: str) -> bool:
    ts = used.get(question)
    if not ts:
        return False
    last = datetime.fromisoformat(ts)
    return datetime.now(timezone.utc) - last < timedelta(days=COOLDOWN_DAYS)


def _mark_used(used: dict, question: str):
    used[question] = datetime.now(timezone.utc).isoformat()


async def _translate(session: aiohttp.ClientSession, text: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    try:
        async with session.get(
            TRANSLATE_API,
            params={"client": "gtx", "sl": "en", "tl": "ar", "dt": "t", "q": text},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=6),
        ) as r:
            body = await r.text()
            if not body.strip():
                _logger.warning("trivia: translation empty response, status=%s", r.status)
                return text
            data = json.loads(body)
            translated = "".join(part[0] for part in data[0] if part[0])
            if translated and translated.strip():
                return translated.strip()
    except Exception as e:
        _logger.warning("trivia: translation failed: %s", e)
    return text


async def _fetch_question(session: aiohttp.ClientSession, used: dict) -> dict | None:
    """Fetch one question not on cooldown. Returns dict with ar_question, ar_correct, ar_choices."""
    for _ in range(10):
        try:
            async with session.get(
                TRIVIA_API,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                data = await r.json()

            if data.get("response_code") != 0:
                await asyncio.sleep(2)
                continue

            item = data["results"][0]
            raw_q = html.unescape(item["question"])

            if _is_on_cooldown(used, raw_q):
                await asyncio.sleep(1)
                continue

            raw_correct   = html.unescape(item["correct_answer"])
            raw_incorrect = [html.unescape(x) for x in item["incorrect_answers"]]

            # Translate everything in parallel
            texts = [raw_q, raw_correct] + raw_incorrect
            translated = await asyncio.gather(*[_translate(session, t) for t in texts])

            ar_q       = translated[0]
            ar_correct = translated[1]
            ar_wrong   = list(translated[2:])

            choices = ar_wrong + [ar_correct]
            random.shuffle(choices)

            return {
                "raw_q":      raw_q,
                "ar_question": ar_q,
                "ar_correct":  ar_correct,
                "ar_choices":  choices,
                "category":    html.unescape(item.get("category", "")),
            }

        except Exception as e:
            _logger.warning("trivia: fetch error: %s", e)
            await asyncio.sleep(2)

    return None


class TriviaSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot   = bot
        self._games: dict[int, asyncio.Task] = {}   # guild_id → running game task

    # ------------------------------------------------------------------ #
    async def _get_or_create_game_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel = guild.get_channel(GAME_CHANNEL_ID)
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
        used = _load_used()
        loop = asyncio.get_running_loop()
        own_session = self.bot._http_session is None or self.bot._http_session.closed
        session: aiohttp.ClientSession = (
            aiohttp.ClientSession() if own_session else self.bot._http_session
        )

        start_embed = discord.Embed(
            description="**بدأت اللعبة!** اكتب **انتهى** في أي وقت لإيقافها.",
            color=0x2ecc71,
        )
        await channel.send(embed=start_embed)

        try:
            while True:
                q = await _fetch_question(session, used)
                if not q:
                    await channel.send("❌ تعذّر جلب سؤال جديد. حاول لاحقاً.")
                    break

                _mark_used(used, q["raw_q"])
                _save_used(used)

                # Build question embed
                labels   = ["ا", "ب", "ج", "د"]
                choices_text = "\n".join(
                    f"**{labels[i]}**. {c}" for i, c in enumerate(q["ar_choices"])
                )
                embed = discord.Embed(
                    title=f"❓ {q['ar_question']}",
                    description=choices_text,
                    color=0x5865F2,
                )
                embed.set_footer(text=f"الفئة: {q['category']} • {QUESTION_TIMEOUT} ثانية للإجابة")
                await channel.send(embed=embed)

                # Wait for correct answer
                correct_lower = q["ar_correct"].strip().lower()
                correct_label = labels[q["ar_choices"].index(q["ar_correct"])]
                answered: set[int] = set()
                winner_uid: int | None = None

                def normalize(text: str) -> str:
                    t = text.strip().lower()
                    # شيل "ا. " أو "ب. " إلخ من أول النص
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
                        f"⏰ انتهى الوقت! الإجابة الصحيحة كانت: **{q['ar_correct']}**"
                    )

                await asyncio.sleep(3)

        except asyncio.CancelledError:
            pass
        finally:
            if own_session and not session.closed:
                await session.close()
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
