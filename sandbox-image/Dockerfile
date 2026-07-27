FROM python:3.12

WORKDIR /app

# ---- System dependencies ----
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    curl \
    vim \
    pandoc \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---- Python dependencies ----
ARG PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
COPY requirements.txt .
RUN pip install --no-cache-dir -i "$PIP_MIRROR" -r requirements.txt

# ---- Skills ----
COPY skills/ ./skills/

CMD ["tail", "-f", "/dev/null"]
