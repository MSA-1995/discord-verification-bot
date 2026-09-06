import discord
from discord.ext import commands
import wavelink
import logging
import asyncio

logger = logging.getLogger(__name__)


class MusicControls(discord.ui.View):
    def __init__(self, player: wavelink.Player):
        super().__init__(timeout=None)
        self.player = player

    @discord.ui.button(emoji="⏸", style=discord.ButtonStyle.secondary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.player.paused:
            await self.player.pause(False)
            button.emoji = "⏸"
        else:
            await self.player.pause(True)
            button.emoji = "▶️"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary)
    async def toggle_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.player.queue.mode == wavelink.QueueMode.loop:
            self.player.queue.mode = wavelink.QueueMode.normal
            button.style = discord.ButtonStyle.secondary
        else:
            self.player.queue.mode = wavelink.QueueMode.loop
            button.style = discord.ButtonStyle.success
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary)
    async def autoplay(self, interaction: discord.Interaction, button: discord.ui.Button):
        if getattr(self.player, "autoplay_enabled", False):
            self.player.autoplay_enabled = False
            button.style = discord.ButtonStyle.secondary
        else:
            self.player.autoplay_enabled = True
            button.style = discord.ButtonStyle.success
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏹", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.queue.clear()
        await self.player.stop()
        await self.player.disconnect()
        await interaction.response.defer()


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._empty_timers: dict[int, asyncio.Task] = {}

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        logger.info("Wavelink node connected: %s", payload.node.identifier)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player: wavelink.Player = payload.player
        if not player or not hasattr(player, "autoplay_enabled"):
            return
        if not player.autoplay_enabled:
            return
        if player.playing or not player.queue.is_empty:
            return

        try:
            last_track = payload.track
            query = last_track.title.split("-")[0].strip()
            tracks = await wavelink.Playable.search(query, source=wavelink.TrackSource.SoundCloud)
            if tracks and len(tracks) > 1:
                next_track = next((t for t in tracks[1:] if t.uri != last_track.uri), tracks[1])
                await player.play(next_track)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player: wavelink.Player = payload.player
        if not hasattr(player, "text_channel") or not player.text_channel:
            return

        track = payload.track
        embed = discord.Embed(
            title="🎵 يشتغل الحين",
            description=f"**[{track.title}]({track.uri})**",
            color=0x1db954
        )
        embed.add_field(name="المدة", value=f"{int(track.length // 60000)}:{int((track.length % 60000) // 1000):02d}")
        embed.set_thumbnail(url=track.artwork)

        view = MusicControls(player)
        await player.text_channel.send(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        for guild in self.bot.guilds:
            player: wavelink.Player = guild.voice_client
            if not player or not player.channel:
                continue

            humans = [m for m in player.channel.members if not m.bot]
            guild_id = guild.id

            if len(humans) == 0:
                if guild_id not in self._empty_timers:
                    self._empty_timers[guild_id] = asyncio.create_task(self._leave_after_timeout(player, guild_id))
            else:
                task = self._empty_timers.pop(guild_id, None)
                if task:
                    task.cancel()

    async def _leave_after_timeout(self, player: wavelink.Player, guild_id: int):
        await asyncio.sleep(60)
        try:
            player.queue.clear()
            await player.stop()
            await player.disconnect()
        except Exception:
            pass
        self._empty_timers.pop(guild_id, None)

    async def play(self, ctx: discord.Message, query: str):
        if not ctx.author.voice:
            return await ctx.channel.send("❌ لازم تكون في روم صوتي!", delete_after=5)

        guild = ctx.guild
        player: wavelink.Player = guild.voice_client

        if not player:
            player = await ctx.author.voice.channel.connect(cls=wavelink.Player)

        player.text_channel = ctx.channel

        tracks = await wavelink.Playable.search(query, source=wavelink.TrackSource.SoundCloud)
        if not tracks:
            return await ctx.channel.send("❌ ما لقيت نتائج!", delete_after=5)

        track = tracks[0]
        await player.queue.put_wait(track)

        if not player.playing:
            await player.play(player.queue.get())
        else:
            await ctx.channel.send(f"✅ أضفت للقائمة: **{track.title}**", delete_after=5)

        await ctx.delete()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.content.startswith("ش "):
            query = message.content[2:].strip()
            if query:
                await self.play(message, query)


async def setup(bot):
    import os
    lavalink_host = os.getenv("LAVALINK_HOST", "localhost")
    lavalink_port = os.getenv("LAVALINK_PORT", "2333")
    lavalink_pass = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")

    uri = f"https://{lavalink_host}" if lavalink_port == "443" else f"http://{lavalink_host}:{lavalink_port}"

    node = wavelink.Node(uri=uri, password=lavalink_pass)
    await wavelink.Pool.connect(nodes=[node], client=bot)
    await bot.add_cog(Music(bot))
