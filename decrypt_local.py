#!/usr/bin/env python3
"""
Standalone local decryptor for ComfyUI-EncryptedPNG files (*.png.enc).

Only needs:  pip install cryptography

Usage:
    python decrypt_local.py image.png.enc                 # -> image.png next to it
    python decrypt_local.py ./output/encrypted -o ./plain  # a whole folder (recursive)
    python decrypt_local.py a.png.enc b.png.enc -p secret
    ENCPNG_PASSWORD=secret python decrypt_local.py ./output

If no password is given (-p or ENCPNG_PASSWORD), you are prompted for it.
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
ENC_EXT = ".png.enc"


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
                    if fn.lower().endswith(ENC_EXT):
                        yield os.path.join(root, fn), p
        else:
            yield p, None


def out_path(src, base, out_dir):
    name = os.path.basename(src)
    name = name[: -len(ENC_EXT)] + ".png" if name.lower().endswith(ENC_EXT) else name + ".png"
    if not out_dir:
        return os.path.join(os.path.dirname(src), name)
    rel_dir = os.path.relpath(os.path.dirname(src), base) if base else ""
    return os.path.normpath(os.path.join(out_dir, rel_dir, name))


def main():
    ap = argparse.ArgumentParser(description="Decrypt ComfyUI-EncryptedPNG *.png.enc files.")
    ap.add_argument("inputs", nargs="+", help="files or folders")
    ap.add_argument("-p", "--password", help="password (default: $ENCPNG_PASSWORD or prompt)")
    ap.add_argument("-o", "--out", help="output folder (default: next to each input)")
    ap.add_argument("-f", "--force", action="store_true", help="overwrite existing .png files")
    a = ap.parse_args()

    pw = a.password or os.environ.get("ENCPNG_PASSWORD") or getpass.getpass("Password: ")
    ok = fail = 0
    for src, base in collect(a.inputs):
        dst = out_path(src, base, a.out)
        try:
            if os.path.exists(dst) and not a.force:
                print(f"skip (exists): {dst}")
                continue
            with open(src, "rb") as f:
                png = decrypt_bytes(f.read(), pw)
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
