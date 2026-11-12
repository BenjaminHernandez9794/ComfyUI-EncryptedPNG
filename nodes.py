import hashlib
import io
import json
import os

import numpy as np
import torch
from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo

import folder_paths

from .encpng_core import (
    DEFAULT_ITERATIONS,
    DEFAULT_PASSWORD,
    FORMATS,
    DecryptError,
    decrypt_bytes,
    detect_format,
    encrypt_bytes,
    is_enc_name,
    resolve_password,
)

try:
    from comfy.cli_args import args as _comfy_args
except Exception:  # pragma: no cover
    _comfy_args = None


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _scan(root, tag):
    out = []
    if not root or not os.path.isdir(root):
        return out
    for dirpath, _dirs, files in os.walk(root, followlinks=True):
        for fn in files:
            if is_enc_name(fn):
                rel = os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")
                out.append(f"{rel} [{tag}]")
    return out


def list_encrypted_files():
    """All encrypted image files (*.png.enc / *.jpg.enc / *.webp.enc) under ComfyUI's output/ and input/ dirs, newest first."""
    items = _scan(folder_paths.get_output_directory(), "output") + _scan(
        folder_paths.get_input_directory(), "input"
    )

    def mtime(name):
        try:
            return os.path.getmtime(folder_paths.get_annotated_filepath(name))
        except OSError:
            return 0

    items.sort(key=mtime, reverse=True)
    return items


def resolve_enc_path(name):
    path = folder_paths.get_annotated_filepath(name)
    # keep reads inside the ComfyUI input/output/temp directories
    roots = [
        os.path.abspath(folder_paths.get_output_directory()),
        os.path.abspath(folder_paths.get_input_directory()),
        os.path.abspath(folder_paths.get_temp_directory()),
    ]
    ap = os.path.abspath(path)
    if not any(os.path.commonpath([ap, r]) == r for r in roots):
        raise ValueError("Path is outside ComfyUI input/output directories.")
    return ap


def decrypt_named_file(name, password):
    path = resolve_enc_path(name)
    with open(path, "rb") as f:
        return decrypt_bytes(f.read(), resolve_password(password))


def _read_metadata(img):
    """PNG text chunks, or ComfyUI-style EXIF tags (Workflow:/Prompt:) for JPEG/WebP."""
    meta = {k: v for k, v in img.info.items() if isinstance(v, str)}
    try:
        exif = img.getexif()
        for tag in (0x010E, 0x010F, 0x9286):
            v = exif.get(tag)
            if isinstance(v, bytes):
                v = v.decode("utf-8", "ignore")
            if isinstance(v, str) and ":" in v:
                k, val = v.split(":", 1)
                meta.setdefault(k.strip().lower(), val)
    except Exception:
        pass
    return meta


def _pil_to_tensors(img):
    img = ImageOps.exif_transpose(img)
    if img.mode == "I":
        img = img.point(lambda i: i * (1 / 255))
    rgb = np.array(img.convert("RGB")).astype(np.float32) / 255.0
    image = torch.from_numpy(rgb)[None,]
    if "A" in img.getbands():
        a = np.array(img.getchannel("A")).astype(np.float32) / 255.0
        mask = 1.0 - torch.from_numpy(a)
    else:
        mask = torch.zeros((rgb.shape[0], rgb.shape[1]), dtype=torch.float32)
    return image, mask[None,]


# ----------------------------------------------------------------------------
# Save (encrypt)
# ----------------------------------------------------------------------------

