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
                overwrites[target.name] = {
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
                overwrites[target.name] = {
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

        # إرسال الملف
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        file = discord.File(
            fp=__import__("io").BytesIO(json_bytes),
            filename=f"backup_{guild.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        await msg.delete()
        await ctx.send(
            f"✅ تم حفظ النسخة الاحتياطية | **{len(data['roles'])}** رول | **{len(data['categories'])}** كاتيقوري | **{len(data['channels'])}** روم",
            file=file
        )

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
        except Exception as e:
            await ctx.send(f"❌ فشل قراءة الملف: {e}", delete_after=10)
            return

        self._restore_lock = True
        msg = await ctx.send("⏳ جاري استعادة السيرفر...")
        guild = ctx.guild
        stats = {"roles": 0, "categories": 0, "channels": 0, "errors": 0}

        try:
            # 1. استعادة الرولات
            existing_roles = {r.name: r for r in guild.roles}
            for role_data in data.get("roles", []):
                try:
                    if role_data["name"] in existing_roles:
                        continue  # الرول موجود، تخطى
                    await guild.create_role(
                        name=role_data["name"],
                        color=discord.Color(role_data["color"]),
                        permissions=discord.Permissions(role_data["permissions"]),
                        hoist=role_data["hoist"],
                        mentionable=role_data["mentionable"],
                        reason="🔄 Restore backup"
                    )
                    stats["roles"] += 1
                    await asyncio.sleep(0.5)  # تجنب rate limit
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error("Failed to create role %s: %s", role_data["name"], e)
                    stats["errors"] += 1

            # تحديث قائمة الرولات بعد الإنشاء
            await guild.chunk()
            existing_roles = {r.name: r for r in guild.roles}

            # 2. استعادة الكاتيقوريات
            existing_categories = {c.name: c for c in guild.categories}
            for cat_data in data.get("categories", []):
                try:
                    if cat_data["name"] in existing_categories:
                        continue
                    overwrites = self._build_overwrites(guild, cat_data["overwrites"])
                    await guild.create_category(
                        name=cat_data["name"],
                        overwrites=overwrites,
                        reason="🔄 Restore backup"
                    )
                    stats["categories"] += 1
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
                    overwrites = self._build_overwrites(guild, ch_data["overwrites"])

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
                    await asyncio.sleep(0.5)
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error("Failed to create channel %s: %s", ch_data["name"], e)
                    stats["errors"] += 1

        except Exception as e:
            logger.error("Restore failed: %s", e)
            await msg.edit(content=f"❌ فشلت الاستعادة: {e}")
            return
        finally:
            self._restore_lock = False

        saved_at = data.get("saved_at", "غير معروف")
        await msg.edit(content=(
            f"✅ تمت الاستعادة من نسخة `{saved_at[:10]}`\n"
            f"**{stats['roles']}** رول | **{stats['categories']}** كاتيقوري | **{stats['channels']}** روم"
            + (f" | ⚠️ {stats['errors']} أخطاء" if stats["errors"] else "")
        ))

    # =====================================================
    # دالة مساعدة لبناء overwrites من الـ backup
    # =====================================================
    def _build_overwrites(self, guild, raw_overwrites: dict) -> dict:
        overwrites = {}
        for name, data in raw_overwrites.items():
            target = discord.utils.get(guild.roles, name=name)
            if not target and data["type"] == "member":
                target = discord.utils.get(guild.members, name=name)
            if not target:
                continue
            overwrite = discord.PermissionOverwrite.from_pair(
                discord.Permissions(data["allow"]),
                discord.Permissions(data["deny"])
            )
            overwrites[target] = overwrite
        return overwrites


async def setup(bot):
    await bot.add_cog(Backup(bot))
