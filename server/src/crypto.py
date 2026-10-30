"""
    Encrypts users' API keys before they are stored.
    ENCRYPTION_KEY is a Fernet key: generate one with
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.getenv('ENCRYPTION_KEY')
    if not key:
        raise RuntimeError('ENCRYPTION_KEY is not set.')
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str | None) -> str:
    """ Return: the plaintext, or '' if nothing is stored or it can't be decrypted (for example after a key change). """
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ''


def hint(value: str) -> str:
    """ Last 4 characters, so users can tell which key is saved. """
    return f'••••{value[-4:]}' if value else ''
