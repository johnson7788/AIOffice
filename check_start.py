#!/usr/bin/env python3
"""状态自检：把 AIOffice 最容易楔死/失联的点逐条查一遍，FAIL 给出修复命令。

用法：python3 check_start.py    （全部 OK 退出 0，任一 FAIL 退出 1）

覆盖的坑（都是踩过的真实故障）：
  1. Docker daemon 是否活着
  2. docserver 容器是否在跑
  3. plugins.json 是否 504 楔死（头号坑：node docservice 卡死 → 零插件加载 → 选区/op 桥全死）
  4. ai-bridge 是否出现在 plugins.json（插件没被发现）
  5. poll.js.gz 主机↔容器大小是否一致（bind-mount 挂错旧仓库 / 没同步）
  6. 每个 .js 是否有比它新的 .gz（stale gz：改了明文没重生成 → nginx gzip_static 吐旧 gz）
  7. 后端 8585 是否就绪
  8. 前端 3585 是否就绪
  9. OpenSandbox 服务（仅当 .env SANDBOX_ENABLED=true）：多租户 terminal 隔离依赖它，
     没起时 agent 跑命令/技能会失败。健康端点 {DOMAIN}/health。
"""
import os
import subprocess
import sys
import urllib.request

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONTAINER = "onlyoffice-documentserver"
GZ_HOST_DIR = os.path.join(PROJECT_DIR, "backend/office_plugin/ai-bridge")
GZ_CONT_DIR = "/var/www/onlyoffice/documentserver/sdkjs-plugins/ai-bridge"

G, R, Y, NC = "\033[0;32m", "\033[0;31m", "\033[1;33m", "\033[0m"
results = []  # (ok: bool, name, detail, fix)


def add(ok, name, detail, fix=""):
    results.append((ok, name, detail, fix))


def sh(args, timeout=8):
    """跑命令，返回 (rc, stdout)。异常/超时 rc=-1。"""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return -1, str(e)


def docker_exec_curl(url, timeout=8):
    """容器内 curl，返回 (http_code:str, time_total:float)；失败 ("000", timeout)。"""
    rc, out = sh(
        ["docker", "exec", CONTAINER, "curl", "-s", "-m", "5", "-o", "/dev/null",
         "-w", "%{http_code}:%{time_total}", url],
        timeout=timeout,
    )
    out = out.strip()
    if rc != 0 or ":" not in out:
        return "000", 5.0
    code, _, t = out.partition(":")
    try:
        return code, float(t)
    except ValueError:
        return code, 5.0


# 1. Docker daemon
rc, _ = sh(["docker", "info"], timeout=8)
daemon_up = rc == 0
add(daemon_up, "Docker daemon",
    "可达" if daemon_up else "无响应/未运行",
    "打开 Docker Desktop：open -a Docker；若之前卡死先 pkill -f com.docker.backend 再 open")

# 依赖 docker 的检查：daemon 不通就全部跳过（避免每条 docker exec 都超时 5s）
if daemon_up:
    # 2. docserver 容器在跑
    rc, out = sh(["docker", "ps", "--filter", f"name={CONTAINER}", "--format", "{{.Status}}"])
    running = out.strip().startswith("Up")
    add(running, "docserver 容器", out.strip() or "未找到（未启动）",
        "cd %s && docker compose up -d documentserver" % PROJECT_DIR)

    if running:
        # 3. plugins.json 楔死检查（头号坑）—— 走 nginx 前端 :80，不要用 :8000
        code, t = docker_exec_curl("http://127.0.0.1/plugins.json")
        ok = code == "200" and t < 2.0
        add(ok, "plugins.json 健康",
            f"http={code} t={t:.2f}s" + ("" if ok else "  ← 楔死/超时，插件加载不出"),
            "docservice 楔死，docker restart/kill 通常无效。重启 Docker Desktop：\n"
            "     osascript -e 'quit app \"Docker Desktop\"'; pkill -f com.docker.backend; "
            "pkill -f 'Docker Desktop.app/Contents/MacOS/Docker Desktop'\n"
            "     然后 open -a Docker，等 docker info 就绪，再 docker compose up -d documentserver")

        # 4. ai-bridge 是否被发现
        if ok:
            rc, body = sh(["docker", "exec", CONTAINER, "curl", "-s", "-m", "5",
                           "http://127.0.0.1/plugins.json"])
            has_bridge = "ai-bridge" in body
            add(has_bridge, "ai-bridge 已注册",
                "在 plugins.json 中" if has_bridge else "未出现在 plugins.json",
                "检查 docker-compose.yml 的 ai-bridge bind-mount；重建容器 "
                "docker rm -f %s && docker compose up -d documentserver" % CONTAINER)

        # 5. poll.js.gz 主机↔容器大小一致（挂错仓库 / 没同步的信号）
        host_gz = os.path.join(GZ_HOST_DIR, "poll.js.gz")
        if os.path.exists(host_gz):
            hsize = os.path.getsize(host_gz)
            rc, out = sh(["docker", "exec", CONTAINER, "wc", "-c", f"{GZ_CONT_DIR}/poll.js.gz"])
            try:
                csize = int(out.strip().split()[0])
            except (ValueError, IndexError):
                csize = -1
            same = hsize == csize
            add(same, "poll.js.gz 挂载同步", f"主机={hsize} 容器={csize}",
                "容器可能挂在旧仓库副本。docker inspect %s --format "
                "'{{range .Mounts}}{{.Source}}{{println}}{{end}}' 看挂载源；"
                "确认是本仓库后 docker rm -f %s && docker compose up -d documentserver"
                % (CONTAINER, CONTAINER))

