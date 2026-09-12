"""
🔐 Encrypted Configuration
المفاتيح المشفرة لبوت التوثيق والحماية
"""

from cryptography.fernet import Fernet
import logging
import os

logger = logging.getLogger(__name__)

# Token مشفر
ENCRYPTED_TOKEN = "gAAAAABqfysAfwbggvXaHn23KSt8JRLmbp46CnYTUETrzOr80jyd8xsi70uNE6yT5YBeSKDshiemR_3hh_nobfqLkvfO6MQ859W6jne-z0Vn1GRP81V21lV62mverxEUIc46NlVeeCBcuFqJRCARfpOmsWlFDqeNRr5NVn5If-QqOWGGvnSpNsY="

# المفتاح (من Environment Variable)
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

def _get_encryption_key():
    if not ENCRYPTION_KEY:
        logger.error("ENCRYPTION_KEY is missing. Add it in your environment variables.")
        return None
    return ENCRYPTION_KEY

def get_discord_token():
    """فك تشفير Discord Token"""
    try:
        key = _get_encryption_key()
        if not key:
            return None
        cipher = Fernet(key.encode())
        decrypted = cipher.decrypt(ENCRYPTED_TOKEN.encode())
        return decrypted.decode()
    except Exception as e:
        logger.error("Discord token decryption failed: %s", e)
        return None

def get_hadith_api_key():
    """قراءة مفتاح Hadith API من Environment Variables"""
    return os.getenv("HADITH_API_KEY") or os.getenv("SUNNAH_API_KEY")

def get_sunnah_api_key():
    """توافق قديم: استخدم get_hadith_api_key بدلاً منها"""
    return get_hadith_api_key()
