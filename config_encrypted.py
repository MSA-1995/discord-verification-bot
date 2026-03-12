"""
🔐 Encrypted Configuration
المفاتيح المشفرة لبوت التوثيق والحماية
"""

from cryptography.fernet import Fernet
import os

# Token مشفر
ENCRYPTED_TOKEN = "gAAAAABpswGLHSH0zCMeBEdV7zo4x0lW8FWSJJ17n5SlnvK6c1HDjV4Ejnj-JOr9AZu2ZJf-tmFuOlgJbs8muY6Bm5msLHIFhVQ_srBKWVaIlyzXvkjNMjtXcuRTdn7FWOPxCQoOnoPcplqthHGP8MTjHDSybeINAIaEbzdr0FA9HeF6dqnIMc8="

# المفتاح (من Environment Variable)
ENCRYPTION_KEY = "sBxWnLSyyCY9ib9Yo100AR4Se6kC9sAXcDfqHox9kKc="

def get_discord_token():
    """فك تشفير Discord Token"""
    try:
        cipher = Fernet(ENCRYPTION_KEY.encode())
        decrypted = cipher.decrypt(ENCRYPTED_TOKEN.encode())
        return decrypted.decode()
    except Exception as e:
        print(f"❌ Decryption error: {e}")
        return None
