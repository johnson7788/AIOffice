# OpenSandBox本地部署

### 官方文档快速开始：https://open\-sandbox\.ai/getting\-started/\#\_4\-try\-the\-cli

Python SDK:https://open\-sandbox\.ai/sdks/python\#quick\-start

---



## 📦 完整操作手册（Windows \+ PowerShell）



### 阶段 0：确保 Docker 已启动并配置加速器（可跳过）

如果您尚未配置 Docker 镜像加速，建议先做（否则拉取会慢或失败）：



1. 打开 Docker Desktop → 设置 → Docker Engine，添加以下内容：

    ```JSON
    {
      "registry-mirrors": [
        "https://docker.1ms.run",
        "https://docker.m.daocloud.io"
      ]
    }
    ```

2. 点击 Apply \& Restart。

    

---



### 阶段 1：拉取所需的 Docker 镜像（一次性）



```PowerShell
# 1. 拉取辅助镜像 execd（必须）
docker pull docker.1ms.run/opensandbox/execd:v1.0.20
docker tag docker.1ms.run/opensandbox/execd:v1.0.20 opensandbox/execd:v1.0.20

# 2. 拉取多语言运行环境镜像（含 Java）
docker pull docker.1ms.run/opensandbox/code-interpreter:latest
docker tag docker.1ms.run/opensandbox/code-interpreter:latest opensandbox/code-interpreter:latest

# 3. 拉取 Python 基础镜像（可选，但您已有）
docker pull python:3.12
```



---



### 阶段 2：生成并配置 OpenSandbox 服务器



```PowerShell
# 1. 生成服务器配置文件（使用 Docker 后端示例）
uvx opensandbox-server init-config ~/.sandbox.toml --example docker

# 2. 用记事本编辑配置，设置 api_key
notepad C:\Users\29517\.sandbox.toml
```

在打开的 `[server]` 部分添加或修改：

```TOML
[server]
host = "0.0.0.0"
port = 8080
api_key = "123456"
```

保存并关闭。



---



### 阶段 3：启动 OpenSandbox 服务器（持久运行）



**打开一个终端（不要关闭），执行：**

```PowerShell
uvx opensandbox-server
```

看到 `Uvicorn running on http://127.0.0.1:8080` 表示启动成功，保持该窗口打开。



---



### 阶段 4：配置 CLI（命令行客户端）



**在另一个新终端中执行：**

```PowerShell
# 1. 初始化 CLI 配置（若已存在可跳过）
osb config init

# 2. 设置连接参数
osb config set connection.domain localhost:8080
osb config set connection.protocol http
osb config set connection.api_key "123456"
osb config set connection.request_timeout 180   # 超时改为 180 秒
```



或者直接编辑 `C:\Users\29517\.opensandbox\config.toml`，确保内容为：

```TOML
[connection]
api_key = "123456"
domain = "localhost:8080"
protocol = "http"
request_timeout = 180
```



---



### 阶段 5：创建沙箱并运行 Java 代码



在**同一个终端**（阶段 4 的终端）依次执行：



```PowerShell
# 设置环境变量（确保 CLI 携带 API Key）
Set-Item -Path Env:OPEN-SANDBOX-API-KEY -Value "123456"

# 创建沙箱（使用 code-interpreter 镜像，含 Java）
$result = osb sandbox create --image opensandbox/code-interpreter:latest --timeout 30m -o json
$result   # 显示创建结果，记录其中的 "id"
```

例如返回 `{"id":"abc-123", ...}`，记下 `abc-123`。



```PowerShell
# 运行 Java 命令查看版本
osb command run abc-123 -o raw -- java -version

# 运行 Hello World
osb command run abc-123 -o raw -- sh -c "echo 'public class Hello { public static void main(String[] args) { System.out.println(\"Hello from Java!\"); } }' > Hello.java && javac Hello.java && java Hello"
```



输出应为：

```Plain Text
Hello from Java!
```



---



## 🔄 额外操作

- 查看所有沙箱：`osb sandbox list`

- 销毁沙箱：`osb sandbox destroy <id>`

- 停止服务器：在服务器终端按 `Ctrl+C`

    

---



## 🧪 备选：如果不想用 Docker 后端

可以改用本地进程后端（无需拉取镜像），适合轻量测试：

```PowerShell
uvx opensandbox-server init-config ~/.sandbox.toml --example local
# 编辑设置 api_key
uvx opensandbox-server
# 创建沙箱（仍可指定 python:3.12，但实际在宿主机运行）
```



---



