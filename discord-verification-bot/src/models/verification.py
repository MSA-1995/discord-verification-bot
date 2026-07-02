import discord
from discord.ext import commands
from datetime import datetime
import asyncio
import aiohttp
import random
import logging

logger = logging.getLogger(__name__)

NEW_ACCOUNT_DAYS = 30
CAPTCHA_TIMEOUT = 60   # ثواني
CAPTCHA_MAX_TRIES = 3  # محاولات قبل الباند

def guild_owner_only():
    async def predicate(ctx):
        if ctx.guild and ctx.author.id == ctx.guild.owner_id:
            return True
        await ctx.send("❌ هذا الأمر مخصص لمالك السيرفر فقط.", delete_after=7)
        return False
    return commands.check(predicate)

def _generate_captcha():
    """توليد سؤال حسابي بسيط"""
    ops = [
        ("+", lambda a, b: a + b),
        ("-", lambda a, b: a - b),
        ("×", lambda a, b: a * b),
    ]
    symbol, func = random.choice(ops)
    if symbol == "×":
        a, b = random.randint(2, 9), random.randint(2, 9)
    elif symbol == "-":
        a, b = random.randint(5, 20), random.randint(1, 5)
    else:
        a, b = random.randint(1, 15), random.randint(1, 15)
    return f"{a} {symbol} {b}", func(a, b)


