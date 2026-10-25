"""自己组装 .icns 文件（不依赖 iconutil）。

原因：本机沙箱禁止 iconutil 往系统临时目录写中间文件
（/var/folders/.../T/TemporaryItems/NSIRD_iconutil_*），iconutil 直接失败。
→ 解决：给 iconutil 指定项目内的 TMPDIR 就可用（见 make_app.sh），
  本脚本作为不依赖 iconutil 的兜底。

icns 是公开的容器格式：
  magic 'icns' (4 bytes)
  uint32 大端 总长度
  重复若干个 chunk：
    4 bytes type（如 'ic07'）
    uint32 大端 **chunk 总长度（含这 8 字节头）**
    N bytes 数据（PNG 或 ARGB 或 JP2）

⚠️ 关键坑：长度字段含 8 字节头。
   写成纯数据长度 → 解析器读完第一个 chunk 就错位 → 后续 type 全乱
   → IconServices 拒绝整张文件 → Dock/Launchpad 显示坏图标/占位图。
   本脚本的 verify() 必须用**同一套约定**校验，且要独立验证
   「解析走到文件末尾且完全对齐」，否则自己验自己会假通过。

macOS 各尺寸对应的 type（Apple 现代 PNG 型映射）：
  ic11  32x32     (16@1x)   ic12  64x64     (32@1x)
  ic13  256x256   (128@1x)  ic14  512x512   (256@1x)
  ic07  128x128   (64@1x)   ic08  256x256   (128@1x)
  ic09  512x512   (256@1x)  ic10  1024x1024 (512@1x)

⚠️ 不要用 icp4/icp5/icp6：
   那三个是**legacy ARGB 专用 type**，塞 PNG 不合规（历史上能显示，
   但小尺寸场景下 IconServices 会退化到解析 ARGB → 显示彩色噪点）。
   同理 iconutil 额外产出的 legacy chunk（ic04/ic05）也不能留：
   它们是「调色板索引」格式，实测我方 PNG 渲染出的 ic05 调色板色数
   达 618/1282（>256 的 8 位索引上限）→ Launchpad / 标题栏小图标直接花屏。

   所以：**只产 PNG 型图层**，16/32/64 这些小尺寸一律走 ic11/ic12，
   再用 ic07/ic08/ic09 覆盖。这样 Launchpad、标题栏代理图标、
   Dock 全部走 PNG 通路，不存在 legacy 解析风险。
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICONSET = os.path.join(ROOT, "assets", "AppIcon.iconset")
OUT = os.path.join(ROOT, "assets", "AppIcon.icns")

# (iconset 文件名, icns type, 该 type 声明的像素尺寸)
# 顺序按 type 升序，便于人读；顺序对 IconServices 无影响。
CHUNKS = [
    ("icon_16x16@2x.png", b"ic11", 32),    # 16@2x → 32px
    ("icon_32x32@2x.png", b"ic12", 64),    # 32@2x → 64px
    ("icon_128x128.png", b"ic07", 128),
    ("icon_128x128@2x.png", b"ic13", 256),
    ("icon_256x256.png", b"ic08", 256),
    ("icon_256x256@2x.png", b"ic14", 512),
    ("icon_512x512.png", b"ic09", 512),
    ("icon_512x512@2x.png", b"ic10", 1024),
]


def build(iconset=ICONSET, out=OUT):
    parts = []
    for name, ctype, expect_px in CHUNKS:
        path = os.path.join(iconset, name)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        with open(path, "rb") as f:
            data = f.read()
        if not data.startswith(b"\x89PNG"):
            raise ValueError(f"{name} 不是 PNG")
        # 校验像素尺寸与 type 声明相符（不等就是 iconset 文件放错了位置）
        w = struct.unpack(">I", data[16:20])[0]
        h = struct.unpack(">I", data[20:24])[0]
        if (w, h) != (expect_px, expect_px):
            raise ValueError(
                f"{name} 像素 {w}x{h} 与 type {ctype.decode()} "
                f"声明的 {expect_px}x{expect_px} 不符"
            )
        # 长度字段含 8 字节头（type + length），这是 Apple 规范
        parts.append(ctype + struct.pack(">I", len(data) + 8) + data)

    body = b"".join(parts)
    blob = b"icns" + struct.pack(">I", len(body) + 8) + body
    with open(out, "wb") as f:
        f.write(blob)
    return len(blob), len(CHUNKS)


def verify(path=OUT):
    """校验生成的 icns。

    独立校验点（不能只查 magic 和 PNG 头——那套约定错了也会自洽通过）：
      1. magic == b'icns'
      2. 长度表 == 实际文件长
      3. 按「长度含 8 字节头」解析，必须**恰好走到文件末尾**，
         且每个 chunk 的 type 都是 4 字节可打印 ASCII（不是 PNG 残片）
      4. 每个 chunk 的数据都是合法 PNG，且实际像素尺寸与 type 声明相符
    """
    with open(path, "rb") as f:
        blob = f.read()
    if blob[:4] != b"icns":
        return False, "magic 不是 icns"
    total = struct.unpack(">I", blob[4:8])[0]
    if total != len(blob):
        return False, f"长度表 {total} != 实际 {len(blob)}"

    # type → 期望的像素尺寸
    expect = {
        b"ic07": 128, b"ic08": 256, b"ic09": 512, b"ic10": 1024,
        b"ic11": 32, b"ic12": 64, b"ic13": 256, b"ic14": 512,
    }
    # ⚠️ legacy chunk（ic04/ic05/ic06/icp4/icp5/icp6）是 ARGB / 调色板索引格式，
    # 小尺寸场景（Launchpad、标题栏代理图标）会优先取它们 → 实测花屏。
    # 本脚本**只产 PNG 型图层**，所以这里直接判为不合格，不再放行。
    forbidden = {b"ic04", b"ic05", b"ic06", b"icp4", b"icp5", b"icp6"}

    pos = 8
    found = []
    while pos < len(blob):
        if pos + 8 > len(blob):
            return False, f"pos={pos} 处剩余不足 8 字节（未对齐）"
        ctype = blob[pos:pos + 4]
        size = struct.unpack(">I", blob[pos + 4:pos + 8])[0]
        # type 必须是合法 4 字节 ASCII tag，不能是 PNG 残片
        if not all(32 <= b < 127 for b in ctype):
            return False, (f"chunk type 非法 {ctype!r}（pos={pos}）"
                           f"→ 长度约定或数据错位")
        if size < 8 or pos + size > len(blob):
            return False, f"chunk {ctype} 长度越界 (size={size}, pos={pos})"
        data = blob[pos + 8:pos + size]
        if len(data) != size - 8:
            return False, f"chunk {ctype} 数据长度不符"
        if ctype in forbidden:
            return False, (f"chunk {ctype} 是 legacy ARGB/调色板图层，"
                           f"小尺寸会花屏，必须剔除")
        if ctype == b"info":
            found.append(("info", size - 8, "元数据"))
        else:
            if not data.startswith(b"\x89PNG"):
                return False, f"chunk {ctype} 不是 PNG"
            w = struct.unpack(">I", data[16:20])[0]
            h = struct.unpack(">I", data[20:24])[0]
            if ctype in expect and (w, h) != (expect[ctype], expect[ctype]):
                return False, (f"chunk {ctype} 像素 {w}x{h} 与声明 "
                               f"{expect[ctype]} 不符")
            found.append((ctype.decode(), size - 8, f"{w}x{h}"))
        pos += size          # 步进 = 长度字段本身（含头）

    if pos != len(blob):
        return False, f"解析结束 pos={pos} != 文件长 {len(blob)}（未完整消耗）"
    # 必须覆盖到小尺寸（ic11=32 / ic12=64），否则 Launchpad 会退化
    have = {t for t, _, _ in found}
    for need in ("ic11", "ic12"):
        if need not in have:
            return False, f"缺少小尺寸图层 {need}（Launchpad 会显示坏图）"
    return True, found


if __name__ == "__main__":
    n, cnt = build()
    print(f"已生成 {OUT}：{n} bytes，{cnt} 个 chunk")
    ok, info = verify()
    print("校验:", "通过" if ok else f"失败 {info}")
    if ok:
        for t, s, kind in info:
            print(f"  {t}  {s} bytes  {kind}")
