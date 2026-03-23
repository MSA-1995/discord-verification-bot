import discord
from discord.ext import commands
from datetime import datetime

NEW_ACCOUNT_DAYS = 30  # الحسابات الأحدث من 30 يوم

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Verify Me", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        
        # فحص إذا كان بوت
        if member.bot:
            await interaction.response.send_message("❌ Bots cannot be verified!", ephemeral=True)
            return
        
        # فحص عمر الحساب
        account_age = (datetime.now(member.created_at.tzinfo) - member.created_at).days
        is_new = account_age < NEW_ACCOUNT_DAYS
        has_avatar = member.avatar is not None
        
        # إعطاء رول Verified
        verified_role = discord.utils.get(interaction.guild.roles, name="Verified")
        if not verified_role:
            verified_role = await interaction.guild.create_role(name="Verified")
        
        await member.add_roles(verified_role)
        
        # إضافة رول مراقبة للحسابات الجديدة/بدون صورة
        if is_new or not has_avatar:
            watched_role = discord.utils.get(interaction.guild.roles, name="Watched")
            if not watched_role:
                watched_role = await interaction.guild.create_role(
                    name="Watched",
                    color=discord.Color.orange()
                )
            await member.add_roles(watched_role)
            
            msg = "✅ Verified! ⚠️ You are under strict monitoring."
        else:
            msg = "✅ You have been verified!"
        
        await interaction.response.send_message(msg, ephemeral=True)

class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
        """إعطاء رول Welcome تلقائياً"""
        if member.bot:
            return
            
        try:
            welcome_role = discord.utils.get(member.guild.roles, name="Welcome")
            if not welcome_role:
                # إنشاء الرول إذا لم يكن موجود
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