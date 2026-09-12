import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import os
from src.utils.embed_utils import build_log_embed, get_audit_entry
from src.config import channels_config

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
        log_channel = channels_config.get_log_channel(guild)
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
    # مقارنة صلاحيات رول قبل/بعد - يرجع (صلاحيات أُضيفت, صلاحيات أُزيلت)
    # =====================================================
    def _diff_permissions(self, before_perms: discord.Permissions, after_perms: discord.Permissions):
        before_dict = dict(before_perms)
        after_dict = dict(after_perms)
        added = [name for name, value in after_dict.items() if value and not before_dict.get(name)]
        removed = [name for name, value in before_dict.items() if value and not after_dict.get(name)]
        return added, removed

    # =====================================================
    # مقارنة overwrites روم قبل/بعد - يرجع أسماء الأهداف اللي تغيّرت صلاحياتهم
    # =====================================================
    def _diff_overwrites(self, before_channel, after_channel):
        def _pairs(channel):
            result = {}
            for target, overwrite in channel.overwrites.items():
                allow, deny = overwrite.pair()
                result[target.id] = (target, allow.value, deny.value)
            return result

        before_map = _pairs(before_channel)
        after_map = _pairs(after_channel)
        changed = []

        for tid, (target, allow, deny) in after_map.items():
            old = before_map.get(tid)
            if old is None or old[1:] != (allow, deny):
                changed.append(target.name)

        for tid, (target, _, _) in before_map.items():
            if tid not in after_map:
                changed.append(f"{target.name} (أُزيل)")

        return changed

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
            name=channels_config.LOG_CHANNEL_NAME,
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
        changes = []
        if before.name != after.name:
            changes += [("الاسم قبل", before.name, True), ("الاسم بعد", after.name, True)]

        if hasattr(before, "topic") and getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append((
                "الموضوع",
                f"{before.topic or 'لا يوجد'} ← {after.topic or 'لا يوجد'}"[:1024],
                False
            ))

        if hasattr(before, "slowmode_delay") and before.slowmode_delay != after.slowmode_delay:
            changes.append(("الإبطاء (Slowmode)", f"{before.slowmode_delay}s ← {after.slowmode_delay}s", True))

        if hasattr(before, "nsfw") and before.nsfw != after.nsfw:
            changes.append(("NSFW", "تفعيل" if after.nsfw else "إيقاف", True))

        if before.overwrites != after.overwrites:
            changed_targets = self._diff_overwrites(before, after)
            if changed_targets:
                changes.append(("صلاحيات مُعدّلة لـ", "، ".join(changed_targets)[:1024], False))

        if not changes:
            return

        key = (
            f"channel_update_{after.id}_{after.name}_"
            f"{getattr(after, 'topic', None)}_{getattr(after, 'slowmode_delay', None)}_"
            f"{getattr(after, 'nsfw', None)}_{len(after.overwrites)}"
        )
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(after.guild, discord.AuditLogAction.channel_update, after.id)
        if entry:
            embed = self._build_log_embed(
                title="تعديل روم",
                color=0xffff00,
                member=entry.user,
                fields=[("الشخص", f"{entry.user.mention}", True), ("الآيدي", f"`{entry.user.id}`", True)] + changes
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
        changes = []
        if before.name != after.name:
            changes += [("الاسم قبل", before.name, True), ("الاسم بعد", after.name, True)]
        if before.color != after.color:
            changes += [("اللون قبل", str(before.color), True), ("اللون بعد", str(after.color), True)]
        if before.hoist != after.hoist:
            changes.append(("العرض المنفصل", "تفعيل" if after.hoist else "إيقاف", True))
        if before.mentionable != after.mentionable:
            changes.append(("قابل للمنشن", "تفعيل" if after.mentionable else "إيقاف", True))
        if before.permissions != after.permissions:
            added, removed = self._diff_permissions(before.permissions, after.permissions)
            if added:
                changes.append(("صلاحيات أُضيفت", "، ".join(added)[:1024], False))
            if removed:
                changes.append(("صلاحيات أُزيلت", "، ".join(removed)[:1024], False))

        if not changes:
            return

        key = f"role_update_{after.id}_{after.permissions.value}_{after.name}_{after.color.value}_{after.hoist}_{after.mentionable}"
        if self._is_duplicate(key):
            return

        await asyncio.sleep(1)
        entry = await self._get_audit_entry(after.guild, discord.AuditLogAction.role_update, after.id)
        if entry:
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

        # نتحقق من الباند أولاً قبل الكيك
        ban_entry = await self._get_audit_entry(member.guild, discord.AuditLogAction.ban, member.id)
        if ban_entry:
            return  # الباند يسجله on_member_ban بشكل منفصل

        kick_entry = await self._get_audit_entry(member.guild, discord.AuditLogAction.kick, member.id)
        if kick_entry:
            embed = self._build_log_embed(
                title="طرد عضو",
                color=0xff0000,
                member=member,
                fields=[
                    ("المسؤول", f"{kick_entry.user.mention}", True),
                    ("العضو", f"{member.name}", True),
                    ("الآيدي", f"`{member.id}`", True),
                    ("السبب", kick_entry.reason or "لا يوجد", False),
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
    async def on_webhooks_update(self, channel):
        key = f"webhook_update_{channel.id}"
        if self._is_duplicate(key, window=10.0):
            return

        await asyncio.sleep(1)
        entry_create = await self._get_audit_entry(channel.guild, discord.AuditLogAction.webhook_create, channel.id)
        entry_delete = await self._get_audit_entry(channel.guild, discord.AuditLogAction.webhook_delete, channel.id)
        entry = entry_create or entry_delete

        # لو ما لقينا entry إنشاء أو حذف = تعديل من البوت نفسه، نتجاهله
        if not entry:
            return

        # لو البوت هو اللي أنشأ الويب هوك نتجاهله
        if entry.user.id == self.bot.user.id:
            return

        action_label = "إنشاء" if entry_create else "حذف"
        color = 0x00ff00 if entry_create else 0xff0000
        actor = entry.user

        embed = self._build_log_embed(
            title=f"⚠️ {action_label} ويب هوك",
            color=color,
            member=actor,
            fields=[
                ("الشخص", f"{actor.mention}", True),
                ("الآيدي", f"`{actor.id}`", True),
                ("الروم", channel.mention, True),
                ("الإجراء", action_label, True),
            ]
        )
        await self.send_log(channel.guild, embed)

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

    # =====================================================
    # تسجيل استخدام أوامر البوت (نجحت أو فشلت) - من أي كوج بالمشروع
    # =====================================================
    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if not ctx.guild:
            return
        await self._log_command_attempt(ctx, success=True)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if not ctx.guild:
            return
        # حد كتب حاجة مو أمر حقيقي أصلاً (غلطة كتابة) - تجاهل، مش محاولة فعلية
        if isinstance(error, commands.CommandNotFound):
            return
        await self._log_command_attempt(ctx, success=False, error=error)

    async def _log_command_attempt(self, ctx, success: bool, error: Exception | None = None):
        key = f"cmd_used_{ctx.message.id}"
        if self._is_duplicate(key):
            return

        if success:
            result_text = "✅ نجح"
            color = 0x3498db
        else:
            result_text = f"❌ فشل — {self._format_command_error(error)}"
            color = 0xff0000

        embed = self._build_log_embed(
            title="استخدام أمر",
            color=color,
            member=ctx.author,
            fields=[
                ("العضو", f"{ctx.author.mention}", True),
                ("الآيدي", f"`{ctx.author.id}`", True),
                ("الروم", ctx.channel.mention, True),
                ("الأمر", f"`{ctx.message.content[:200]}`", False),
                ("النتيجة", result_text, False),
            ]
        )
        await self.send_log(ctx.guild, embed)

    def _format_command_error(self, error: Exception) -> str:
        if isinstance(error, commands.CheckFailure):
            return "ما عنده الصلاحية المطلوبة"
        if isinstance(error, commands.MissingRequiredArgument):
            return f"ناقص معطى: `{error.param.name}`"
        if isinstance(error, commands.BadArgument):
            return "معطى غير صحيح"
        if isinstance(error, commands.CommandOnCooldown):
            return f"Cooldown - حاول بعد {error.retry_after:.0f} ثانية"
        return (str(error) or type(error).__name__)[:200]

async def setup(bot):
    await bot.add_cog(Logging(bot))
