import discord
from discord.ext import commands
from datetime import datetime
import asyncio

NEW_ACCOUNT_DAYS = 30  # الحسابات الأحدث من 30 يوم

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify Me", style=discord.ButtonStyle.green, custom_id="verify_button_v2")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        # نحصل على الـ cog من البوت في كل مرة لضمان عمل الأزرار الدائمة
        cog = interaction.client.get_cog('Verification')
        if not cog:
            # رسالة خطأ إذا لم يتم العثور على الـ cog (حالة نادرة)
            await interaction.response.send_message("Error: Verification system is offline.", ephemeral=True)
            return

        member = interaction.user

        if member.bot:
            await interaction.response.send_message("❌ Bots cannot be verified!", ephemeral=True)
            return

        account_age = (datetime.now(member.created_at.tzinfo) - member.created_at).days
        is_new = account_age < NEW_ACCOUNT_DAYS
        has_avatar = member.avatar is not None

        # تحديد الرولات
        verified_role = discord.utils.get(interaction.guild.roles, name="Verified")
        if not verified_role:
            verified_role = await interaction.guild.create_role(name="Verified")

        # وضع كل عملية إعطاء رول في queue
        await cog.queue_task(self.add_roles, member, [verified_role])

        msg = "✅ You have been verified!"
        if is_new or not has_avatar:
            watched_role = discord.utils.get(interaction.guild.roles, name="Watched")
            if not watched_role:
                watched_role = await interaction.guild.create_role(
                    name="Watched",
                    color=discord.Color.orange()
                )
            await cog.queue_task(self.add_roles, member, [watched_role])
            msg = "✅ Verified! ⚠️ You are under strict monitoring."

        # الرد على المستخدم
        await interaction.response.send_message(msg, ephemeral=True)

    async def add_roles(self, member, roles):
        """إضافة الرولات مع حماية من أي خطأ"""
        try:
            await member.add_roles(*roles)
            print(f"✅ Added roles {[r.name for r in roles]} to {member.name}")
        except Exception as e:
            print(f"⚠️ Error adding roles to {member.name}: {e}")

class Verification(commands.Cog):
    def __init__(self, bot):
        print("\n>>> [DEBUG] Verification Cog v2.0 Initialized! If you see this, the code is updated. <<<")
        self.bot = bot
        self.task_queue = asyncio.Queue()
        self.bot.loop.create_task(self.worker())

    async def worker(self):
        """معالجة المهام في الـ queue مع فاصل زمني لتجنب 429"""
        while True:
            func, args = await self.task_queue.get()
            try:
                await func(*args)
            except Exception as e:
                print(f"⚠️ Error in queue task: {e}")
            await asyncio.sleep(1)  # فاصل زمني 1 ثانية بين كل مهمة
            self.task_queue.task_done()

    async def queue_task(self, func, *args):
        """إضافة مهمة للـ queue"""
        await self.task_queue.put((func, args))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setup_verify(self, ctx):
        """أمر لإنشاء رسالة التوثيق مع زر"""
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
        """إيقاف تشغيل البوت عن بعد (للحالات الطارئة)"""
        await ctx.send("🛑 جاري إيقاف البوت... سيتم قطع الاتصال فوراً.")
        await self.bot.close()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """إعطاء رول Welcome تلقائياً باستخدام queue"""
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
        except Exception as e:
            print(f"⚠️ Error giving Welcome role: {e}")

async def setup(bot):
    await bot.add_cog(Verification(bot))