class EncryptedPNGSave:
    """Save images AES-256-GCM encrypted as PNG / JPEG / WebP (*.png.enc, *.jpg.enc, *.webp.enc)."""

    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.temp_dir = folder_paths.get_temp_directory()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "password": ("STRING", {"default": DEFAULT_PASSWORD, "multiline": False,
                                         "tooltip": f"Default {DEFAULT_PASSWORD}. Empty = use the ENCPNG_PASSWORD environment variable"}),
                "filename_prefix": ("STRING", {"default": "encrypted/ComfyUI"}),
                "format": (list(FORMATS.keys()), {"default": "png"}),
                "quality": ("INT", {"default": 95, "min": 1, "max": 100, "step": 1,
                                    "tooltip": "JPEG / WebP quality (ignored for PNG). 100 + webp = lossless"}),
                "embed_workflow": ("BOOLEAN", {"default": True,
                                               "tooltip": "Store prompt/workflow inside the (encrypted) PNG"}),
                "show_preview": ("BOOLEAN", {"default": True,
                                             "tooltip": "Show an unencrypted preview from ComfyUI's temp dir"}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "image/encryption"

    def save(self, images, password, filename_prefix="encrypted/ComfyUI", format="png", quality=95,
             embed_workflow=True, show_preview=True, prompt=None, extra_pnginfo=None):
        if format not in FORMATS:
            format = "png"
        enc_ext, plain_ext, _mime = FORMATS[format]
        pw = resolve_password(password)
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(
            filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0]
        )
        disable_meta = bool(_comfy_args and getattr(_comfy_args, "disable_metadata", False))
        previews = []
        for batch_number, image in enumerate(images):
            arr = np.clip(255.0 * image.cpu().numpy(), 0, 255).astype(np.uint8)
            img = Image.fromarray(arr)

            want_meta = embed_workflow and not disable_meta
            buf = io.BytesIO()
            if format == "png":
                meta = None
                if want_meta:
                    meta = PngInfo()
                    if prompt is not None:
                        meta.add_text("prompt", json.dumps(prompt))
                    if extra_pnginfo is not None:
                        for k, v in extra_pnginfo.items():
                            meta.add_text(k, json.dumps(v))
                img.save(buf, format="PNG", pnginfo=meta, compress_level=4)
            else:
                exif = Image.Exif()
                if want_meta:
                    # same tags ComfyUI uses for animated WebP: 0x010E workflow, 0x010F prompt
                    if extra_pnginfo is not None and "workflow" in extra_pnginfo:
                        exif[0x010E] = "workflow:" + json.dumps(extra_pnginfo["workflow"])
                    if prompt is not None:
                        exif[0x010F] = "prompt:" + json.dumps(prompt)
                if format == "jpeg":
                    img.convert("RGB").save(buf, format="JPEG", quality=quality, exif=exif, optimize=True)
                else:
                    img.save(buf, format="WEBP", quality=quality, lossless=(quality >= 100), exif=exif, method=4)
            img_bytes = buf.getvalue()

            name = filename.replace("%batch_num%", str(batch_number))
            file = f"{name}_{counter:05}_{enc_ext}"
            with open(os.path.join(full_output_folder, file), "wb") as f:
                f.write(encrypt_bytes(img_bytes, pw, DEFAULT_ITERATIONS))

            if show_preview:
                pfile = f"encpng_preview_{name.replace('/', '_')}_{counter:05}_{plain_ext}"
                with open(os.path.join(self.temp_dir, pfile), "wb") as f:
                    f.write(img_bytes)
                previews.append({"filename": pfile, "subfolder": "", "type": "temp"})
            counter += 1

        return {"ui": {"images": previews}}


# ----------------------------------------------------------------------------
# Load (decrypt)
# ----------------------------------------------------------------------------

class EncryptedPNGLoad:
    """Pick an encrypted image file from a dropdown, decrypt it, preview and output it."""

    def __init__(self):
        self.temp_dir = folder_paths.get_temp_directory()

    @classmethod
    def INPUT_TYPES(cls):
        files = list_encrypted_files()
        return {
            "required": {
                "file": (files if files else ["(no encrypted files found)"],),
                "password": ("STRING", {"default": DEFAULT_PASSWORD, "multiline": False,
                                         "tooltip": f"Default {DEFAULT_PASSWORD}. Empty = use the ENCPNG_PASSWORD environment variable"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("image", "mask", "metadata")
    FUNCTION = "load"
    OUTPUT_NODE = True
    CATEGORY = "image/encryption"

    def load(self, file, password):
        try:
            png_bytes = decrypt_named_file(file, password)
        except DecryptError as e:
            raise RuntimeError(str(e))

        fmt = detect_format(png_bytes) or "png"
        img = Image.open(io.BytesIO(png_bytes))
        img.load()
        metadata = json.dumps(_read_metadata(img), ensure_ascii=False)
        image, mask = _pil_to_tensors(img)

        digest = hashlib.sha1(file.encode("utf-8")).hexdigest()[:12]
        pfile = f"encpng_decrypted_{digest}{FORMATS[fmt][1]}"
        with open(os.path.join(self.temp_dir, pfile), "wb") as f:
            f.write(png_bytes)

        return {
            "ui": {"images": [{"filename": pfile, "subfolder": "", "type": "temp"}]},
            "result": (image, mask, metadata),
        }

    @classmethod
    def IS_CHANGED(cls, file, password):
        try:
            p = resolve_enc_path(file)
            st = os.stat(p)
            key = f"{p}|{st.st_mtime_ns}|{st.st_size}|{password}"
        except Exception:
            key = f"{file}|{password}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, file, password):
        if not folder_paths.exists_annotated_filepath(file):
            return f"Encrypted file not found: {file}"
        return True


NODE_CLASS_MAPPINGS = {
    "EncryptedPNGSave": EncryptedPNGSave,
    "EncryptedPNGLoad": EncryptedPNGLoad,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "EncryptedPNGSave": "Save Encrypted Image (AES-GCM)",
    "EncryptedPNGLoad": "Load Encrypted Image (AES-GCM)",
}