# 6. stale gz：每个 .js 应有比它新的 .gz（不依赖 docker，本地文件时间戳）
if os.path.isdir(GZ_HOST_DIR):
    stale = []
    for fn in os.listdir(GZ_HOST_DIR):
        if fn.endswith(".js"):
            js = os.path.join(GZ_HOST_DIR, fn)
            gz = js + ".gz"
            if not os.path.exists(gz):
                stale.append(f"{fn}(缺 .gz)")
            elif os.path.getmtime(gz) < os.path.getmtime(js):
                stale.append(f"{fn}(.gz 比源旧)")
    add(not stale, "插件 .gz 未过期", "全部最新" if not stale else "、".join(stale),
        "重新生成：cd %s && for f in *.js; do gzip -9 -c $f > $f.gz; done" % GZ_HOST_DIR)


# 关键：本机服务一律绕过代理直连。这台机器的 shell 常挂 Clash(7890)，urllib 默认
# 吃 http_proxy → 打 localhost:8080 会被代理转成误导性的 502（其实是没起）。ProxyHandler({}) 强制直连。
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_ok(url, timeout=3):
    try:
        with _DIRECT.open(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def env_val(key, default=""):
    """从项目根 .env 读一个值（不引 dotenv 依赖，手动解析）。"""
    try:
        with open(os.path.join(PROJECT_DIR, ".env")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and line.split("=", 1)[0].strip() == key:
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return default


# 7. 后端
be = http_ok("http://localhost:8585/docs")
add(be, "后端 :8585", "就绪" if be else "无响应",
    "cd %s/backend && uv run python server.py --port 8585 &（无 --reload，改 py 要重启）" % PROJECT_DIR)

# 8. 前端
fe = http_ok("http://localhost:3585/")
add(fe, "前端 :3585", "就绪" if fe else "无响应",
    "cd %s/frontend && npm run dev &" % PROJECT_DIR)

# 9. OpenSandbox 服务（仅在启用时才算故障；未启用则 terminal 回退本地 subprocess，无需检查）
if env_val("SANDBOX_ENABLED", "false").lower() in ("1", "true", "yes", "on"):
    domain = env_val("SANDBOX_DOMAIN", "localhost:8080")
    proto = env_val("SANDBOX_PROTOCOL", "http")
    sb = http_ok(f"{proto}://{domain}/health")
    add(sb, "沙箱服务", f"{proto}://{domain}/health " + ("就绪" if sb else "无响应（未启动）"),
        "启动 OpenSandbox 服务端：cd %s && ./start_sandbox.sh" % PROJECT_DIR)
else:
    add(True, "沙箱服务", "SANDBOX_ENABLED=false，terminal 走本地 subprocess，无需沙箱服务")


# ─── 输出 ───
print(f"\n{'='*44}\n  AIOffice 状态自检\n{'='*44}")
failed = 0
for ok, name, detail, fix in results:
    mark = f"{G}✓{NC}" if ok else f"{R}✗{NC}"
    print(f"{mark} {name:<18} {detail}")
    if not ok:
        failed += 1
        if fix:
            print(f"    {Y}修复：{fix}{NC}")
print(f"{'='*44}")
if failed:
    print(f"{R}{failed} 项异常，见上方修复建议{NC}\n")
    sys.exit(1)
print(f"{G}全部正常{NC}\n")
