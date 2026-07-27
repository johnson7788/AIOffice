import { useCallback, useEffect, useState } from 'react';
import {
  File as FileIcon,
  Folder,
  FolderOpen,
  RefreshCw,
  Trash2,
  Upload,
  Download,
  PenLine,
} from 'lucide-react';
import {
  deleteFile,
  fileRawUrl,
  filesTree,
  readFileText,
  uploadFile,
  writeFileText,
  type FileNode,
} from './api';
import WhiteboardEditor from './WhiteboardEditor';
import OfficeEditor, { isOffice } from './OfficeEditor';

const isWhiteboard = (name: string) => name.toLowerCase().endsWith('.excalidraw');

const IMAGE_EXT = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'];
const TEXT_EXT = ['txt', 'md', 'json', 'csv', 'log', 'py', 'js', 'ts', 'html', 'css', 'yaml', 'yml', 'xml'];

function extOf(name: string): string {
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
}

function TreeNode({
  node,
  depth,
  selected,
  onSelect,
  onDelete,
}: {
  node: FileNode;
  depth: number;
  selected: string | null;
  onSelect: (n: FileNode) => void;
  onDelete: (n: FileNode) => void;
}) {
  const [open, setOpen] = useState(depth < 1);
  const isDir = node.type === 'directory';
  const isSel = selected === node.path;

  return (
    <div>
      <div
        className={`group flex items-center gap-1.5 px-2 py-1 rounded cursor-pointer text-[13px] ${
          isSel ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-slate-100'
        }`}
        style={{ paddingLeft: 8 + depth * 14 }}
        onClick={() => (isDir ? setOpen((o) => !o) : onSelect(node))}
      >
        {isDir ? (
          open ? <FolderOpen size={15} className="text-amber-500" /> : <Folder size={15} className="text-amber-500" />
        ) : (
          <FileIcon size={15} className="text-slate-400" />
        )}
        <span className="truncate flex-1">{node.name}</span>
        <Trash2
          size={13}
          className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-500"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(node);
          }}
        />
      </div>
      {isDir && open && node.children?.map((c) => (
        <TreeNode key={c.path} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} onDelete={onDelete} />
      ))}
    </div>
  );
}

function Preview({ node, userId }: { node: FileNode; userId: string }) {
  const ext = extOf(node.name);
  const url = fileRawUrl(node.path, userId);
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    setText(null);
    if (TEXT_EXT.includes(ext)) {
      readFileText(node.path, userId).then(setText).catch(() => setText('（读取失败）'));
    }
  }, [node.path, ext, userId]);

  if (IMAGE_EXT.includes(ext)) {
    return <img src={url} alt={node.name} className="max-w-full max-h-full object-contain mx-auto" />;
  }
  if (TEXT_EXT.includes(ext)) {
    return (
      <pre className="text-[13px] text-slate-700 whitespace-pre-wrap leading-relaxed p-4 font-mono">
        {text ?? '加载中…'}
      </pre>
    );
  }
  // 无法在线预览的类型（压缩包等）→ 下载
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 text-slate-500">
      <FileIcon size={40} className="text-slate-300" />
      <div className="text-sm">{node.name}</div>
      <a
        href={url}
        download={node.name}
        className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm"
      >
        <Download size={15} /> 下载
      </a>
    </div>
  );
}

export default function Workspace({
  userId,
  onOpenFile,
  reloadNonce = 0,
  showFiles = true,
}: {
  userId: string;
  onOpenFile?: (f: { path: string; name: string } | null) => void;
  reloadNonce?: number;
  showFiles?: boolean;
}) {
  const [tree, setTree] = useState<FileNode[]>([]);
  const [selected, setSelected] = useState<FileNode | null>(null);
  const [loading, setLoading] = useState(false);

  // 上报当前打开的文件，供助手侧栏做文档感知
  useEffect(() => {
    onOpenFile?.(selected ? { path: selected.path, name: selected.name } : null);
  }, [selected, onOpenFile]);

  const refresh = useCallback(() => {
    setLoading(true);
    filesTree(userId)
      .then(setTree)
      .catch(() => setTree([]))
      .finally(() => setLoading(false));
  }, [userId]);

  useEffect(refresh, [refresh]);

  const onUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      await uploadFile(file, userId).catch(() => {});
      e.target.value = '';
      refresh();
    },
    [userId, refresh],
  );

  const onDelete = useCallback(
    async (node: FileNode) => {
      if (!confirm(`删除 ${node.name}？`)) return;
      await deleteFile(node.path, userId).catch(() => {});
      if (selected?.path === node.path) setSelected(null);
      refresh();
    },
    [userId, selected, refresh],
  );

  const onNewWhiteboard = useCallback(async () => {
    const name = `whiteboard-${Date.now()}.excalidraw`;
    await writeFileText(name, '', userId).catch(() => {});
    const data = await filesTree(userId).catch(() => [] as FileNode[]);
    setTree(data);
    const node = data.find((n) => n.path === name);
    if (node) setSelected(node);
  }, [userId]);

  return (
    <div className="flex h-full">
      {/* 文件树（由 Shell 的左侧悬浮把手开合） */}
      {showFiles && (
      <div className="w-64 flex-shrink-0 border-r border-slate-200 flex flex-col bg-white">
        <div className="flex items-center gap-2 px-3 py-2.5 border-b border-slate-200">
          <span className="text-[13px] font-medium text-slate-700 flex-1">文件</span>
          <button className="text-slate-500 hover:text-slate-700" title="新建白板" onClick={onNewWhiteboard}>
            <PenLine size={15} />
          </button>
          <label className="cursor-pointer text-slate-500 hover:text-slate-700" title="上传">
            <Upload size={15} />
            <input type="file" className="hidden" onChange={onUpload} />
          </label>
          <button className="text-slate-500 hover:text-slate-700" title="刷新" onClick={refresh}>
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
        <div className="flex-1 overflow-auto py-1">
          {tree.length === 0 ? (
            <div className="text-center text-slate-400 text-xs py-8">暂无文件</div>
          ) : (
            tree.map((n) => (
              <TreeNode key={n.path} node={n} depth={0} selected={selected?.path ?? null} onSelect={setSelected} onDelete={onDelete} />
            ))
          )}
        </div>
      </div>
      )}

      {/* 编辑/预览区 */}
      <div className="flex-1 min-w-0 bg-slate-50">
        {selected ? (
          isWhiteboard(selected.name) ? (
            <WhiteboardEditor key={`${selected.path}:${reloadNonce}`} path={selected.path} userId={userId} />
          ) : isOffice(selected.name) ? (
            <OfficeEditor key={`${selected.path}:${reloadNonce}`} path={selected.path} userId={userId} name={selected.name} />
          ) : (
            <div className="h-full overflow-auto">
              <Preview node={selected} userId={userId} />
            </div>
          )
        ) : (
          <div className="flex items-center justify-center h-full text-slate-400 text-sm">
            从左侧选择一个文件
          </div>
        )}
      </div>
    </div>
  );
}
