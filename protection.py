import discord
from discord.ext import commands
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio

# إعدادات الحماية
SPAM_THRESHOLD = 5
SPAM_TIMEFRAME = 10
MUTE_DURATION = 30

class Protection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_messages = defaultdict(list)

    async def send_security_log(self, guild, embed):
        """إرسال لوق حماية (نسخة مبسطة داخلية لتجنب التعقيد)"""
        log_channel = discord.utils.get(guild.text_channels, name="📋・logs")
        if log_channel:
            await log_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        
        if message.author.guild_permissions.administrator:
            return
            
        member = message.author

        # 1. فحص الروابط
        if any(word in message.content.lower() for word in ['http://', 'https://', 'discord.gg/', '.com', '.net', '.org']):
            try:
                await message.delete()
                await member.timeout(timedelta(minutes=MUTE_DURATION), reason="🚫 Posted links")
                await message.channel.send(
                    f"⚠️ {member.mention} has been muted for {MUTE_DURATION} minutes for posting links!",
                    delete_after=10
                )
                
                embed = discord.Embed(title="لوق الحماية - ميوت روابط", color=0xff6600, timestamp=datetime.now())
                embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
                embed.add_field(name="المحتوى", value=message.content[:1024], inline=False)
                embed.add_field(name="المدة", value=f"{MUTE_DURATION} دقيقة", inline=True)
                embed.set_thumbnail(url=message.guild.icon.url if message.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_security_log(message.guild, embed)
            except:
                pass
            return

        # 2. فحص السبام
        now = datetime.now()
        self.user_messages[member.id].append(now)
        self.user_messages[member.id] = [t for t in self.user_messages[member.id] 
                                         if (now - t).seconds < SPAM_TIMEFRAME]
        
        if len(self.user_messages[member.id]) >= SPAM_THRESHOLD:
            try:
                await member.timeout(timedelta(minutes=MUTE_DURATION), reason="🚫 Spamming")
                await message.channel.send(
                    f"⚠️ {member.mention} has been muted for {MUTE_DURATION} minutes for spamming!",
                    delete_after=10
                )
                
                embed = discord.Embed(title="لوق الحماية - ميوت سبام", color=0xff6600, timestamp=datetime.now())
                embed.add_field(name="العضو", value=f"{member.mention} ({member.id})", inline=False)
                embed.add_field(name="السبب", value=f"إرسال {SPAM_THRESHOLD} رسائل في {SPAM_TIMEFRAME} ثواني", inline=False)
                embed.add_field(name="المدة", value=f"{MUTE_DURATION} دقيقة", inline=True)
                embed.set_thumbnail(url=message.guild.icon.url if message.guild.icon else None)
                embed.set_footer(text="نظام الحماية • MSA")
                await self.send_security_log(message.guild, embed)
                
                self.user_messages[member.id].clear()
            except:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """منع البوتات غير المصرح بها"""
        if not member.bot:
            return
            
        await asyncio.sleep(1)
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
            if entry.target.id == member.id:
                # لو المالك أضافه = سماح
                if entry.user.id == member.guild.owner_id:
                    print(f"✅ Owner added bot: {member.name}")
                    return
                # لو غير المالك = طرد
                else:
                    try:
                        await member.kick(reason="🚫 Only owner can add bots")
                        
                        embed = discord.Embed(title="لوق الحماية - طرد بوت", color=0xff0000, timestamp=datetime.now())
                        embed.add_field(name="البوت", value=f"{member.name} ({member.id})", inline=False)
                        embed.add_field(name="من أضافه", value=f"{entry.user.mention} ({entry.user.id})", inline=False)
                        embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
                        embed.set_footer(text="نظام الحماية • MSA")
                        await self.send_security_log(member.guild, embed)
                    except:
                        pass
                break

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """حماية من إنشاء رومات غير مصرح بها"""
        await asyncio.sleep(1)
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
            if entry.target.id == channel.id:
                creator = entry.user
                
                # تخطي البوت نفسه
                if creator.id == self.bot.user.id:
                    return

                # إرسال لوق (سيتم التعامل معه في Logging Cog، هنا فقط الحماية)
                
                # لو مو Admin ومو البوت
                if not creator.guild_permissions.administrator and not creator.bot:
                    try:
                        await channel.delete(reason="🚫 Unauthorized channel creation")
                        await creator.ban(reason="🚫 Unauthorized channel creation")
                        
                        embed = discord.Embed(title="لوق الحماية - باند", color=0xff0000, timestamp=datetime.now())
                        embed.add_field(name="الشخص", value=f"{creator.mention} ({creator.id})", inline=False)
                        embed.add_field(name="السبب", value="إنشاء روم غير مصرح به", inline=False)
                        embed.set_thumbnail(url=channel.guild.icon.url if channel.guild.icon else None)
                        embed.set_footer(text="نظام الحماية • MSA")
                        await self.send_security_log(channel.guild, embed)
                    except:
                        pass
                break

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        """حماية من إنشاء رتب غير مصرح بها"""
        await asyncio.sleep(1)
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
            if entry.target.id == role.id:
                creator = entry.user
                
                if creator.id == self.bot.user.id:
                    return
                
                if not creator.guild_permissions.administrator:
                    try:
                        await role.delete(reason="🚫 Unauthorized role creation")
                        member = role.guild.get_member(creator.id)
                        if member:
                            await member.ban(reason="🚫 Unauthorized role creation")
                            
                            embed = discord.Embed(title="لوق الحماية - باند", color=0xff0000, timestamp=datetime.now())
                            embed.add_field(name="الشخص", value=f"{creator.mention} ({creator.id})", inline=False)
                            embed.add_field(name="السبب", value="إنشاء رول غير مصرح به", inline=False)
                            embed.set_thumbnail(url=role.guild.icon.url if role.guild.icon else None)
                            embed.set_footer(text="نظام الحماية • MSA")
                            await self.send_security_log(role.guild, embed)
                    except:
                        pass
                break

async def setup(bot):
    await bot.add_cog(Protection(bot))
