#!/bin/bash
# 停止 AIOffice 前后端所有进程（后端 uvicorn:8585 + 各 app vite dev:3585-3588）。

for port in 8585 3585 3586 3587 3588; do
    pids=$(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "kill :$port -> $pids"
        kill $pids 2>/dev/null
    fi
done

echo "done"
