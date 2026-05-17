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
ENCRYPTED_TOKEN = "gAAAAABp9msbvqZM_lQuDm0nNgPQTwoW7pti1aCs6pRn10Y1kRrU68ozQFn4mf3YwFTMRWmiiAzGaTMhSsWp6Ngiu4MatRvF_xKwBXfQTTrn5dX4s_UmCQXkcsC3NbKNGUhOirrVVL35phmSeFpOq7VZ7QphiLF9CEOQ-DxbQSueOB8lhz4wTfA="

# Critical Webhook مشفر
ENCRYPTED_CRITICAL_WEBHOOK = "gAAAAABpuay0FYK_AXFBy_trEWffy5Ho8xzGr4-zSrASVWnVqipfKR3_k6C9VsucFp1qPEzcHaXDb8txhiVUkFrXFKTD9XIguwTnCZcpj6FqnGTKi7-jaCDb3eHEdeNiZcmKpax4ma_WNrlRHLJDTVDSuWvtff41bmMLyohJ3_ezK3Ox0-8iHeVDnutL1oyU7sMHwWfWY4f12xvc--03MTYqu42u_0IfNbEvyCt2LGvDNlVIJcCkQeg="

# المفتاح (من Environment Variable)
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

def get_discord_token():
    """فك تشفير Discord Token"""
    try:
        cipher = Fernet(ENCRYPTION_KEY.encode())
        decrypted = cipher.decrypt(ENCRYPTED_TOKEN.encode())
        return decrypted.decode()
    except Exception as e:
        print(f"❌ Decryption error: {e}")
        return None

def get_critical_webhook():
    """فك تشفير Critical Webhook"""
    try:
        _KEY = os.getenv('ENCRYPTION_KEY', ENCRYPTION_KEY)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'binance_bot_salt_2026',
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(_KEY.encode()))
        fernet = Fernet(key)
        webhook = fernet.decrypt(ENCRYPTED_CRITICAL_WEBHOOK.encode()).decode()
        return webhook
    except:
        return None
