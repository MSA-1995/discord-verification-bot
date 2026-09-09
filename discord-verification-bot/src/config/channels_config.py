"""
كل الـ IDs الخاصة بالرومات والكاتيقوريات بمكان واحد.
تقدر تتحكم فيها عبر Environment Variables، وإذا ما كانت موجودة يرجع للقيم الافتراضية تحت.
"""
import os


def _get_id(env_name: str, default: str) -> int:
    value = os.getenv(env_name, default)
    return int(value) if value and value.isdigit() else int(default)


LOG_CHANNEL_ID = _get_id("LOG_CHANNEL_ID", "1480613605144526868")
SINGLETON_CHANNEL_ID = _get_id("SINGLETON_CHANNEL_ID", "1547299546470678610")
AZKAR_CHANNEL_ID = _get_id("AZKAR_CHANNEL_ID", "1519388684569284701")
VERIFY_CATEGORY_ID = _get_id("VERIFY_CATEGORY_ID", "1480294823473709299")
WELCOME_CHANNEL_ID = _get_id("WELCOME_CHANNEL_ID", "1545884039897157652")
HONEYPOT_CHANNEL_ID = _get_id("HONEYPOT_CHANNEL_ID", "1522303725316603944")
GAME_CHANNEL_ID = _get_id("GAME_CHANNEL_ID", "1546548300608438354")
