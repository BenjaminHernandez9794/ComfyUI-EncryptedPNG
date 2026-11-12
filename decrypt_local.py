#!/usr/bin/env python3
"""
Standalone local decryptor for ComfyUI-EncryptedPNG files (*.png.enc / *.jpg.enc / *.webp.enc).
The real image format is detected from the decrypted bytes.

Only needs:  pip install cryptography

Usage:
    python decrypt_local.py image.png.enc                 # -> image.png next to it
    python decrypt_local.py ./output/encrypted -o ./plain  # a whole folder (recursive)
    python decrypt_local.py a.png.enc b.png.enc -p secret
    ENCPNG_PASSWORD=secret python decrypt_local.py ./output

If no password is given (-p or ENCPNG_PASSWORD), you are prompted for it;
pressing Enter uses the nodes' default password 147258.
"""

import argparse
import getpass
import hashlib
import os
import struct
import sys

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    sys.exit("Missing dependency: pip install cryptography")

MAGIC = b"ENCPNG"
HEADER_FMT = ">6sBBI16s12s"
HEADER_LEN = struct.calcsize(HEADER_FMT)  # 40
DEFAULT_PASSWORD = "147258"  # same default as the ComfyUI nodes
ENC_EXTS = (".png.enc", ".jpg.enc", ".jpeg.enc", ".webp.enc")


def detect_ext(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def decrypt_bytes(blob, password):
    if len(blob) < HEADER_LEN or blob[:6] != MAGIC:
        raise ValueError("not an ENCPNG file")
    _magic, version, kdf, iterations, salt, nonce = struct.unpack(HEADER_FMT, blob[:HEADER_LEN])
    if version != 1 or kdf != 1:
        raise ValueError(f"unsupported format (version={version}, kdf={kdf})")
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    try:
        return AESGCM(key).decrypt(nonce, blob[HEADER_LEN:], blob[:HEADER_LEN])
    except InvalidTag:
        raise ValueError("wrong password or corrupted file")


def collect(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, _d, files in os.walk(p):
                for fn in sorted(files):
                    if fn.lower().endswith(ENC_EXTS):
                        yield os.path.join(root, fn), p
        else:
            yield p, None


def out_path(src, base, out_dir, ext):
    name = os.path.basename(src)
    if name.lower().endswith(".enc"):
        name = name[:-4]
    stem, old = os.path.splitext(name)
    if old.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        name = stem
    name += ext
    if not out_dir:
        return os.path.join(os.path.dirname(src), name)
    rel_dir = os.path.relpath(os.path.dirname(src), base) if base else ""
    return os.path.normpath(os.path.join(out_dir, rel_dir, name))


def main():
    ap = argparse.ArgumentParser(description="Decrypt ComfyUI-EncryptedPNG *.png.enc / *.jpg.enc / *.webp.enc files.")
    ap.add_argument("inputs", nargs="+", help="files or folders")
    ap.add_argument("-p", "--password", help="password (default: $ENCPNG_PASSWORD or prompt)")
    ap.add_argument("-o", "--out", help="output folder (default: next to each input)")
    ap.add_argument("-f", "--force", action="store_true", help="overwrite existing output files")
    a = ap.parse_args()

    pw = a.password or os.environ.get("ENCPNG_PASSWORD") or getpass.getpass(
        f"Password (Enter = default {DEFAULT_PASSWORD}): ") or DEFAULT_PASSWORD
    ok = fail = 0
    for src, base in collect(a.inputs):
        try:
            with open(src, "rb") as f:
                png = decrypt_bytes(f.read(), pw)
            dst = out_path(src, base, a.out, detect_ext(png))
            if os.path.exists(dst) and not a.force:
                print(f"skip (exists): {dst}")
                continue
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            with open(dst, "wb") as f:
                f.write(png)
            print(f"ok   {src} -> {dst}")
            ok += 1
        except Exception as e:
            print(f"FAIL {src}: {e}", file=sys.stderr)
            fail += 1
    print(f"\n{ok} decrypted, {fail} failed")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
