import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from werkzeug.security import check_password_hash, generate_password_hash

PBKDF2_ITERATIONS = 390_000


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def generate_salt() -> bytes:
    return os.urandom(16)


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def encrypt_str(value: str, password: str, salt: bytes) -> str:
    key = _derive_key(password, salt)
    token = Fernet(key).encrypt(value.encode("utf-8"))
    return base64.urlsafe_b64encode(token).decode("utf-8")


def decrypt_str(encrypted: str, password: str, salt: bytes) -> str:
    """Raises InvalidToken if the password is wrong / data was tampered with."""
    key = _derive_key(password, salt)
    token = base64.urlsafe_b64decode(encrypted.encode("utf-8"))
    return Fernet(key).decrypt(token).decode("utf-8")


# Kept as thin aliases -- every secret (API key, relay token, agent secret)
# uses the same password-derived encryption, just under a clearer name per call site.
encrypt_api_key = encrypt_str
decrypt_api_key = decrypt_str
