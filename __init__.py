from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"

# --- HTTP routes used by the front-end (dropdown refresh + in-node preview) ---
try:
    from aiohttp import web
    from server import PromptServer

    from .encpng_core import FORMATS, DecryptError, detect_format
    from .nodes import decrypt_named_file, list_encrypted_files

    routes = PromptServer.instance.routes

    @routes.get("/encrypted_png/list")
    async def _encpng_list(request):
        return web.json_response({"files": list_encrypted_files()})

    @routes.post("/encrypted_png/preview")
    async def _encpng_preview(request):
        try:
            body = await request.json()
            png = decrypt_named_file(body.get("file", ""), body.get("password", ""))
        except DecryptError as e:
            return web.json_response({"error": str(e)}, status=403)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)
        mime = FORMATS.get(detect_format(png) or "png")[2]
        return web.Response(body=png, content_type=mime,
                            headers={"Cache-Control": "no-store"})
except Exception as e:  # pragma: no cover
    print(f"[ComfyUI-EncryptedPNG] preview routes not registered: {e}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
