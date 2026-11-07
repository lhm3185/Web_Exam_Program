from hashlib import sha256
from hmac import digest
from secrets import token_bytes

from django.conf import settings


def access_code_digest(code):
    return sha256(code.strip().lower().encode("utf-8")).hexdigest()


def access_code_key():
    key = (settings.BASE_DIR / ".access_code_key").read_bytes()
    if len(key) != 32:
        raise ValueError("Invalid access code key.")
    return key


def create_access_code_key():
    path = settings.BASE_DIR / ".access_code_key"
    try:
        with path.open("xb") as key_file:
            key_file.write(token_bytes(32))
    except FileExistsError:
        pass
    return access_code_key()


def derive_access_code(seed, key):
    return digest(key, seed.encode("ascii"), "sha256").hex()[:24]
