"""
🔐 Configuration
إعدادات البوت - جميع القيم الحساسة من Environment Variables فقط
"""

import logging
import os

logger = logging.getLogger(__name__)


def get_discord_token():
    """قراءة Discord Token من Environment Variables"""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN is missing. Add it in your environment variables on Koyeb.")
    return token


def get_hadith_api_key():
    """قراءة مفتاح Hadith API من Environment Variables"""
    return os.getenv("HADITH_API_KEY") or os.getenv("SUNNAH_API_KEY")


def get_sunnah_api_key():
    """توافق قديم: استخدم get_hadith_api_key بدلاً منها"""
    return get_hadith_api_key()
