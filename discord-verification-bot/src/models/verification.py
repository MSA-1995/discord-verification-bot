import discord
from discord.ext import commands
from datetime import datetime
import asyncio
import aiohttp

NEW_ACCOUNT_DAYS = 30

class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify Me", style=discord.ButtonStyle.green, custom_id="verify_button_v2")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. الاستجابة فوراً للدسكورد لمنع خطأ "Interaction Failed"
        deferred = False
        try:
            await interaction.response.defer(ephemeral=True)
            deferred = True
        except discord.InteractionResponded:
            deferred = True
        except Exception:
            print("⚠️ Failed to defer interaction (Network issues)")

        try:
            cog = interaction.client.get_cog('Verification')
            if not cog:
                if deferred: await interaction.followup.send("Error: Verification system is offline.", ephemeral=True)
                return

            member = interaction.user
            if member.bot:
                if deferred: await interaction.followup.send("❌ Bots cannot be verified!", ephemeral=True)
                return

            # 2. استخدام utcnow() لتجنب أخطاء المناطق الزمنية
            now = discord.utils.utcnow()
            account_age = (now - member.created_at).days
            is_new     = account_age < NEW_ACCOUNT_DAYS
            has_avatar = member.avatar is not None

            # التأكد من وجود الرولات أو إنشائها
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

            # إرسال المهمة للـ Queue للتعامل مع الـ Rate Limit
            await cog.queue_task(self.add_roles, member, roles_to_add)
            if deferred: await interaction.followup.send(msg, ephemeral=True)

        except discord.Forbidden:
            if deferred: await interaction.followup.send("❌ Bot lacks permissions!", ephemeral=True)
        except aiohttp.ClientError:
            print("⚠️ Network error during verification followup")
        except Exception as e:
            print(f"⚠️ Verification Error: {e}")
            if deferred:
                try:
                    await interaction.followup.send(f"❌ An internal error occurred.", ephemeral=True)
                except: pass

    async def add_roles(self, member, roles):
        try:
            welcome_role = discord.utils.get(member.guild.roles, name="Welcome")
            if welcome_role and welcome_role in member.roles:
                await member.remove_roles(welcome_role)
                print(f"Removed Welcome role from {member.name}")
            await member.add_roles(*roles)
            print(f"✅ Added roles {[r.name for r in roles]} to {member.name}")
        except discord.Forbidden:
            print(f"⚠️ Missing permissions to add roles to {member.name}")
        except (discord.HTTPException, aiohttp.ClientError) as e:
            print(f"⚠️ Network error adding roles to {member.name}: {e}")
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

        # التحقق مما إذا كان الـ View مسجلاً بالفعل لمنع التكرار
        custom_id = "verify_button_v2"
        is_registered = False
        for view in self.bot.persistent_views:
            if any(getattr(item, 'custom_id', None) == custom_id for item in view.children):
                is_registered = True
                break

        if not is_registered:
            self.bot.add_view(VerifyButton())
            print("✅ VerifyButton view registered")
        else:
            print("ℹ️ VerifyButton already registered, skipping duplication")

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
        # منع تنفيذ الأمر إذا كان هناك رسالة تفعيل قيد الإنشاء في نفس الثانية
        if getattr(self, "_setup_lock", False):
            return
        self._setup_lock = True
        
        try:
            await ctx.message.delete()
        except Exception:
            pass # تجاهل الخطأ إذا لم يمتلك البوت صلاحية حذف الرسائل

        try:
            embed = discord.Embed(
                title="توثيق السيرفر",
                description="اضغط على زر **توثيق** أدناه للحصول على صلاحية الوصول لبقية السيرفر!\n\n**الحماية النشطة**",
                color=0x00ff00
            )
            
            if ctx.guild.icon:
                embed.set_thumbnail(url=ctx.guild.icon.url)
                
            embed.set_footer(text="نظام التوثيق والحماية • MSA")

            await ctx.send(embed=embed, view=VerifyButton())
            print(f"✅ Verification message created in #{ctx.channel.name}")
        except Exception as e:
            print(f"❌ Error in setup_verify: {e}")
            await ctx.send(f"❌ حدث خطأ أثناء إنشاء رسالة التوثيق: {e}", delete_after=10)
        finally:
            await asyncio.sleep(2) # تأخير بسيط لمنع التكرار
            self._setup_lock = False

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
