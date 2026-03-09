import discord
from discord.ext import commands
import os

# قراءة الـ Token من Environment Variable
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("❌ Error: DISCORD_TOKEN not found!")
    print("Please set DISCORD_TOKEN in Railway/Render settings.")
    exit(1)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="✅ Verify Me", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name="Verified")
        
        # لو الرول مو موجود، يسويه
        if not role:
            role = await interaction.guild.create_role(name="Verified")
        
        # يعطي العضو الرول
        await interaction.user.add_roles(role)
        await interaction.response.send_message("✅ You have been verified!", ephemeral=True)

@bot.event
async def on_ready():
    bot.add_view(VerifyButton())
    print(f"✅ {bot.user} is online and ready!")
    print(f"📊 Connected to {len(bot.guilds)} server(s)")

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_verify(ctx):
    """أمر لإنشاء رسالة التوثيق مع زر"""
    await ctx.message.delete()
    
    embed = discord.Embed(
        title="🔐 Server Verification",
        description="Click the **✅ Verify Me** button below to gain access to the rest of the server!",
        color=0x00ff00
    )
    embed.set_footer(text="MSA Verification System")
    
    await ctx.send(embed=embed, view=VerifyButton())
    print(f"✅ Verification message created in #{ctx.channel.name}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need Administrator permissions to use this command!", delete_after=5)

# تشغيل البوت
print("🚀 Starting verification bot...")
bot.run(TOKEN)
