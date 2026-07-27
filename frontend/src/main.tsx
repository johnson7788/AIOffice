import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Sparkles, ChevronLeft, ChevronRight, User } from 'lucide-react';
import App from './App.tsx';
import Workspace from './Workspace.tsx';
import './index.css';

/** 边缘悬浮把手：锚在面板分界线上，点击开合抽屉。offset=展开时距对应边的像素（面板宽）。 */
function EdgeToggle({
  edge,
  open,
  offset,
  onClick,
  title,
}: {
  edge: 'left' | 'right';
  open: boolean;
  offset: number;
  onClick: () => void;
  title: string;
}) {
  // 展开时把手贴在面板内侧边界，收起时贴屏幕边缘
  const pos = edge === 'left' ? { left: open ? offset : 0 } : { right: open ? offset : 0 };
  // 箭头指向“点击后的方向”：左侧展开→指左收起，右侧展开→指右收起
  const pointLeft = edge === 'left' ? open : !open;
  return (
    <button
      onClick={onClick}
      title={title}
      style={{ ...pos, top: '50%', transform: 'translateY(-50%)' }}
      className="absolute z-20 flex items-center justify-center w-5 h-14 bg-white border border-slate-200 rounded-md shadow-sm text-slate-400 hover:text-slate-700 hover:bg-slate-50"
    >
      {pointLeft ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
    </button>
  );
}

function Shell() {
  const [userId, setUserId] = useState('default_user');
  const [showFiles, setShowFiles] = useState(true);
  const [showAssistant, setShowAssistant] = useState(true);
  const [openFile, setOpenFile] = useState<{ path: string; name: string } | null>(null);
  // 助手覆盖保存白板后 +1，触发工作台重挂编辑器拉最新内容
  const [reloadNonce, setReloadNonce] = useState(0);

  return (
    <div className="flex flex-col h-screen bg-slate-50">
      {/* 统一顶栏：logo + 产品名 · 用户（开关移到两侧悬浮把手） */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-200 bg-white flex-shrink-0">
        <Sparkles size={18} className="text-blue-600" />
        <span className="text-[15px] font-semibold text-slate-800">Online AI Office</span>
        <div className="ml-auto flex items-center gap-1.5 text-[12px] text-slate-400">
          <User size={14} />
          <input
            className="bg-slate-100 border border-slate-300 rounded px-2 py-0.5 text-slate-700 w-28 outline-none focus:border-blue-500"
            value={userId}
            onChange={(e) => setUserId(e.target.value || 'default_user')}
          />
        </div>
      </div>

      {/* 三栏：文件树+编辑器(Workspace) | 助手对话侧栏(App)；两侧边缘悬浮把手开合 */}
      <div className="flex-1 min-h-0 flex relative">
        <div className="flex-1 min-w-0">
          <Workspace userId={userId} onOpenFile={setOpenFile} reloadNonce={reloadNonce} showFiles={showFiles} />
        </div>
        {showAssistant && (
          <aside className="w-[420px] flex-shrink-0 border-l border-slate-200 min-h-0">
            <App
              userId={userId}
              hideHeader
              openFile={openFile}
              onDocChanged={() => setReloadNonce((n) => n + 1)}
            />
          </aside>
        )}
        {/* 左：文件树开合（树宽 w-64=256）；右：助手开合（宽 420） */}
        <EdgeToggle edge="left" open={showFiles} offset={256} onClick={() => setShowFiles((s) => !s)} title={showFiles ? '隐藏文件' : '显示文件'} />
        <EdgeToggle edge="right" open={showAssistant} offset={420} onClick={() => setShowAssistant((s) => !s)} title={showAssistant ? '隐藏助手' : '显示助手'} />
      </div>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Shell />
  </StrictMode>,
);
