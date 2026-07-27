import { useEffect, useRef, useState } from 'react';
import { Download } from 'lucide-react';
import { fileRawUrl } from './api';

const OFFICE_EXT = [
  'docx', 'doc', 'odt', 'rtf', 'txt',
  'xlsx', 'xls', 'ods', 'csv',
  'pptx', 'ppt', 'odp',
  'pdf',
];

export function isOffice(name: string): boolean {
  const i = name.lastIndexOf('.');
  return i >= 0 && OFFICE_EXT.includes(name.slice(i + 1).toLowerCase());
}

// 按 docserver 地址缓存 api.js 的加载 Promise，避免重复注入
const scriptCache = new Map<string, Promise<void>>();
function loadDocsApi(docserverUrl: string): Promise<void> {
  let p = scriptCache.get(docserverUrl);
  if (p) return p;
  p = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = `${docserverUrl}/web-apps/apps/api/documents/api.js`;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('无法加载 ONLYOFFICE api.js'));
    document.head.appendChild(s);
  });
  scriptCache.set(docserverUrl, p);
  return p;
}

let seq = 0;

/** ONLYOFFICE 在线编辑 doc/xls/ppt/pdf。未配置/不可用时回退为下载。 */
export default function OfficeEditor({ path, userId, name }: { path: string; userId: string; name: string }) {
  const holderId = useRef(`office-${++seq}`).current;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const editorRef = useRef<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    setError(null);
    fetch(`/office/config?path=${encodeURIComponent(path)}&user_id=${encodeURIComponent(userId)}`)
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
        await loadDocsApi(data.docserverUrl);
        if (disposed) return;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const DocsAPI = (window as any).DocsAPI;
        if (!DocsAPI) throw new Error('DocsAPI 未就绪');
        editorRef.current = new DocsAPI.DocEditor(holderId, data.config);
      })
      .catch((e) => !disposed && setError(String(e.message || e)));

    return () => {
      disposed = true;
      try {
        editorRef.current?.destroyEditor?.();
      } catch {
        /* ignore */
      }
      editorRef.current = null;
    };
  }, [path, userId, holderId]);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-slate-400">
        <div className="text-sm">在线编辑不可用：{error}</div>
        <a
          href={fileRawUrl(path, userId)}
          download={name}
          className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm"
        >
          <Download size={15} /> 下载 {name}
        </a>
        <div className="text-xs text-slate-600">（需启动 ONLYOFFICE DocumentServer 并配置 OFFICE_JWT_SECRET）</div>
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <div id={holderId} className="h-full w-full" />
    </div>
  );
}
