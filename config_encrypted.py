"""
🔐 Encrypted Configuration
المفاتيح المشفرة لبوت التوثيق والحماية
"""

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64
import os

# Token مشفر
ENCRYPTED_TOKEN = "gAAAAABpt0pwARYQJjyO2mIymdSfQ0Oe8qRc_gegZW-pAZg48K-8ThUcROy1HcznX2ILFJmiP2X8PKUfGfLYuLdVDowKJ8J4FtbBN6vvWVirgXuPG55yEYixslc2EzIvQ-Z2cfjZ7LGierGE142AQVaDCA_YRY8thcpfg8zZAm0E50i4IKcjMM0="

# Critical Webhook مشفر
ENCRYPTED_CRITICAL_WEBHOOK = "gAAAAABpuay0FYK_AXFBy_trEWffy5Ho8xzGr4-zSrASVWnVqipfKR3_k6C9VsucFp1qPEzcHaXDb8txhiVUkFrXFKTD9XIguwTnCZcpj6FqnGTKi7-jaCDb3eHEdeNiZcmKpax4ma_WNrlRHLJDTVDSuWvtff41bmMLyohJ3_ezK3Ox0-8iHeVDnutL1oyU7sMHwWfWY4f12xvc--03MTYqu42u_0IfNbEvyCt2LGvDNlVIJcCkQeg="

# المفتاح (من Environment Variable)
ENCRYPTION_KEY = "sBxWnLSyyCY9ib9Yo100AR4Se6kC9sAXcDfqHox9kKc="

def get_discord_token():
    """فك تشفير Discord Token"""
    try:
        # حاول قراءة المفتاح من متغيرات البيئة أولاً، وإلا استخدم المفتاح الثابت
        _KEY = os.getenv('ENCRYPTION_KEY', ENCRYPTION_KEY)
        cipher = Fernet(_KEY.encode())
        decrypted = cipher.decrypt(ENCRYPTED_TOKEN.encode())
        return decrypted.decode()
    except Exception as e:
        print(f"❌ Token decryption error: {e}")
        return None

def get_critical_webhook():
    """فك تشفير Critical Webhook"""
    try:
        # استخدام نفس طريقة فك التشفير البسيطة للتوكن
        _KEY = os.getenv('ENCRYPTION_KEY', ENCRYPTION_KEY)
        cipher = Fernet(_KEY.encode())
        webhook = cipher.decrypt(ENCRYPTED_CRITICAL_WEBHOOK.encode()).decode()
        return webhook
    except Exception as e:
        print(f"❌ Critical webhook decryption error: {e}")
        return None
