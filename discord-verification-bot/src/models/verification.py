import discord
from discord.ext import commands
from datetime import datetime
import asyncio

NEW_ACCOUNT_DAYS = 30

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify Me", style=discord.ButtonStyle.green, custom_id="verify_button_v2")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog('Verification')
        if not cog:
            await interaction.response.send_message("Error: Verification system is offline.", ephemeral=True)
            return

        member = interaction.user

        if member.bot:
            await interaction.response.send_message("❌ Bots cannot be verified!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        account_age = (datetime.now(member.created_at.tzinfo) - member.created_at).days
        is_new     = account_age < NEW_ACCOUNT_DAYS
        has_avatar = member.avatar is not None

        try:
            verified_role = discord.utils.get(interaction.guild.roles, name="Verified")
            if not verified_role:
                verified_role = await interaction.guild.create_role(name="Verified")

            roles_to_add = [verified_role]
            msg = "✅ You have been verified!"

            if is_new or not has_avatar:
                watched_role = discord.utils.get(interaction.guild.roles, name="Watched")
                if not watched_role:
                    watched_role = await interaction.guild.create_role(
                        name="Watched",
                        color=discord.Color.orange()
                    )
                roles_to_add.append(watched_role)
                msg = "✅ Verified! ⚠️ You are under strict monitoring."

            await cog.queue_task(self.add_roles, member, roles_to_add)
            await interaction.followup.send(msg, ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send("❌ Bot lacks permissions!", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    async def add_roles(self, member, roles):
        try:
            await member.add_roles(*roles)
            print(f"✅ Added roles {[r.name for r in roles]} to {member.name}")
        except discord.Forbidden:
            print(f"⚠️ Missing permissions to add roles to {member.name}")
        except discord.HTTPException as e:
            print(f"⚠️ HTTP error adding roles to {member.name}: {e}")


class Verification(commands.Cog):
    def __init__(self, bot):
        print("\n>>> [DEBUG] Verification Cog v2.1 Initialized! <<<")
        self.bot = bot
        self.task_queue = asyncio.Queue()
        self._worker_task = None

    async def cog_load(self):
        self._worker_task = asyncio.create_task(self.worker())
        print("✅ Verification worker started")

        # FIX: تحقق قبل إضافة الـ View لمنع التكرار عند reload
        already_added = any(
            isinstance(v, VerifyButton)
            for v in self.bot.persistent_views
        )
        if not already_added:
            self.bot.add_view(VerifyButton())
            print("✅ VerifyButton view registered")
        else:
            print("ℹ️ VerifyButton already registered, skipping")

    def cog_unload(self):
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
        print("✅ Verification worker stopped")

    async def worker(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                func, args = await self.task_queue.get()
                try:
                    await func(*args)
                except Exception as e:
                    print(f"⚠️ Error in queue task: {e}")
                await asyncio.sleep(1)
                self.task_queue.task_done()
            except asyncio.CancelledError:
                print("✅ Worker cancelled cleanly")
                break

    async def queue_task(self, func, *args):
        await self.task_queue.put((func, args))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setup_verify(self, ctx):
        await ctx.message.delete()

        embed = discord.Embed(
            title="توثيق السيرفر",
            description="اضغط على زر **توثيق** أدناه للحصول على صلاحية الوصول لبقية السيرفر!\n\n**الحماية النشطة**",
            color=0x00ff00
        )
        embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
        embed.set_footer(text="نظام التوثيق والحماية • MSA")

        await ctx.send(embed=embed, view=VerifyButton())
        print(f"✅ Verification message created in #{ctx.channel.name}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def shutdown(self, ctx):
        await ctx.send("🛑 جاري إيقاف البوت... سيتم قطع الاتصال فوراً.")
        await self.bot.close()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return
        await self.queue_task(self.add_welcome_role, member)

    async def add_welcome_role(self, member):
        try:
            welcome_role = discord.utils.get(member.guild.roles, name="Welcome")
            if not welcome_role:
                welcome_role = await member.guild.create_role(
                    name="Welcome",
                    color=discord.Color.blue(),
                    reason="رول ترحيب تلقائي للأعضاء الجدد"
                )
                print(f"✅ Created Welcome role")
            await member.add_roles(welcome_role)
            print(f"✅ Gave Welcome role to {member.name}")
        except discord.Forbidden:
            print(f"⚠️ Missing permissions to give Welcome role to {member.name}")
        except discord.HTTPException as e:
            print(f"⚠️ HTTP error giving Welcome role: {e}")


async def setup(bot):
    await bot.add_cog(Verification(bot))