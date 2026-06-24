import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import asyncio
import aiohttp
import os

def guild_owner_only():
    async def predicate(ctx):
        if ctx.guild and ctx.author.id == ctx.guild.owner_id:
            return True
        await ctx.send("❌ هذا الأمر مخصص لمالك السيرفر فقط.", delete_after=7)
        return False
    return commands.check(predicate)

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
        now = datetime.now(timezone.utc).timestamp()
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
        now = datetime.now(timezone.utc).timestamp()
        if key in self.processed_events:
            if now - self.processed_events[key] < window:
                return True
        self.processed_events[key] = now
        return False

    # =====================================================
    # FIX: إضافة error handling لـ send_log
    # =====================================================
    async def send_log(self, guild, embed):
        log_channel_id = os.getenv("LOG_CHANNEL_ID")
        log_channel = None
        if log_channel_id and log_channel_id.isdigit():
            log_channel = guild.get_channel(int(log_channel_id))
        if not log_channel:
            log_channel = discord.utils.get(guild.text_channels, name="📋・logs")
        if not log_channel:
            print(f"⚠️ Warning: Log channel not found in {guild.name}")
            return

        try:
            await log_channel.send(embed=embed)
        except Exception as e:
            print(f"⚠️ Failed to send log: {e}")

    def _build_log_embed(self, *, title, color, member=None, user=None, fields=None, guild=None):
        """بناء embed موحد للوقات"""
        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=datetime.now(timezone.utc)
        )

        # Author row
        bot_avatar = self.bot.user.avatar.url if self.bot.user.avatar else None
        embed.set_author(name="نظام الحماية", icon_url=bot_avatar)

        # صورة العضو كـ thumbnail
        target = member or user
        if target:
            if hasattr(target, 'avatar') and target.avatar:
                embed.set_thumbnail(url=target.avatar.url)
            elif hasattr(target, 'default_avatar'):
                embed.set_thumbnail(url=target.default_avatar.url)

        # الحقول
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=value, inline=inline)

        # Footer
        embed.set_footer(text="نظام الحماية | MSA")

        return embed

    # =====================================================
    # FIX: دالة مساعدة لجلب audit log مع filter زمني
    # =====================================================
    async def _get_audit_entry(self, guild, action, target_id: int):
        """جلب audit log entry خلال آخر 5 ثواني فقط"""
        after_time = datetime.now(timezone.utc) - timedelta(seconds=5)
        try:
            # متوافق مع بايثون 3.10 و 3.13
            async def fetch():
                async for entry in guild.audit_logs(limit=5, action=action, after=after_time):
                    if entry.target and entry.target.id == target_id:
                        return entry
                return None
            return await asyncio.wait_for(fetch(), timeout=3.0)
        except (discord.Forbidden, discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return None

    # =====================================================
    # Commands
    # =====================================================
    @commands.command()
    @guild_owner_only()
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
    @guild_owner_only()
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

        embed = self._build_log_embed(
            title="دخول السيرفر",
            color=0x00ff00,
            member=member,
            fields=[
                ("العضو", f"{member.mention}", True),
                ("الآيدي", f"`{member.id}`", True),
                ("تاريخ إنشاء الحساب", member.created_at.strftime("%Y-%m-%d %H:%M"), True),
                ("عدد الأعضاء", str(member.guild.member_count), True),
            ]
        )
        await self.send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        key = f"channel_create_{channel.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        if entry:
            embed = self._build_log_embed(
                title="إنشاء روم",
                color=0x00ff00,
                member=entry.user,
                fields=[
                    ("الشخص", f"{entry.user.mention}", True),
                    ("الآيدي", f"`{entry.user.id}`", True),
                    ("اسم الروم", channel.name, True),
                ]
            )
            await self.send_log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        key = f"role_create_{role.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        if entry:
            embed = self._build_log_embed(
                title="إنشاء رول",
                color=0x00ff00,
                member=entry.user,
                fields=[
                    ("الشخص", f"{entry.user.mention}", True),
                    ("الآيدي", f"`{entry.user.id}`", True),
                    ("اسم الرول", role.name, True),
                ]
            )
            await self.send_log(role.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        key = f"channel_delete_{channel.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if entry:
            embed = self._build_log_embed(
                title="حذف روم",
                color=0xff0000,
                member=entry.user,
                fields=[
                    ("الشخص", f"{entry.user.mention}", True),
                    ("الآيدي", f"`{entry.user.id}`", True),
                    ("اسم الروم", channel.name, True),
                ]
            )
            await self.send_log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        key = f"member_ban_{user.id}_{guild.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(guild, discord.AuditLogAction.ban, user.id)
        if entry:
            embed = self._build_log_embed(
                title="باند عضو",
                color=0xff0000,
                user=user,
                fields=[
                    ("المسؤول", f"{entry.user.mention}", True),
                    ("العضو", f"{user.mention}", True),
                    ("الآيدي", f"`{user.id}`", True),
                    ("السبب", entry.reason or "لا يوجد", False),
                ]
            )
            await self.send_log(guild, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        key = f"member_unban_{user.id}_{guild.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(guild, discord.AuditLogAction.unban, user.id)
        if entry:
            embed = self._build_log_embed(
                title="فك باند",
                color=0x00ff00,
                user=user,
                fields=[
                    ("المسؤول", f"{entry.user.mention}", True),
                    ("العضو", f"{user.name}", True),
                    ("الآيدي", f"`{user.id}`", True),
                ]
            )
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
            embed = self._build_log_embed(
                title="طرد عضو",
                color=0xff0000,
                member=member,
                fields=[
                    ("المسؤول", f"{entry.user.mention}", True),
                    ("العضو", f"{member.name}", True),
                    ("الآيدي", f"`{member.id}`", True),
                    ("السبب", entry.reason or "لا يوجد", False),
                ]
            )
            await self.send_log(member.guild, embed)
        else:
            embed = self._build_log_embed(
                title="مغادرة السيرفر",
                color=0x808080,
                member=member,
                fields=[
                    ("العضو", f"{member.name}", True),
                    ("الآيدي", f"`{member.id}`", True),
                    ("عدد الأعضاء", str(member.guild.member_count), True),
                ]
            )
            await self.send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.author or message.author.bot or self.bulk_delete_active:
            return

        key = f"msg_delete_{message.id}_{message.channel.id}"
        if self._is_duplicate(key):
            return

        embed = self._build_log_embed(
            title="حذف رسالة",
            color=0xff0000,
            member=message.author,
            fields=[
                ("الكاتب", f"{message.author.mention}", True),
                ("الآيدي", f"`{message.author.id}`", True),
                ("الروم", message.channel.mention, True),
                ("المحتوى", message.content[:1024] if message.content else "لا يوجد", False),
            ]
        )
        await self.send_log(message.guild, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.author or before.author.bot or before.content == after.content:
            return

        key = f"msg_edit_{before.id}"
        if self._is_duplicate(key):
            return

        embed = self._build_log_embed(
            title="تعديل رسالة",
            color=0xffff00,
            member=before.author,
            fields=[
                ("الشخص", f"{before.author.mention}", True),
                ("الآيدي", f"`{before.author.id}`", True),
                ("الروم", before.channel.mention, True),
                ("قبل", before.content[:1024] if before.content else "لا يوجد", False),
                ("بعد", after.content[:1024] if after.content else "لا يوجد", False),
            ]
        )
        await self.send_log(before.guild, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # تغيير الاسم
        if before.nick != after.nick:
            key = f"nick_update_{after.id}_{after.guild.id}_{after.nick}"
            if not self._is_duplicate(key):
                embed = self._build_log_embed(
                    title="تغيير الاسم",
                    color=0xffff00,
                    member=after,
                    fields=[
                        ("العضو", f"{after.mention}", True),
                        ("الآيدي", f"`{after.id}`", True),
                        ("قبل", before.nick or before.name, True),
                        ("بعد", after.nick or after.name, True),
                    ]
                )
                await self.send_log(after.guild, embed)

        # إضافة رول
        if len(before.roles) < len(after.roles):
            new_role = list(set(after.roles) - set(before.roles))[0]
            key = f"role_add_{after.id}_{new_role.id}"
            if not self._is_duplicate(key):
                await asyncio.sleep(1)
                entry = await self._get_audit_entry(
                    after.guild, discord.AuditLogAction.member_role_update, after.id
                )
                if entry:
                    embed = self._build_log_embed(
                        title="إعطاء رول",
                        color=0x00ff00,
                        member=after,
                        fields=[
                            ("المسؤول", f"{entry.user.mention}", True),
                            ("العضو", f"{after.mention}", True),
                            ("الرول", new_role.mention, True),
                        ]
                    )
                    await self.send_log(after.guild, embed)

        # سحب رول
        if len(before.roles) > len(after.roles):
            removed_role = list(set(before.roles) - set(after.roles))[0]
            key = f"role_remove_{after.id}_{removed_role.id}"
            if not self._is_duplicate(key):
                await asyncio.sleep(1)
                entry = await self._get_audit_entry(
                    after.guild, discord.AuditLogAction.member_role_update, after.id
                )
                if entry:
                    embed = self._build_log_embed(
                        title="سحب رول",
                        color=0xff0000,
                        member=after,
                        fields=[
                            ("المسؤول", f"{entry.user.mention}", True),
                            ("العضو", f"{after.mention}", True),
                            ("الرول", removed_role.name, True),
                        ]
                    )
                    await self.send_log(after.guild, embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # دخول روم صوتي
        if before.channel is None and after.channel is not None:
            key = f"vc_join_{member.id}_{after.channel.id}"
            if self._is_duplicate(key, window=2.0):
                return
            embed = self._build_log_embed(
                title="دخول روم صوتي",
                color=0x00ff00,
                member=member,
                fields=[
                    ("العضو", f"{member.mention}", True),
                    ("الآيدي", f"`{member.id}`", True),
                    ("الروم", after.channel.name, True),
                ]
            )
            await self.send_log(member.guild, embed)

        # خروج من روم صوتي
        elif before.channel is not None and after.channel is None:
            key = f"vc_leave_{member.id}_{before.channel.id}"
            if self._is_duplicate(key, window=2.0):
                return
            embed = self._build_log_embed(
                title="خروج من روم صوتي",
                color=0xff0000,
                member=member,
                fields=[
                    ("العضو", f"{member.mention}", True),
                    ("الآيدي", f"`{member.id}`", True),
                    ("الروم", before.channel.name, True),
                ]
            )
            await self.send_log(member.guild, embed)

        # تنقل بين رومات
        elif before.channel != after.channel and before.channel is not None and after.channel is not None:
            key = f"vc_move_{member.id}_{before.channel.id}_{after.channel.id}"
            if self._is_duplicate(key):
                return
            embed = self._build_log_embed(
                title="تنقل بين رومات صوتية",
                color=0xffff00,
                member=member,
                fields=[
                    ("العضو", f"{member.mention}", True),
                    ("الآيدي", f"`{member.id}`", True),
                    ("من", before.channel.name, True),
                    ("إلى", after.channel.name, True),
                ]
            )
            await self.send_log(member.guild, embed)

async def setup(bot):
    await bot.add_cog(Logging(bot))