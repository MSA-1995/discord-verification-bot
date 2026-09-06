import discord
from discord.ext import commands
import yt_dlp
import asyncio
import logging

logger = logging.getLogger(__name__)

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'cookiefile': '/app/cookies.txt',
    'extractor_args': {'youtube': {'player_client': ['android', 'ios', 'web_creator']}},
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}


class MusicControls(discord.ui.View):
    def __init__(self, cog, guild_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(emoji="⏸", style=discord.ButtonStyle.secondary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.defer()
        if vc.is_paused():
            vc.resume()
            button.emoji = "⏸"
        else:
            vc.pause()
            button.emoji = "▶️"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary)
    async def toggle_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.guild_id)
        state['loop'] = not state.get('loop', False)
        button.style = discord.ButtonStyle.success if state['loop'] else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary)
    async def autoplay(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.guild_id)
        state['autoplay'] = not state.get('autoplay', False)
        button.style = discord.ButtonStyle.success if state['autoplay'] else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏹", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            self.cog.get_state(self.guild_id)['autoplay'] = False
            self.cog.get_state(self.guild_id)['loop'] = False
            await vc.disconnect()
        await interaction.response.defer()


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._states = {}
        self._empty_timers = {}

    def get_state(self, guild_id):
        if guild_id not in self._states:
            self._states[guild_id] = {'loop': False, 'autoplay': False, 'current': None, 'text_channel': None}
        return self._states[guild_id]

    async def search_and_play(self, guild, query, after_autoplay=False):
        state = self.get_state(guild.id)
        vc = guild.voice_client
        if not vc:
            return

        loop = asyncio.get_event_loop()
        try:
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
                if after_autoplay:
                    data = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch5:{query}", download=False))
                    entries = data.get('entries', [])
                    current_url = state.get('current_url')
                    track = next((e for e in entries if e.get('webpage_url') != current_url), entries[1] if len(entries) > 1 else entries[0] if entries else None)
                else:
                    data = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch:{query}", download=False))
                    entries = data.get('entries', [])
                    track = entries[0] if entries else None
        except Exception as e:
            logger.error("yt-dlp error: %s", e)
            return

        if not track:
            return

        url = track.get('url')
        title = track.get('title', 'Unknown')
        webpage_url = track.get('webpage_url', '')
        thumbnail = track.get('thumbnail')
        duration = track.get('duration', 0)

        state['current'] = query
        state['current_url'] = webpage_url

        def after_play(error):
            if error:
                logger.error("Player error: %s", error)
            asyncio.run_coroutine_threadsafe(self._after_track(guild, query), self.bot.loop)

        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        vc.play(source, after=after_play)

        text_channel = state.get('text_channel')
        if text_channel:
            embed = discord.Embed(
                title="🎵 يشتغل الحين",
                description=f"**[{title}]({webpage_url})**",
                color=0x1db954
            )
            mins, secs = divmod(duration, 60)
            embed.add_field(name="المدة", value=f"{int(mins)}:{int(secs):02d}")
            if thumbnail:
                embed.set_thumbnail(url=thumbnail)
            view = MusicControls(self, guild.id)
            await text_channel.send(embed=embed, view=view)

    async def _after_track(self, guild, query):
        state = self.get_state(guild.id)
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            return

        if state.get('loop'):
            await self.search_and_play(guild, query)
        elif state.get('autoplay'):
            await self.search_and_play(guild, query, after_autoplay=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if member.bot:
            return
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if not vc or not vc.channel:
                continue
            humans = [m for m in vc.channel.members if not m.bot]
            guild_id = guild.id
            if len(humans) == 0:
                if guild_id not in self._empty_timers:
                    self._empty_timers[guild_id] = asyncio.create_task(self._leave_after_timeout(guild, guild_id))
            else:
                task = self._empty_timers.pop(guild_id, None)
                if task:
                    task.cancel()

    async def _leave_after_timeout(self, guild, guild_id):
        await asyncio.sleep(60)
        try:
            vc = guild.voice_client
            if vc:
                await vc.disconnect()
        except Exception:
            pass
        self._empty_timers.pop(guild_id, None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.content.startswith("ش "):
            query = message.content[2:].strip()
            if not query:
                return
            if not message.author.voice:
                return await message.channel.send("❌ لازم تكون في روم صوتي!", delete_after=5)

            guild = message.guild
            vc = guild.voice_client

            if not vc:
                vc = await message.author.voice.channel.connect()
            elif vc.channel != message.author.voice.channel:
                await vc.move_to(message.author.voice.channel)

            state = self.get_state(guild.id)
            state['text_channel'] = message.channel

            await message.delete()
            await self.search_and_play(guild, query)


async def setup(bot):
    await bot.add_cog(Music(bot))
