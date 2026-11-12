# ComfyUI-EncryptedPNG

在 ComfyUI 中把生成的图片以 **AES-256-GCM** 加密保存（`*.png.enc`），并在节点里下拉选择、解密、预览；附带一个独立的本地解密脚本。

## 节点

| 节点 | 说明 |
|---|---|
| **Save Encrypted PNG (AES-GCM)** | 输入 `IMAGE`，加密后写入 `output/<filename_prefix>_00001_.png.enc`。可选把 prompt/workflow 元数据一起嵌入（在加密内容里）。可选在节点上显示预览（明文预览只写到 ComfyUI 的 `temp/`，重启即清空）。 |
| **Load Encrypted PNG (AES-GCM)** | 下拉列出 `output/` 和 `input/` 下所有 `*.png.enc`（新的在前）。切换文件或点 **👁 preview** 即在节点内解密预览；**🔄 refresh file list** 无需重启刷新列表。输出 `image` / `mask` / `metadata`（PNG 文本块的 JSON）。 |

分类：`image/encryption`

## 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/BenjaminHernandez9794/ComfyUI-EncryptedPNG.git
pip install -r ComfyUI-EncryptedPNG/requirements.txt   # 仅 cryptography
```
重启 ComfyUI。

## 密码

- 节点 `password` 留空时，读取环境变量 **`ENCPNG_PASSWORD`**（推荐，避免密码写进工作流 JSON）。
- 填在节点里的密码会随工作流保存/分享，请注意。界面上密码会以 `•` 遮挡显示。

## 本地解密脚本

只依赖 `cryptography`，可单独拷走使用：

```bash
pip install cryptography
python decrypt_local.py image.png.enc                    # 生成同目录 image.png
python decrypt_local.py ComfyUI/output/encrypted -o ./plain   # 递归解密整个文件夹，保留子目录
ENCPNG_PASSWORD=xxx python decrypt_local.py a.png.enc b.png.enc -f   # -f 覆盖已存在文件
```
未提供 `-p` 或环境变量时会提示输入密码。解密出的 PNG 若嵌入了工作流，可直接拖回 ComfyUI 还原。

## 文件格式

```
0   6   magic "ENCPNG"
6   1   版本 = 1
7   1   KDF = 1 (PBKDF2-HMAC-SHA256)
8   4   迭代次数 (big-endian, 默认 200000)
12  16  salt
28  12  nonce
40  ..  ciphertext || 16 字节 GCM tag
```
32 字节密钥由 PBKDF2 派生；每个文件随机 salt + nonce；40 字节头部作为 AAD 参与认证，任何篡改或密码错误都会解密失败。

## 说明

- 预览接口 `POST /encrypted_png/preview` 只读取 ComfyUI 的 input/output/temp 目录，拒绝路径穿越。若 ComfyUI 监听在公网（`--listen`），任何能访问它的人都能尝试密码，请自行加访问控制。
- 忘记密码无法恢复。

## License
MIT
