import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import os
from src.utils.embed_utils import build_log_embed, get_audit_entry

logger = logging.getLogger(__name__)

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
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("send_log failed: %s", e)
        except Exception as e:
            logger.error("send_log unexpected error: %s", e)

    # =====================================================
    # نقطة 8: _build_log_embed و _get_audit_entry من embed_utils
    # =====================================================
    def _build_log_embed(self, **kwargs):
        return build_log_embed(self.bot, **kwargs)

    async def _get_audit_entry(self, guild, action, target_id: int):
        return await get_audit_entry(guild, action, target_id)

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
            reason="نظام اللوقات - ᴹˢᴬ"
        )

        embed = discord.Embed(
            title="تم إنشاء نظام اللوقات",
            description=f"روم اللوقات: {log_channel.mention}\nمخفي عن الجميع ما عدا الأدمن",
            color=0x00ff00
        )
        embed.set_footer(text="نظام الحماية • ᴹˢᴬ")
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
    async def on_guild_channel_update(self, before, after):
        if before.name == after.name:
            return
        key = f"channel_update_{after.id}_{after.name}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(after.guild, discord.AuditLogAction.channel_update, after.id)
        if entry:
            embed = self._build_log_embed(
                title="تعديل روم",
                color=0xffff00,
                member=entry.user,
                fields=[
                    ("الشخص", f"{entry.user.mention}", True),
                    ("الآيدي", f"`{entry.user.id}`", True),
                    ("قبل", before.name, True),
                    ("بعد", after.name, True),
                ]
            )
            await self.send_log(after.guild, embed)

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
    async def on_guild_role_update(self, before, after):
        if before.name == after.name and before.color == after.color:
            return
        key = f"role_update_{after.id}_{after.name}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(after.guild, discord.AuditLogAction.role_update, after.id)
        if entry:
            changes = []
            if before.name != after.name:
                changes += [("الاسم قبل", before.name, True), ("الاسم بعد", after.name, True)]
            if before.color != after.color:
                changes += [("اللون قبل", str(before.color), True), ("اللون بعد", str(after.color), True)]
            embed = self._build_log_embed(
                title="تعديل رول",
                color=0xffff00,
                member=entry.user,
                fields=[("الشخص", f"{entry.user.mention}", True), ("الآيدي", f"`{entry.user.id}`", True)] + changes
            )
            await self.send_log(after.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        key = f"role_delete_{role.id}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
        if entry:
            embed = self._build_log_embed(
                title="حذف رول",
                color=0xff0000,
                member=entry.user,
                fields=[
                    ("الشخص", f"{entry.user.mention}", True),
                    ("الآيدي", f"`{entry.user.id}`", True),
                    ("اسم الرول", role.name, True),
                ]
            )
            await self.send_log(role.guild, embed)

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        key = f"invite_create_{invite.code}"
        if self._is_duplicate(key):
            return

        embed = self._build_log_embed(
            title="إنشاء دعوة",
            color=0x00ff00,
            member=invite.inviter,
            fields=[
                ("الشخص", f"{invite.inviter.mention}", True),
                ("الآيدي", f"`{invite.inviter.id}`", True),
                ("الروم", invite.channel.mention, True),
                ("الكود", f"`{invite.code}`", True),
                ("الصلاحية", f"{invite.max_uses or 'لا نهاية'} استخدام", True),
            ]
        )
        await self.send_log(invite.guild, embed)

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
    async def on_guild_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes += [("الاسم قبل", before.name, True), ("الاسم بعد", after.name, True)]
        if before.icon != after.icon:
            changes.append(("الأيقونة", "تم تغييرها", True))
        if not changes:
            return

        key = f"guild_update_{after.id}_{after.name}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(after, discord.AuditLogAction.guild_update, after.id)
        actor = entry.user if entry else None
        embed = self._build_log_embed(
            title="تعديل السيرفر",
            color=0xffff00,
            member=actor,
            fields=([("الشخص", f"{actor.mention}", True), ("الآيدي", f"`{actor.id}`", True)] if actor else []) + changes
        )
        await self.send_log(after, embed)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        before_set = {e.id: e for e in before}
        after_set = {e.id: e for e in after}

        added = [e for e in after if e.id not in before_set]
        removed = [e for e in before if e.id not in after_set]

        for emoji in added:
            key = f"emoji_add_{emoji.id}"
            if self._is_duplicate(key):
                continue
            embed = self._build_log_embed(
                title="إضافة إيموجي",
                color=0x00ff00,
                fields=[("الاسم", f":{emoji.name}:", True), ("الآيدي", f"`{emoji.id}`", True)]
            )
            await self.send_log(guild, embed)

        for emoji in removed:
            key = f"emoji_remove_{emoji.id}"
            if self._is_duplicate(key):
                continue
            embed = self._build_log_embed(
                title="حذف إيموجي",
                color=0xff0000,
                fields=[("الاسم", f":{emoji.name}:", True), ("الآيدي", f"`{emoji.id}`", True)]
            )
            await self.send_log(guild, embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        key = f"invite_delete_{invite.code}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(invite.guild, discord.AuditLogAction.invite_delete, invite.guild.id)
        actor = entry.user if entry else None
        embed = self._build_log_embed(
            title="حذف دعوة",
            color=0xff0000,
            member=actor,
            fields=[
                ("الشخص", f"{actor.mention}" if actor else "غير معروف", True),
                ("الروم", invite.channel.mention, True),
                ("الكود", f"`{invite.code}`", True),
            ]
        )
        await self.send_log(invite.guild, embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if self.bulk_delete_active or not messages:
            return

        channel = messages[0].channel
        key = f"bulk_delete_{channel.id}"
        if self._is_duplicate(key):
            return

        embed = self._build_log_embed(
            title="حذف رسائل بالجملة",
            color=0xff0000,
            fields=[
                ("الروم", channel.mention, True),
                ("عدد الرسائل", str(len(messages)), True),
            ]
        )
        await self.send_log(channel.guild, embed)

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
                entry = await self._get_audit_entry(after.guild, discord.AuditLogAction.member_role_update, after.id)
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
                entry = await self._get_audit_entry(after.guild, discord.AuditLogAction.member_role_update, after.id)
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

        # تايم أوت
        if before.timed_out_until != after.timed_out_until:
            key = f"timeout_{after.id}_{after.guild.id}"
            if not self._is_duplicate(key):
                await asyncio.sleep(1)
                entry = await self._get_audit_entry(after.guild, discord.AuditLogAction.member_update, after.id)
                if after.timed_out_until:
                    embed = self._build_log_embed(
                        title="تايم أوت عضو",
                        color=0xff8800,
                        member=after,
                        fields=[
                            ("المسؤول", f"{entry.user.mention}" if entry else "غير معروف", True),
                            ("العضو", f"{after.mention}", True),
                            ("الآيدي", f"`{after.id}`", True),
                            ("ينتهي", after.timed_out_until.strftime("%Y-%m-%d %H:%M"), True),
                            ("السبب", entry.reason or "لا يوجد" if entry else "لا يوجد", False),
                        ]
                    )
                else:
                    embed = self._build_log_embed(
                        title="رفع تايم أوت",
                        color=0x00ff00,
                        member=after,
                        fields=[
                            ("المسؤول", f"{entry.user.mention}" if entry else "غير معروف", True),
                            ("العضو", f"{after.mention}", True),
                            ("الآيدي", f"`{after.id}`", True),
                        ]
                    )
                await self.send_log(after.guild, embed)

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes += [("اليوزر قبل", before.name, True), ("اليوزر بعد", after.name, True)]
        if before.display_avatar != after.display_avatar:
            changes.append(("الأفاتار", "تم تغييره", True))
        if not changes:
            return

        key = f"user_update_{after.id}_{after.name}"
        if self._is_duplicate(key):
            return

        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if member:
                embed = self._build_log_embed(
                    title="تعديل حساب",
                    color=0xffff00,
                    member=after,
                    fields=[("العضو", f"{after.mention}", True), ("الآيدي", f"`{after.id}`", True)] + changes
                )
                await self.send_log(guild, embed)
                break

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