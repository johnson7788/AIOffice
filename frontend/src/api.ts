const API_BASE = '';

/**
 * SSE 事件类型
 */
export interface SSEEvent {
  type: 'text' | 'thought' | 'tool_step' | 'tool_call' | 'narrator_card' | 'clarify' | 'done';
  [key: string]: unknown;
}

/**
 * 解析 fetch 响应体（SSE 流），yield 每条 data 的 JSON 事件
 */
async function* parseSSE(response: Response): AsyncGenerator<SSEEvent> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status}: ${text}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE 消息以双换行分隔
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';

    for (const part of parts) {
      const lines = part.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const jsonStr = line.slice(6);
          try {
            yield JSON.parse(jsonStr) as SSEEvent;
          } catch {
            // 跳过格式错误的 JSON
          }
        }
      }
    }
  }
}

/**
 * 调用 SSE 流式端点，yield 解析后的 JSON 事件
 */
export async function* streamChat(
  message: string,
  userId: string = 'default_user',
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  // 用 POST 走请求体：白板等大内容注入 message 时，GET 塞 URL 会撑爆请求头触发 HTTP 431
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ message, user_id: userId }),
    signal,
  });
  yield* parseSSE(response);
}

/**
 * 回答 clarify 澄清提问，续接同一 session 的流式输出
 */
export async function* answerChat(
  sessionId: string,
  callId: string,
  answer: string,
  userId: string = 'default_user',
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const response = await fetch(`${API_BASE}/chat/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ session_id: sessionId, call_id: callId, answer, user_id: userId }),
    signal,
  });
  yield* parseSSE(response);
}

/**
 * 调用非流式 POST /chat 端点
 */
export async function postChat(message: string, userId: string = 'default_user') {
  const url = `${API_BASE}/chat`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, user_id: userId }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status}: ${text}`);
  }

  return response.json();
}

/**
 * 上传文件到后端
 */
export async function uploadFile(file: File, userId: string = 'default_user') {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('user_id', userId);

  const response = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status}: ${text}`);
  }

  return response.json();
}

/**
 * 列出用户已上传的文件
 */
export async function listUploads(userId: string = 'default_user') {
  const response = await fetch(`${API_BASE}/uploads?user_id=${encodeURIComponent(userId)}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

/**
 * 清除用户所有已上传的文件
 */
export async function clearUploads(userId: string = 'default_user') {
  const response = await fetch(`${API_BASE}/uploads?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

// ─── 文件工作台 ──────────────────────────────────────────────────────────

export interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size: number;
  modified: number;
  children?: FileNode[];
}

/** 获取用户文档空间的文件树 */
export async function filesTree(userId: string = 'default_user'): Promise<FileNode[]> {
  const response = await fetch(`${API_BASE}/files/tree?user_id=${encodeURIComponent(userId)}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  return data.tree as FileNode[];
}

/** 单个文件的原始内容 URL（可直接给 <img>/下载/编辑器 fetch 用） */
export function fileRawUrl(path: string, userId: string = 'default_user'): string {
  return `${API_BASE}/files/raw?user_id=${encodeURIComponent(userId)}&path=${encodeURIComponent(path)}`;
}

/** 读取文本文件内容 */
export async function readFileText(path: string, userId: string = 'default_user'): Promise<string> {
  const response = await fetch(fileRawUrl(path, userId));
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.text();
}

/** 写入文本文件 */
export async function writeFileText(path: string, content: string, userId: string = 'default_user') {
  const response = await fetch(`${API_BASE}/files/raw`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, content, user_id: userId }),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

/** 删除文件或目录 */
export async function deleteFile(path: string, userId: string = 'default_user') {
  const response = await fetch(
    `${API_BASE}/files?user_id=${encodeURIComponent(userId)}&path=${encodeURIComponent(path)}`,
    { method: 'DELETE' },
  );
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
