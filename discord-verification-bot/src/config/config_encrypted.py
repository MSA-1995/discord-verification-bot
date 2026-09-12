"""
🔐 Encrypted Configuration
المفاتيح المشفرة لبوت التوثيق والحماية
"""

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64
import logging
import os

logger = logging.getLogger(__name__)

# ملاحظة: هذا الـ salt ثابت ومجرد قيمة عشوائية لاشتقاق المفتاح (KDF) —
# لا علاقة له بأي بوت أو خدمة خارجية. تم تثبيته باسم عام لأن ENCRYPTED_CRITICAL_WEBHOOK
# أعلاه مُشفّر باستخدام هذه القيمة بالذات؛ لو غيّرتها لازم تعيد تشفير الـ webhook من جديد
# (شغّل Fernet.generate_key() + نفس الـ KDF بالقيمة الجديدة، وشفّر الرابط من جديد).
_WEBHOOK_KDF_SALT = b"binance_bot_salt_2026"

# Token مشفر
ENCRYPTED_TOKEN = "gAAAAABqfysAfwbggvXaHn23KSt8JRLmbp46CnYTUETrzOr80jyd8xsi70uNE6yT5YBeSKDshiemR_3hh_nobfqLkvfO6MQ859W6jne-z0Vn1GRP81V21lV62mverxEUIc46NlVeeCBcuFqJRCARfpOmsWlFDqeNRr5NVn5If-QqOWGGvnSpNsY="

# Critical Webhook مشفر
ENCRYPTED_CRITICAL_WEBHOOK = "gAAAAABpuay0FYK_AXFBy_trEWffy5Ho8xzGr4-zSrASVWnVqipfKR3_k6C9VsucFp1qPEzcHaXDb8txhiVUkFrXFKTD9XIguwTnCZcpj6FqnGTKi7-jaCDb3eHEdeNiZcmKpax4ma_WNrlRHLJDTVDSuWvtff41bmMLyohJ3_ezK3Ox0-8iHeVDnutL1oyU7sMHwWfWY4f12xvc--03MTYqu42u_0IfNbEvyCt2LGvDNlVIJcCkQeg="

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

def get_critical_webhook():
    """فك تشفير Critical Webhook"""
    try:
        _KEY = _get_encryption_key()
        if not _KEY:
            return None
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_WEBHOOK_KDF_SALT,
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(_KEY.encode()))
        fernet = Fernet(key)
        webhook = fernet.decrypt(ENCRYPTED_CRITICAL_WEBHOOK.encode()).decode()
        return webhook
    except Exception as e:
        logger.error("Critical webhook decryption failed: %s", e)
        return None

def get_hadith_api_key():
    """قراءة مفتاح Hadith API من Environment Variables"""
    return os.getenv("HADITH_API_KEY") or os.getenv("SUNNAH_API_KEY")

def get_sunnah_api_key():
    """توافق قديم: استخدم get_hadith_api_key بدلاً منها"""
    return get_hadith_api_key()
