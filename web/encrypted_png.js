import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Front-end for "Load Encrypted PNG (AES-GCM)":
//  - 🔄 button refreshes the file dropdown without restarting ComfyUI
//  - 👁 button (and changing the file) decrypts on the server and previews in-node
//  - the password field is masked on screen

const NODE = "EncryptedPNGLoad";

function maskPasswordWidget(node) {
    const w = node.widgets?.find((x) => x.name === "password");
    if (!w || w._encpngMasked) return;
    w._encpngMasked = true;
    const orig = w.draw;
    if (typeof orig === "function") {
        w.draw = function (ctx, n, width, y, height) {
            const real = this.value;
            this.value = real ? "•".repeat(Math.min(String(real).length, 16)) : "";
            try {
                return orig.call(this, ctx, n, width, y, height);
            } finally {
                this.value = real;
            }
        };
    }
}

async function refreshList(node) {
    const fileW = node.widgets.find((w) => w.name === "file");
    const res = await api.fetchApi("/encrypted_png/list");
    const { files } = await res.json();
    fileW.options.values = files.length ? files : ["(no .png.enc files found)"];
    if (!fileW.options.values.includes(fileW.value)) fileW.value = fileW.options.values[0];
    app.graph.setDirtyCanvas(true, true);
}

async function preview(node, quiet = false) {
    const file = node.widgets.find((w) => w.name === "file")?.value;
    const password = node.widgets.find((w) => w.name === "password")?.value ?? "";
    if (!file || file.startsWith("(no ")) return;
    const res = await api.fetchApi("/encrypted_png/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file, password }),
    });
    if (!res.ok) {
        let msg = res.statusText;
        try { msg = (await res.json()).error || msg; } catch {}
        if (!quiet) alert(`Encrypted PNG preview: ${msg}`);
        node.imgs = undefined;
        app.graph.setDirtyCanvas(true, true);
        return;
    }
    const blob = await res.blob();
    if (node._encpngUrl) URL.revokeObjectURL(node._encpngUrl);
    node._encpngUrl = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
        node.imgs = [img];
        node.imageIndex = 0;
        node.setSizeForImage?.();
        app.graph.setDirtyCanvas(true, true);
    };
    img.src = node._encpngUrl;
}

app.registerExtension({
    name: "EncryptedPNG.LoadPreview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE) return;

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            const node = this;
            maskPasswordWidget(node);

            const fileW = node.widgets.find((w) => w.name === "file");
            const cb = fileW.callback;
            fileW.callback = function () {
                const out = cb?.apply(this, arguments);
                preview(node, true);
                return out;
            };

            node.addWidget("button", "🔄 refresh file list", null, () => refreshList(node));
            node.addWidget("button", "👁 preview (decrypt)", null, () => preview(node));
            return r;
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            if (this._encpngUrl) URL.revokeObjectURL(this._encpngUrl);
            return onRemoved?.apply(this, arguments);
        };
    },
});
