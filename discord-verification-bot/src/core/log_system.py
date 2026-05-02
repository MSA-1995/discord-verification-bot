import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import asyncio

class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.deleted_messages = {}
        self.bulk_delete_active = False
        self.processed_events = {}
        # FIX: تشغيل task لتنظيف الذاكرة بشكل دوري
        self.cleanup_task.start()

    def cog_unload(self):
        self.cleanup_task.cancel()

    # =====================================================
    # تنظيف دوري للذاكرة كل 5 دقائق
    # =====================================================
    @tasks.loop(minutes=5)
    async def cleanup_task(self):
        now = datetime.now().timestamp()
        cutoff = now - 60
        self.processed_events = {
            k: v for k, v in self.processed_events.items() if v > cutoff
        }

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # =====================================================
    # دالة مركزية للتحقق من التكرار
    # =====================================================
    def _is_duplicate(self, key: str, window: float = 5.0) -> bool:
        now = datetime.now().timestamp()
        if key in self.processed_events:
            if now - self.processed_events[key] < window:
                return True
        self.processed_events[key] = now
        return False

    # =====================================================
    # FIX: إضافة error handling لـ send_log
    # =====================================================
    async def send_log(self, guild, embed):
        log_channel = discord.utils.get(guild.text_channels, name="📋・logs")
        if log_channel:
            try:
                await log_channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
            except Exception:
                pass  # ConnectionReset/DNS errors - skip silently

    # =====================================================
    # FIX: دالة مساعدة لجلب audit log مع filter زمني
    # =====================================================
    async def _get_audit_entry(self, guild, action, target_id: int):
        """جلب audit log entry خلال آخر 5 ثواني فقط"""
        after_time = datetime.utcnow() - timedelta(seconds=5)
        try:
            async for entry in guild.audit_logs(limit=5, action=action, after=after_time):
                if entry.target.id == target_id:
                    return entry
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    # =====================================================
    # Commands
    # =====================================================
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setup_logs(self, ctx):
        """إنشاء روم اللوقات المخفي"""
        await ctx.message.delete()

        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        log_channel = await ctx.guild.create_text_channel(
            name="📋・logs",
            overwrites=overwrites,
            reason="نظام اللوقات - MSA"
        )

        embed = discord.Embed(
            title="تم إنشاء نظام اللوقات",
            description=f"روم اللوقات: {log_channel.mention}\nمخفي عن الجميع ما عدا الأدمن",
            color=0x00ff00
        )
        embed.set_footer(text="نظام الحماية • MSA")
        await ctx.send(embed=embed, delete_after=10)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx):
        """حذف كل الرسائل من الروم الحالي"""
        try:
            self.bulk_delete_active = True
            deleted = await ctx.channel.purge(limit=None)
            self.bulk_delete_active = False

            msg = await ctx.send(f"✅ تم حذف {len(deleted)} رسالة")
            await asyncio.sleep(3)
            await msg.delete()
        except Exception as e:
            self.bulk_delete_active = False
            await ctx.send(f"❌ خطأ: {e}", delete_after=5)

    # =====================================================
    # Events
    # =====================================================
    @commands.Cog.listener()
    async def on_member_join(self, member):
        key = f"member_join_{member.id}_{member.guild.id}"
        if self._is_duplicate(key):
            return

        embed = discord.Embed(title="دخول السيرفر", color=0x00ff00, timestamp=datetime.now())
        embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
        embed.add_field(name="تاريخ إنشاء الحساب", value=member.created_at.strftime("%Y-%m-%d %H:%M"), inline=True)
        embed.add_field(name="عدد الأعضاء", value=member.guild.member_count, inline=True)
        embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
        embed.set_footer(text="نظام الحماية • MSA")
        await self.send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        key = f"channel_create_{channel.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        if entry:
            embed = discord.Embed(title="إنشاء روم", color=0x00ff00, timestamp=datetime.now())
            embed.add_field(name="الشخص", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="اسم الروم", value=channel.name, inline=True)
            embed.add_field(name="ID الروم", value=channel.id, inline=True)
            embed.set_thumbnail(url=channel.guild.icon.url if channel.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        key = f"role_create_{role.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        if entry:
            embed = discord.Embed(title="إنشاء رول", color=0x00ff00, timestamp=datetime.now())
            embed.add_field(name="الشخص", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="اسم الرول", value=role.name, inline=True)
            embed.add_field(name="ID الرول", value=role.id, inline=True)
            embed.set_thumbnail(url=role.guild.icon.url if role.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(role.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        key = f"channel_delete_{channel.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if entry:
            embed = discord.Embed(title="حذف روم", color=0xff0000, timestamp=datetime.now())
            embed.add_field(name="الشخص", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="اسم الروم", value=channel.name, inline=True)
            embed.add_field(name="ID الروم", value=channel.id, inline=True)
            embed.set_thumbnail(url=channel.guild.icon.url if channel.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        key = f"member_ban_{user.id}_{guild.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(guild, discord.AuditLogAction.ban, user.id)
        if entry:
            embed = discord.Embed(title="باند عضو", color=0xff0000, timestamp=datetime.now())
            embed.add_field(name="المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="العضو", value=f"{user.mention} ({user.id})", inline=False)
            embed.add_field(name="السبب", value=entry.reason or "لا يوجد", inline=False)
            embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(guild, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        key = f"member_unban_{user.id}_{guild.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(guild, discord.AuditLogAction.unban, user.id)
        if entry:
            embed = discord.Embed(title="فك باند", color=0x00ff00, timestamp=datetime.now())
            embed.add_field(name="المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="العضو", value=f"{user.name} ({user.id})", inline=False)
            embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(guild, embed)

    # =====================================================
    # FIX: on_member_kick → on_member_remove + audit logs
    # =====================================================
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        key = f"member_remove_{member.id}_{member.guild.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(member.guild, discord.AuditLogAction.kick, member.id)
        if entry:
            embed = discord.Embed(title="طرد عضو", color=0xff0000, timestamp=datetime.now())
            embed.add_field(name="المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
            embed.add_field(name="العضو", value=f"{member.name} ({member.id})", inline=False)
            embed.add_field(name="السبب", value=entry.reason or "لا يوجد", inline=False)
            embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(member.guild, embed)
        else:
            # العضو غادر من تلقاء نفسه
            embed = discord.Embed(title="مغادرة السيرفر", color=0x808080, timestamp=datetime.now())
            embed.add_field(name="العضو", value=f"{member.name} ({member.id})", inline=False)
            embed.add_field(name="عدد الأعضاء", value=member.guild.member_count, inline=True)
            embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or self.bulk_delete_active:
            return

        key = f"msg_delete_{message.id}_{message.channel.id}"
        if self._is_duplicate(key):
            return

        embed = discord.Embed(title="حذف رسالة", color=0xff0000, timestamp=datetime.now())
        embed.add_field(name="الكاتب", value=f"{message.author.mention} ({message.author.id})", inline=False)
        embed.add_field(name="المحتوى", value=message.content[:1024] if message.content else "لا يوجد", inline=False)
        embed.add_field(name="الروم", value=message.channel.mention, inline=True)
        embed.set_thumbnail(url=message.guild.icon.url if message.guild.icon else None)
        embed.set_footer(text="نظام الحماية • MSA")
        await self.send_log(message.guild, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or before.content == after.content:
            return

        key = f"msg_edit_{before.id}"
        if self._is_duplicate(key):
            return

        embed = discord.Embed(title="تعديل رسالة", color=0xffff00, timestamp=datetime.now())
        embed.add_field(name="الشخص", value=f"{before.author.mention} ({before.author.id})", inline=False)
        embed.add_field(name="قبل", value=before.content[:1024] if before.content else "لا يوجد", inline=False)
        embed.add_field(name="بعد", value=after.content[:1024] if after.content else "لا يوجد", inline=False)
        embed.add_field(name="الروم", value=before.channel.mention, inline=True)
        embed.set_thumbnail(url=before.guild.icon.url if before.guild.icon else None)
        embed.set_footer(text="نظام الحماية • MSA")
        await self.send_log(before.guild, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # تغيير الاسم
        if before.nick != after.nick:
            key = f"nick_update_{after.id}_{after.guild.id}_{after.nick}"
            if not self._is_duplicate(key):
                embed = discord.Embed(title="تغيير الاسم", color=0xffff00, timestamp=datetime.now())
                embed.add_field(name="العضو", value=f"{after.mention} ({after.id})", inline=False)
                embed.add_field(name="قبل", value=before.nick or before.name, inline=True)
                embed.add_field(name="بعد", value=after.nick or after.name, inline=True)
                embed.set_thumbnail(url=after.guild.icon.url if after.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_log(after.guild, embed)

        # إضافة رول
        if len(before.roles) < len(after.roles):
            new_role = list(set(after.roles) - set(before.roles))[0]
            key = f"role_add_{after.id}_{new_role.id}"
            if not self._is_duplicate(key):
                await asyncio.sleep(1)
                # FIX: التحقق إن الـ entry يخص نفس العضو
                entry = await self._get_audit_entry(
                    after.guild, discord.AuditLogAction.member_role_update, after.id
                )
                if entry:
                    embed = discord.Embed(title="إعطاء رول", color=0x00ff00, timestamp=datetime.now())
                    embed.add_field(name="المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                    embed.add_field(name="العضو", value=f"{after.mention} ({after.id})", inline=False)
                    embed.add_field(name="الرول", value=new_role.mention, inline=True)
                    embed.set_thumbnail(url=after.guild.icon.url if after.guild.icon else None)
                    embed.set_footer(text="نظام الحماية • MSA")
                    await self.send_log(after.guild, embed)

        # سحب رول
        if len(before.roles) > len(after.roles):
            removed_role = list(set(before.roles) - set(after.roles))[0]
            key = f"role_remove_{after.id}_{removed_role.id}"
            if not self._is_duplicate(key):
                await asyncio.sleep(1)
                # FIX: التحقق إن الـ entry يخص نفس العضو
                entry = await self._get_audit_entry(
                    after.guild, discord.AuditLogAction.member_role_update, after.id
                )
                if entry:
                    embed = discord.Embed(title="سحب رول", color=0xff0000, timestamp=datetime.now())
                    embed.add_field(name="المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                    embed.add_field(name="العضو", value=f"{after.mention} ({after.id})", inline=False)
                    embed.add_field(name="الرول", value=removed_role.name, inline=True)
                    embed.set_thumbnail(url=after.guild.icon.url if after.guild.icon else None)
                    embed.set_footer(text="نظام الحماية • MSA")
                    await self.send_log(after.guild, embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # دخول روم صوتي
        if before.channel is None and after.channel is not None:
            key = f"vc_join_{member.id}_{after.channel.id}"
            if self._is_duplicate(key):
                return
            embed = discord.Embed(title="دخول روم صوتي", color=0x00ff00, timestamp=datetime.now())
            embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
            embed.add_field(name="الروم", value=after.channel.name, inline=True)
            embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(member.guild, embed)

        # خروج من روم صوتي
        elif before.channel is not None and after.channel is None:
            key = f"vc_leave_{member.id}_{before.channel.id}"
            if self._is_duplicate(key):
                return
            embed = discord.Embed(title="خروج من روم صوتي", color=0xff0000, timestamp=datetime.now())
            embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
            embed.add_field(name="الروم", value=before.channel.name, inline=True)
            embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(member.guild, embed)

        # تنقل بين رومات
        elif before.channel != after.channel and before.channel is not None and after.channel is not None:
            key = f"vc_move_{member.id}_{before.channel.id}_{after.channel.id}"
            if self._is_duplicate(key):
                return
            embed = discord.Embed(title="تنقل بين رومات صوتية", color=0xffff00, timestamp=datetime.now())
            embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
            embed.add_field(name="من", value=before.channel.name, inline=True)
            embed.add_field(name="إلى", value=after.channel.name, inline=True)
            embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(member.guild, embed)

async def setup(bot):
    await bot.add_cog(Logging(bot))