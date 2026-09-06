import discord
from discord.ext import commands
import wavelink
import logging

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

    @discord.ui.button(emoji="⏭", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.skip(force=True)
        await interaction.response.defer()

    @discord.ui.button(emoji="⏹", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.queue.clear()
        await self.player.stop()
        await self.player.disconnect()
        await interaction.response.defer()


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        logger.info("Wavelink node connected: %s", payload.node.identifier)

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

    @commands.command(name="ش")
    async def play(self, ctx: commands.Context, *, query: str):
        if not ctx.author.voice:
            return await ctx.send("❌ لازم تكون في روم صوتي!", delete_after=5)

        if not ctx.voice_client:
            player: wavelink.Player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
        else:
            player: wavelink.Player = ctx.voice_client

        player.text_channel = ctx.channel
        player.autoplay = wavelink.AutoPlayMode.partial

        tracks = await wavelink.Playable.search(query, source=wavelink.TrackSource.YouTube)
        if not tracks:
            return await ctx.send("❌ ما لقيت نتائج!", delete_after=5)

        track = tracks[0]
        await player.queue.put_wait(track)

        if not player.playing:
            await player.play(player.queue.get())
        else:
            await ctx.send(f"✅ أضفت للقائمة: **{track.title}**", delete_after=5)

        await ctx.message.delete()


async def setup(bot):
    lavalink_host = __import__("os").getenv("LAVALINK_HOST", "localhost")
    lavalink_port = int(__import__("os").getenv("LAVALINK_PORT", "2333"))
    lavalink_pass = __import__("os").getenv("LAVALINK_PASSWORD", "youshallnotpass")

    scheme = "https" if str(lavalink_port) == "443" else "http"
    node = wavelink.Node(
        uri=f"{scheme}://{lavalink_host}:{lavalink_port}",
        password=lavalink_pass
    )
    await wavelink.Pool.connect(nodes=[node], client=bot)
    await bot.add_cog(Music(bot))
