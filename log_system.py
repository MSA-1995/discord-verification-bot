import discord
from discord.ext import commands
from datetime import datetime
import asyncio

class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.deleted_messages = {}
        self.bulk_delete_active = False
        self.processed_events = {}

    async def send_log(self, guild, embed):
        """إرسال لوق للروم المخصص"""
        log_channel = discord.utils.get(guild.text_channels, name="📋・logs")
        if log_channel:
            await log_channel.send(embed=embed)

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

    # ========== Events ==========

    @commands.Cog.listener()
    async def on_member_join(self, member):
        event_key = f"member_join_{member.id}_{member.guild.id}"
        current_time = datetime.now().timestamp()
        
        if event_key in self.processed_events:
            if current_time - self.processed_events[event_key] < 5:
                return
        self.processed_events[event_key] = current_time

        embed = discord.Embed(title="دخول السيرفر", color=0x00ff00, timestamp=datetime.now())
        embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
        embed.add_field(name="تاريخ إنشاء الحساب", value=member.created_at.strftime("%Y-%m-%d %H:%M"), inline=True)
        embed.add_field(name="عدد الأعضاء", value=member.guild.member_count, inline=True)
        embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
        embed.set_footer(text="نظام الحماية • MSA")
        await self.send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await asyncio.sleep(1)
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
            if entry.target.id == channel.id:
                embed = discord.Embed(title="إنشاء روم", color=0x00ff00, timestamp=datetime.now())
                embed.add_field(name="الشخص", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                embed.add_field(name="اسم الروم", value=channel.name, inline=True)
                embed.add_field(name="ID الروم", value=channel.id, inline=True)
                embed.set_thumbnail(url=channel.guild.icon.url if channel.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_log(channel.guild, embed)
                break

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await asyncio.sleep(1)
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
            if entry.target.id == role.id:
                embed = discord.Embed(title="إنشاء رول", color=0x00ff00, timestamp=datetime.now())
                embed.add_field(name="الشخص", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                embed.add_field(name="اسم الرول", value=role.name, inline=True)
                embed.add_field(name="ID الرول", value=role.id, inline=True)
                embed.set_thumbnail(url=role.guild.icon.url if role.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_log(role.guild, embed)
                break

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await asyncio.sleep(1)
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            if entry.target.id == channel.id:
                embed = discord.Embed(title="حذف روم", color=0xff0000, timestamp=datetime.now())
                embed.add_field(name="الشخص", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                embed.add_field(name="اسم الروم", value=channel.name, inline=True)
                embed.add_field(name="ID الروم", value=channel.id, inline=True)
                embed.set_thumbnail(url=channel.guild.icon.url if channel.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_log(channel.guild, embed)
                break

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await asyncio.sleep(1)
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                embed = discord.Embed(title="باند عضو", color=0xff0000, timestamp=datetime.now())
                embed.add_field(name="المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                embed.add_field(name="العضو", value=f"{user.mention} ({user.id})", inline=False)
                embed.add_field(name="السبب", value=entry.reason or "لا يوجد", inline=False)
                embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_log(guild, embed)
                break

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await asyncio.sleep(1)
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
            if entry.target.id == user.id:
                embed = discord.Embed(title="فك باند", color=0x00ff00, timestamp=datetime.now())
                embed.add_field(name="المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                embed.add_field(name="العضو", value=f"{user.name} ({user.id})", inline=False)
                embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_log(guild, embed)
                break

    @commands.Cog.listener()
    async def on_member_kick(self, member):
        await asyncio.sleep(1)
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                embed = discord.Embed(title="طرد عضو", color=0xff0000, timestamp=datetime.now())
                embed.add_field(name="المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
                embed.add_field(name="السبب", value=entry.reason or "لا يوجد", inline=False)
                embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_log(member.guild, embed)
                break

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or self.bulk_delete_active:
            return
        
        message_id = f"{message.id}_{message.channel.id}"
        current_time = datetime.now().timestamp()
        
        if message_id in self.deleted_messages:
            if current_time - self.deleted_messages[message_id] < 5:
                return
        
        self.deleted_messages[message_id] = current_time
        
        # تنظيف الذاكرة
        if len(self.deleted_messages) > 100:
            self.deleted_messages = {k:v for k,v in list(self.deleted_messages.items())[-50:]}
        
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
            await asyncio.sleep(1)
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
                embed = discord.Embed(title="إعطاء رول", color=0x00ff00, timestamp=datetime.now())
                embed.add_field(name="المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                embed.add_field(name="العضو", value=f"{after.mention} ({after.id})", inline=False)
                embed.add_field(name="الرول", value=new_role.mention, inline=True)
                embed.set_thumbnail(url=after.guild.icon.url if after.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_log(after.guild, embed)
                break
        
        # سحب رول
        if len(before.roles) > len(after.roles):
            removed_role = list(set(before.roles) - set(after.roles))[0]
            await asyncio.sleep(1)
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
                embed = discord.Embed(title="سحب رول", color=0xff0000, timestamp=datetime.now())
                embed.add_field(name="المسؤول", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                embed.add_field(name="العضو", value=f"{after.mention} ({after.id})", inline=False)
                embed.add_field(name="الرول", value=removed_role.name, inline=True)
                embed.set_thumbnail(url=after.guild.icon.url if after.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_log(after.guild, embed)
                break

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # دخول روم صوتي
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(title="دخول روم صوتي", color=0x00ff00, timestamp=datetime.now())
            embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
            embed.add_field(name="الروم", value=after.channel.name, inline=True)
            embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(member.guild, embed)
        
        # خروج من روم صوتي
        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(title="خروج من روم صوتي", color=0xff0000, timestamp=datetime.now())
            embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
            embed.add_field(name="الروم", value=before.channel.name, inline=True)
            embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(member.guild, embed)
        
        # تنقل
        elif before.channel != after.channel and before.channel is not None and after.channel is not None:
            embed = discord.Embed(title="تنقل بين رومات صوتية", color=0xffff00, timestamp=datetime.now())
            embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
            embed.add_field(name="من", value=before.channel.name, inline=True)
            embed.add_field(name="إلى", value=after.channel.name, inline=True)
            embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            embed.set_footer(text="نظام الحماية • MSA")
            await self.send_log(member.guild, embed)

async def setup(bot):
    await bot.add_cog(Logging(bot))
