#!/usr/bin/env bash
# L2：用 ONLYOFFICE 自带 docbuilder（无浏览器、无编辑器 UI）验证 P6.2 的 Builder 脚本
# 真能把幻灯片背景改成指定色。证明 op→文档正确性，与浏览器/插件管道解耦。
# 用法：bash tests/l2_builder_docbuilder.sh [样例.pptx]
# 依赖：docker + 已拉取的 onlyoffice/documentserver 镜像（docbuilder 二进制内置其中）
set -euo pipefail

R="$(cd "$(dirname "$0")/../.." && pwd)"
SAMPLE="${1:-$R/backend/uploads/default_user/循证医学智能体.pptx}"
IMG="onlyoffice/documentserver"
DOCBUILDER="/var/www/onlyoffice/documentserver/server/FileConverter/bin/docbuilder"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cp "$SAMPLE" "$WORK/in.pptx"
cat > "$WORK/bg.docbuilder" <<'EOF'
builder.OpenFile("/test/in.pptx");
var oSlide = Api.GetPresentation().GetSlideByIndex(0);
oSlide.SetBackground(Api.CreateSolidFill(Api.CreateRGBColor(0xFF, 0xFA, 0xCD)));
builder.SaveFile("pptx", "/test/out.pptx");
builder.CloseFile();
EOF

docker run --rm -v "$WORK:/test" --entrypoint "$DOCBUILDER" "$IMG" /test/bg.docbuilder

python3 - "$WORK/in.pptx" "$WORK/out.pptx" <<'PY'
import sys, zipfile, re
def bg(p, idx=1):
    x = zipfile.ZipFile(p).read(f"ppt/slides/slide{idx}.xml").decode()
    m = re.search(r'<p:bg>.*?srgbClr\s+val="([0-9A-Fa-f]{6})"', x, re.S)
    return m.group(1).upper() if m else None
before, after = bg(sys.argv[1]), bg(sys.argv[2])
print(f"before={before} after={after}")
assert after == "FFFACD", f"L2 FAIL: expected FFFACD got {after}"
print("L2 OK: SetBackground 生效")
PY
