import discord
from discord.ext import commands
import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def guild_owner_only():
    async def predicate(ctx):
        if ctx.guild and ctx.author.id == ctx.guild.owner_id:
            return True
        await ctx.send("❌ هذا الأمر مخصص لمالك السيرفر فقط.", delete_after=7)
        return False
    return commands.check(predicate)


class Backup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._restore_lock = False

    # =====================================================
    # !backup - حفظ السيرفر
    # =====================================================
    @commands.command()
    @guild_owner_only()
    async def backup(self, ctx):
        """حفظ نسخة احتياطية من رولات وقنوات السيرفر"""
        try:
            await ctx.message.delete()
        except Exception:
            pass

        msg = await ctx.send("⏳ جاري حفظ نسخة احتياطية...")

        guild = ctx.guild
        data = {
            "guild_name": guild.name,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "everyone_permissions": guild.default_role.permissions.value,
            "roles": [],
            "categories": [],
            "channels": []
        }

        # حفظ الرولات (ما عدا @everyone)
        for role in sorted(guild.roles, key=lambda r: r.position):
            if role.is_default():
                continue
            if role.managed:  # رولات البوتات - تخطى
                continue
            data["roles"].append({
                "id": role.id,
                "name": role.name,
                "color": role.color.value,
                "permissions": role.permissions.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "position": role.position
            })

        # حفظ الكاتيقوريات
        for category in sorted(guild.categories, key=lambda c: c.position):
            overwrites = {}
            for target, overwrite in category.overwrites.items():
                allow, deny = overwrite.pair()
                overwrites[str(target.id)] = {
                    "id": target.id,
                    "name": target.name,
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value
                }
            data["categories"].append({
                "name": category.name,
                "position": category.position,
                "overwrites": overwrites
            })

        # حفظ الرومات
        for channel in sorted(guild.channels, key=lambda c: c.position):
            if isinstance(channel, discord.CategoryChannel):
                continue

            overwrites = {}
            for target, overwrite in channel.overwrites.items():
                allow, deny = overwrite.pair()
                overwrites[str(target.id)] = {
                    "id": target.id,
                    "name": target.name,
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value
                }

            channel_data = {
                "name": channel.name,
                "type": str(channel.type),
                "position": channel.position,
                "category": channel.category.name if channel.category else None,
                "overwrites": overwrites
            }

            if isinstance(channel, discord.TextChannel):
                channel_data["topic"] = channel.topic or ""
                channel_data["slowmode"] = channel.slowmode_delay
                channel_data["nsfw"] = channel.is_nsfw()

            elif isinstance(channel, discord.VoiceChannel):
                channel_data["bitrate"] = channel.bitrate
                channel_data["user_limit"] = channel.user_limit

            data["channels"].append(channel_data)

        # إرسال الملف كرسالة خاصة للأونر فقط
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        MAX_BYTES = 8 * 1024 * 1024  # 8MB حد ديسكورد
        if len(json_bytes) > MAX_BYTES:
            await msg.delete()
            await ctx.send("❌ حجم الباكب كبير جداً، حاول تقليل عدد الرومات أو الرولات.", delete_after=10)
            return

        file = discord.File(
            fp=__import__("io").BytesIO(json_bytes),
            filename=f"backup_{guild.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        await msg.delete()
        try:
            await ctx.author.send(
                f"✅ نسخة احتياطية لسيرفر **{guild.name}** | **{len(data['roles'])}** رول | **{len(data['categories'])}** كاتيقوري | **{len(data['channels'])}** روم",
                file=file
            )
            await ctx.send("✅ تم إرسال النسخة الاحتياطية في رسالة خاصة.", delete_after=5)
        except discord.Forbidden:
            await ctx.send("❌ ما قدرت أرسل لك رسالة خاصة، تأكد إن الرسائل الخاصة مفتوحة.", delete_after=10)

    # =====================================================
    # !restore - استعادة السيرفر
    # =====================================================
    @commands.command()
    @guild_owner_only()
    async def restore(self, ctx):
        """استعادة السيرفر من ملف backup - أرفق الملف مع الأمر"""
        if self._restore_lock:
            await ctx.send("⚠️ عملية استعادة جارية بالفعل، انتظر حتى تنتهي.", delete_after=7)
            return

        if not ctx.message.attachments:
            await ctx.send("❌ أرفق ملف الـ backup مع الأمر.", delete_after=7)
            return

        attachment = ctx.message.attachments[0]
        if not attachment.filename.endswith(".json"):
            await ctx.send("❌ الملف يجب أن يكون بصيغة `.json`.", delete_after=7)
            return

        try:
            await ctx.message.delete()
        except Exception:
            pass

        # تحميل الملف
        try:
            raw = await attachment.read()
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            await ctx.send(f"❌ فشل قراءة الملف: {e}", delete_after=10)
            return

        # تحقق من بنية الملف قبل التطبيق
        if not isinstance(data, dict) or "roles" not in data or "channels" not in data:
            await ctx.send("❌ الملف غير صحيح، تأكد إنه ملف backup صحيح.", delete_after=10)
            return

        self._restore_lock = True
        msg = await ctx.send("⏳ جاري استعادة السيرفر...")
        guild = ctx.guild
        stats = {"roles": 0, "categories": 0, "channels": 0, "errors": 0}

        total_items = len(data.get("roles", [])) + len(data.get("categories", [])) + len(data.get("channels", []))
        done_items = 0

        async def _bump_progress():
            nonlocal done_items
            done_items += 1
            if done_items % 5 == 0 or done_items == total_items:
                try:
                    await msg.edit(content=f"⏳ جاري استعادة السيرفر... ({done_items}/{total_items})")
                except discord.HTTPException:
                    pass

        # يربط الـ ID القديم (من ملف الـ backup) بالرول الفعلي الحالي (سواء تم
        # إنشاؤه الآن أو كان موجود بنفس الاسم أصلاً). هذا يخلي مطابقة صلاحيات
        # القنوات (overwrites) تعتمد على الهوية الحقيقية للرول بدل الاسم فقط.
        role_id_map: dict[int, discord.Role] = {}

        try:
            # 1. استعادة الرولات
            existing_roles = {r.name: r for r in guild.roles}
            for role_data in data.get("roles", []):
                try:
                    existing = existing_roles.get(role_data["name"])
                    if existing:
                        role_id_map[role_data.get("id")] = existing
                        continue  # الرول موجود، تخطى
                    new_role = await guild.create_role(
                        name=role_data["name"],
                        color=discord.Color(role_data["color"]),
                        permissions=discord.Permissions(role_data["permissions"]),
                        hoist=role_data["hoist"],
                        mentionable=role_data["mentionable"],
                        reason="🔄 Restore backup"
                    )
                    role_id_map[role_data.get("id")] = new_role
                    stats["roles"] += 1
                    await _bump_progress()
                    await asyncio.sleep(0.5)  # تجنب rate limit
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error("Failed to create role %s: %s", role_data["name"], e)
                    stats["errors"] += 1

            # صلاحيات @everyone نفسها (ما ينحفظش/يترجعش تلقائياً لأنه مش رول قابل للإنشاء)
            everyone_perms = data.get("everyone_permissions")
            if everyone_perms is not None:
                try:
                    await guild.default_role.edit(
                        permissions=discord.Permissions(everyone_perms),
                        reason="🔄 Restore backup"
                    )
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error("Failed to restore @everyone permissions: %s", e)
                    stats["errors"] += 1

            # ترتيب الرولات (الهرمية) - بنفس الترتيب المحفوظ بالباكب
            await self._restore_role_order(guild, data.get("roles", []), role_id_map, stats)

            # 2. استعادة الكاتيقوريات
            existing_categories = {c.name: c for c in guild.categories}
            for cat_data in data.get("categories", []):
                try:
                    if cat_data["name"] in existing_categories:
                        continue
                    overwrites = self._build_overwrites(guild, role_id_map, cat_data["overwrites"])
                    await guild.create_category(
                        name=cat_data["name"],
                        overwrites=overwrites,
                        reason="🔄 Restore backup"
                    )
                    stats["categories"] += 1
                    await _bump_progress()
                    await asyncio.sleep(0.5)
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error("Failed to create category %s: %s", cat_data["name"], e)
                    stats["errors"] += 1

            # تحديث قائمة الكاتيقوريات
            existing_categories = {c.name: c for c in guild.categories}

            # 3. استعادة الرومات
            existing_channels = {c.name: c for c in guild.channels}
            for ch_data in data.get("channels", []):
                try:
                    if ch_data["name"] in existing_channels:
                        continue

                    category = existing_categories.get(ch_data.get("category"))
                    overwrites = self._build_overwrites(guild, role_id_map, ch_data["overwrites"])

                    if ch_data["type"] == "text":
                        await guild.create_text_channel(
                            name=ch_data["name"],
                            category=category,
                            topic=ch_data.get("topic") or None,
                            slowmode_delay=ch_data.get("slowmode", 0),
                            nsfw=ch_data.get("nsfw", False),
                            overwrites=overwrites,
                            reason="🔄 Restore backup"
                        )
                    elif ch_data["type"] == "voice":
                        await guild.create_voice_channel(
                            name=ch_data["name"],
                            category=category,
                            bitrate=min(ch_data.get("bitrate", 64000), guild.bitrate_limit),
                            user_limit=ch_data.get("user_limit", 0),
                            overwrites=overwrites,
                            reason="🔄 Restore backup"
                        )

                    stats["channels"] += 1
                    await _bump_progress()
                    await asyncio.sleep(0.5)
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error("Failed to create channel %s: %s", ch_data["name"], e)
                    stats["errors"] += 1

            # ترتيب الكاتيقوريات والرومات - بنفس الترتيب المحفوظ بالباكب
            await self._restore_channel_order(guild, data, stats)

        except Exception as e:
            logger.error("Restore failed: %s", e)
            await msg.edit(content=f"❌ فشلت الاستعادة: {e}")
            return
        finally:
            self._restore_lock = False

        saved_at = data.get("saved_at", "غير معروف")
        await msg.edit(content=(
            f"✅ تمت الاستعادة من نسخة `{saved_at[:10]}` (شامل الترتيب وصلاحيات @everyone)\n"
            f"**{stats['roles']}** رول | **{stats['categories']}** كاتيقوري | **{stats['channels']}** روم"
            + (f" | ⚠️ {stats['errors']} أخطاء" if stats["errors"] else "")
        ))

    # =====================================================
    # دالة مساعدة لبناء overwrites من الـ backup
    # =====================================================
    def _build_overwrites(self, guild, role_id_map: dict, raw_overwrites: dict) -> dict:
        overwrites = {}
        for key, data in raw_overwrites.items():
            old_id = data.get("id")
            name = data.get("name", key)
            target = None

            if data["type"] == "role":
                # الأولوية لمطابقة الرول عن طريق الـ ID المحفوظ وقت الباكب
                # (يشتغل حتى لو تغيّر اسم الرول لاحقاً). لو ما لقيناه، نرجع للاسم.
                target = role_id_map.get(old_id) or discord.utils.get(guild.roles, name=name)
            else:
                # الأعضاء عندهم نفس الـ ID دايماً في ديسكورد، فنجرب الـ ID
                # الحقيقي مباشرة (العضو لازم يكون لسه في السيرفر)، وبعدين الاسم كحل أخير.
                target = guild.get_member(old_id) or discord.utils.get(guild.members, name=name)

            if not target:
                continue

            overwrite = discord.PermissionOverwrite.from_pair(
                discord.Permissions(data["allow"]),
                discord.Permissions(data["deny"])
            )
            overwrites[target] = overwrite
        return overwrites

    # =====================================================
    # ترتيب الرولات (الهرمية) دفعة واحدة عبر edit_role_positions
    # =====================================================
    async def _restore_role_order(self, guild, roles_data: list, role_id_map: dict, stats: dict):
        bot_member = guild.me
        if not bot_member or not bot_member.top_role:
            return

        # ما نقدر نحط رول عند مستوى رول البوت الأعلى أو فوقه - ديسكورد هيرفض
        max_position = bot_member.top_role.position - 1
        if max_position < 1:
            logger.warning("Bot's top role is too low to reorder any roles.")
            return

        positions = {}
        pos = 1
        for role_data in roles_data:  # roles_data محفوظة بالترتيب الصحيح من الأسفل للأعلى
            role = role_id_map.get(role_data.get("id"))
            if not role or role.managed:
                continue
            if pos > max_position:
                logger.warning(
                    "Stopped restoring role order at '%s': above the bot's own top role.", role.name
                )
                break
            positions[role] = pos
            pos += 1

        if not positions:
            return

        try:
            await guild.edit_role_positions(positions=positions, reason="🔄 Restore backup - ترتيب الرولات")
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Failed to restore role order: %s", e)
            stats["errors"] += 1

    # =====================================================
    # ترتيب الكاتيقوريات والرومات دفعة واحدة عبر PATCH channels
    # =====================================================
    async def _restore_channel_order(self, guild, data: dict, stats: dict):
        category_map = {c.name: c for c in guild.categories}
        channel_map = {
            c.name: c for c in guild.channels if not isinstance(c, discord.CategoryChannel)
        }

        payload = []
        for i, cat_data in enumerate(data.get("categories", [])):
            category = category_map.get(cat_data["name"])
            if category:
                payload.append({"id": category.id, "position": i})

        # الرومات لازم ترتيبها يكون مستقل داخل كل كاتيقوري (وبرة أي كاتيقوري) على حدة
        grouped: dict = {}
        for ch_data in data.get("channels", []):
            grouped.setdefault(ch_data.get("category"), []).append(ch_data)

        for ch_list in grouped.values():
            for i, ch_data in enumerate(ch_list):
                channel = channel_map.get(ch_data["name"])
                if channel:
                    payload.append({"id": channel.id, "position": i})

        if not payload:
            return

        try:
            # نستخدم الـ HTTP endpoint مباشرة لأن discord.py ما يوفر دالة عامة
            # لتعديل ترتيب عدة رومات دفعة وحدة (PATCH /guilds/{id}/channels)
            await self.bot.http.bulk_channel_update(
                guild.id, payload, reason="🔄 Restore backup - ترتيب الرومات"
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Failed to restore channel order: %s", e)
            stats["errors"] += 1


async def setup(bot):
    await bot.add_cog(Backup(bot))