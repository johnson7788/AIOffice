import { useCallback, useEffect, useRef, useState } from 'react';
import { Excalidraw, serializeAsJSON } from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';
import { readFileText, writeFileText } from './api';

type Scene = { elements: unknown[]; appState: Record<string, unknown>; files: Record<string, unknown> };

/** .excalidraw 白板/思维导图编辑器：读写 uploads/<user_id>/ 下的 .excalidraw 文件。 */
export default function WhiteboardEditor({ path, userId }: { path: string; userId: string }) {
  // undefined=加载中, null=空/新建, Scene=已有内容
  const [initial, setInitial] = useState<Scene | null | undefined>(undefined);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setInitial(undefined);
    readFileText(path, userId)
      .then((txt) => {
        if (!txt.trim()) return setInitial(null);
        try {
          const s = JSON.parse(txt);
          setInitial({ elements: s.elements ?? [], appState: s.appState ?? {}, files: s.files ?? {} });
        } catch {
          setInitial(null);
        }
      })
      .catch(() => setInitial(null));
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [path, userId]);

  // onChange 触发极频繁，防抖后序列化保存
  const handleChange = useCallback(
    (elements: readonly unknown[], appState: unknown, files: unknown) => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const json = serializeAsJSON(elements as any, appState as any, files as any, 'local');
        writeFileText(path, json, userId).catch(() => {});
      }, 800);
    },
    [path, userId],
  );

  if (initial === undefined) {
    return <div className="flex items-center justify-center h-full text-slate-400 text-sm">加载白板…</div>;
  }
  return (
    <div className="h-full w-full">
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      <Excalidraw initialData={(initial ?? undefined) as any} onChange={handleChange} />
    </div>
  );
}