class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="توثيق الحساب", style=discord.ButtonStyle.green, custom_id="verify_button_v2")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            member = interaction.user
            if member.bot:
                await interaction.response.send_message("❌ لا يمكن توثيق البوتات.", ephemeral=True)
                return

            verified_role = discord.utils.get(interaction.guild.roles, name="Verified")
            if verified_role and verified_role in member.roles:
                await interaction.response.send_message("✅ أنت متفعل بالفعل!", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            cog = interaction.client.get_cog('Verification')
            if not cog:
                await interaction.followup.send("❌ نظام التوثيق غير متاح حالياً.", ephemeral=True)
                return

            # منع فتح أكثر من channel واحد لنفس العضو
            if member.id in cog.active_captchas:
                await interaction.followup.send("⚠️ لديك جلسة توثيق مفتوحة بالفعل.", ephemeral=True)
                return

            await interaction.followup.send("⏳ جاري إنشاء غرفة التوثيق...", ephemeral=True)
            await cog.start_captcha(member, interaction.guild)

        except discord.InteractionResponded:
            pass
        except discord.Forbidden:
            try:
                await interaction.followup.send("❌ لا أملك الصلاحيات المطلوبة.", ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            logger.error("VerifyButton error: %s", e)
            try:
                await interaction.followup.send("❌ حدث خطأ داخلي.", ephemeral=True)
            except Exception:
                pass

    async def add_roles(self, member, roles):
        try:
            welcome_role = discord.utils.get(member.guild.roles, name="Welcome")
            if welcome_role and welcome_role in member.roles:
                await member.remove_roles(welcome_role)
            await member.add_roles(*roles)
            logger.info("Added roles %s to %s", [r.name for r in roles], member.name)
        except discord.Forbidden:
            logger.error("Missing permissions to add roles to %s", member.name)
        except (discord.HTTPException, aiohttp.ClientError) as e:
            logger.error("Error adding roles to %s: %s", member.name, e)


class Verification(commands.Cog):
    def __init__(self, bot):
        print("\n>>> [DEBUG] Verification Cog v3.0 Initialized! <<<")
        self.bot = bot
        self.task_queue = asyncio.Queue()
        self._worker_task = None
        self.active_captchas: set[int] = set()  # member IDs مع جلسة مفتوحة

    async def cog_load(self):
        self._worker_task = asyncio.create_task(self.worker())
        print("✅ Verification worker started")

        custom_id = "verify_button_v2"
        is_registered = any(
            any(getattr(item, 'custom_id', None) == custom_id for item in view.children)
            for view in self.bot.persistent_views
        )
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
                    logger.error("Queue task error: %s", e)
                await asyncio.sleep(0.5)
                self.task_queue.task_done()
            except asyncio.CancelledError:
                print("✅ Worker cancelled cleanly")
                break

    async def queue_task(self, func, *args):
        await self.task_queue.put((func, args))

    # =====================================================
    # Captcha - إنشاء channel مؤقت وإرسال السؤال
    # =====================================================
    async def start_captcha(self, member: discord.Member, guild: discord.Guild):
        self.active_captchas.add(member.id)
        channel = None
        try:
            # جلب كاتيقوري التفعيل
            category = discord.utils.get(guild.categories, name="تفعيل")

            # صلاحيات الـ channel - يشوفه العضو والبوت فقط
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            channel = await guild.create_text_channel(
                name=f"verify-{member.name}",
                category=category,
                overwrites=overwrites,
                reason="Captcha verification channel"
            )

            def check(m):
                return m.author.id == member.id and m.channel.id == channel.id

            for attempt in range(1, CAPTCHA_MAX_TRIES + 1):
                question, answer = _generate_captcha()

                embed = discord.Embed(
                    title="🔐 التحقق من الهوية",
                    description=(
                        f"{member.mention} أجب على السؤال التالي لإتمام التوثيق:\n\n"
                        f"**كم ناتج: {question} ؟**\n\n"
                        f"المحاولة **{attempt}** من **{CAPTCHA_MAX_TRIES}** | لديك **{CAPTCHA_TIMEOUT} ثانية**"
                    ),
                    color=0x3498db
                )
                embed.set_footer(text="نظام الحماية | MSA")
                await channel.send(embed=embed)

                try:
                    msg = await self.bot.wait_for("message", check=check, timeout=CAPTCHA_TIMEOUT)
                except asyncio.TimeoutError:
                    await channel.send("⏰ انتهى الوقت. أعد المحاولة من زر التوثيق.")
                    await asyncio.sleep(3)
                    break

                if msg.content.strip() == str(answer):
                    await self._complete_verification(member, guild, channel)
                    return
                else:
                    if attempt < CAPTCHA_MAX_TRIES:
                        await channel.send(f"❌ إجابة خاطئة. سيتم إرسال سؤال جديد...")
                        await asyncio.sleep(1)
                    else:
                        await channel.send("🚫 استنفذت كل المحاولات. سيتم حظرك.")
                        await asyncio.sleep(2)
                        try:
                            await member.ban(reason="🚫 Failed captcha verification", delete_message_days=1)
                        except (discord.Forbidden, discord.HTTPException) as e:
                            logger.error("Failed to ban %s after captcha fail: %s", member.id, e)

        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Captcha channel error for %s: %s", member.id, e)
        finally:
            self.active_captchas.discard(member.id)
            if channel:
                await asyncio.sleep(3)
                try:
                    await channel.delete(reason="Captcha session ended")
                except (discord.Forbidden, discord.HTTPException):
                    pass

    async def _complete_verification(self, member: discord.Member, guild: discord.Guild, channel: discord.TextChannel):
        """إعطاء الرولات بعد نجاح الـ Captcha"""
        now = discord.utils.utcnow()
        account_age = (now - member.created_at).days
        is_new = account_age < NEW_ACCOUNT_DAYS
        has_avatar = member.avatar is not None

        verified_role = discord.utils.get(guild.roles, name="Verified")
        if not verified_role:
            verified_role = await guild.create_role(name="Verified")

        roles_to_add = [verified_role]
        msg = "✅ تم توثيق حسابك بنجاح!"

        if is_new or not has_avatar:
            watched_role = discord.utils.get(guild.roles, name="Watched")
            if not watched_role:
                watched_role = await guild.create_role(name="Watched", color=discord.Color.orange())
            roles_to_add.append(watched_role)
            msg = "✅ تم توثيق حسابك. ⚠️ حسابك تحت مراقبة إضافية مؤقتاً."

        await channel.send(msg)
        view_instance = VerifyButton()
        await self.queue_task(view_instance.add_roles, member, roles_to_add)

    # =====================================================
    # Commands
    # =====================================================
    @commands.command()
    @guild_owner_only()
    async def setup_verify(self, ctx):
        if getattr(self, "_setup_lock", False):
            return
        self._setup_lock = True

        try:
            await ctx.message.delete()
        except Exception:
            pass

        try:
            embed = discord.Embed(color=0x2b2d31)
            embed.set_author(
                name=ctx.guild.name,
                icon_url=ctx.guild.icon.url if ctx.guild.icon else None
            )
            embed.add_field(
                name="التحقق من الهوية",
                value=(
                    "للوصول إلى قنوات السيرفر، يجب التحقق من حسابك.\n"
                    "اضغط الزر أدناه لإتمام التوثيق."
                ),
                inline=False
            )
            embed.set_footer(text="نظام الحماية | MSA")
            await ctx.send(embed=embed, view=VerifyButton())
            print(f"✅ Verification message created in #{ctx.channel.name}")
        except Exception as e:
            logger.error("setup_verify error: %s", e)
            await ctx.send(f"❌ حدث خطأ: {e}", delete_after=10)
        finally:
            await asyncio.sleep(2)
            self._setup_lock = False

    @commands.command()
    @guild_owner_only()
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
            await member.add_roles(welcome_role)
            logger.info("Gave Welcome role to %s", member.name)
        except discord.Forbidden:
            logger.error("Missing permissions to give Welcome role to %s", member.name)
        except discord.HTTPException as e:
            logger.error("HTTP error giving Welcome role: %s", e)


async def setup(bot):
    await bot.add_cog(Verification(bot))
