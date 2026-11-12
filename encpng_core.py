"""
AES-256-GCM encryption core for PNG files.

File layout (all integers big-endian):

    offset  size  field
    0       6     magic  b"ENCPNG"
    6       1     format version (1)
    7       1     kdf id (1 = PBKDF2-HMAC-SHA256)
    8       4     kdf iterations
    12      16    salt
    28      12    nonce (GCM IV)
    40      ...   ciphertext || 16-byte GCM tag

The 40-byte header is authenticated as AAD, so any tampering with
salt / nonce / iterations / version is detected on decrypt.
"""

import hashlib
import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"ENCPNG"
VERSION = 1
KDF_PBKDF2_SHA256 = 1
DEFAULT_ITERATIONS = 200_000
SALT_LEN = 16
NONCE_LEN = 12
HEADER_FMT = ">6sBBI16s12s"
HEADER_LEN = struct.calcsize(HEADER_FMT)  # 40
ENC_EXT = ".png.enc"  # legacy default
ENC_EXTS = (".png.enc", ".jpg.enc", ".jpeg.enc", ".webp.enc")
FORMATS = {  # name -> (encrypted extension, plain extension, mime)
    "png": (".png.enc", ".png", "image/png"),
    "jpeg": (".jpg.enc", ".jpg", "image/jpeg"),
    "webp": (".webp.enc", ".webp", "image/webp"),
}
ENV_PASSWORD = "ENCPNG_PASSWORD"


class DecryptError(Exception):
    pass


def resolve_password(password):
    """Use the given password, or fall back to the ENCPNG_PASSWORD env var."""
    pw = password if password else os.environ.get(ENV_PASSWORD, "")
    if not pw:
        raise ValueError(
            f"No password given. Fill the password field or set the {ENV_PASSWORD} environment variable."
        )
    return pw


def derive_key(password, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)


def encrypt_bytes(data, password, iterations=DEFAULT_ITERATIONS):
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    header = struct.pack(HEADER_FMT, MAGIC, VERSION, KDF_PBKDF2_SHA256, iterations, salt, nonce)
    key = derive_key(password, salt, iterations)
    return header + AESGCM(key).encrypt(nonce, data, header)


def is_encrypted(blob):
    return len(blob) >= HEADER_LEN and blob[:6] == MAGIC


def decrypt_bytes(blob, password):
    if not is_encrypted(blob):
        raise DecryptError("Not an ENCPNG file (bad magic).")
    magic, version, kdf, iterations, salt, nonce = struct.unpack(HEADER_FMT, blob[:HEADER_LEN])
    if version != VERSION:
        raise DecryptError(f"Unsupported format version {version}.")
    if kdf != KDF_PBKDF2_SHA256:
        raise DecryptError(f"Unsupported KDF id {kdf}.")
    key = derive_key(password, salt, iterations)
    try:
        return AESGCM(key).decrypt(nonce, blob[HEADER_LEN:], blob[:HEADER_LEN])
    except InvalidTag:
        raise DecryptError("Decryption failed: wrong password or the file is corrupted.")


def detect_format(data):
    """Detect the real image format of decrypted bytes: 'png', 'jpeg', 'webp' or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def is_enc_name(name):
    return name.lower().endswith(ENC_EXTS)


def encrypt_file(src, dst, password, iterations=DEFAULT_ITERATIONS):
    with open(src, "rb") as f:
        data = f.read()
    with open(dst, "wb") as f:
        f.write(encrypt_bytes(data, password, iterations))


def decrypt_file(src, password):
    with open(src, "rb") as f:
        return decrypt_bytes(f.read(), password)
