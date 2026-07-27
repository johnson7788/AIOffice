import { useState, useRef, useEffect, useCallback, useMemo, type ReactNode, type ChangeEvent, type DragEvent, type KeyboardEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ArrowUp,
  Bot,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  FileText,
  HelpCircle,
  Loader2,
  Paperclip,
  Search,
  Square,
  Terminal,
  Trash2,
  Upload,
  User,
  Wrench,
  XCircle,
} from 'lucide-react';
import { streamChat, answerChat, uploadFile, type SSEEvent } from './api';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface ToolCall {
  id: string;
  tool_name: string;
  display_name: string;
  args_summary: string;
  status: 'running' | 'done' | 'error';
  result_summary: string | null;
}

interface ToolStep {
  step_id: string;
  summary: string;
  call_count: number;
  calls: ToolCall[];
}

interface ThoughtItem {
  raw: string;
  narrated: string | null;
}

interface HistoryMessage {
  id: string;
  role: 'user' | 'assistant';
  text?: string;
  steps?: ToolStep[];
  thoughts?: ThoughtItem[];
  timeline?: TimelineItem[];
}

interface UploadedFile {
  name: string;
  size: number;
  path: string;
}

// ─── 时序类型 ────────────────────────────────────────────────────────────────

type TimelineItem =
  | { kind: 'thought'; data: ThoughtItem }
  | { kind: 'text'; text: string }
  | { kind: 'tool'; step: ToolStep };

// ─── 澄清提问（人在回路）────────────────────────────────────────────────────

interface ClarifyState {
  session_id: string;
  call_id: string;
  question: string;
  choices: string[];
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const TYPING_CHARS = 3;
const TYPING_INTERVAL = 12;

// ─── 工具图标映射 ────────────────────────────────────────────────────────────

function getToolIcon(toolName: string): ReactNode {
  const map: Record<string, React.ReactNode> = {
    arxiv_search: <Search className="w-4 h-4" />,
    write_file: <FileText className="w-4 h-4" />,
    read_file: <FileText className="w-4 h-4" />,
    execute_command: <Terminal className="w-4 h-4" />,
    load_skill: <Wrench className="w-4 h-4" />,
    web_search: <Search className="w-4 h-4" />,
  };
  return map[toolName] || <Wrench className="w-4 h-4" />;
}

// ─── 预设模版风格（与后端 _STYLE_PRESETS 对应）────────────────────────────────
const PPT_STYLES = [
  '科研答辩风', '麦肯锡风格', '清爽专业风', '数据仪表盘风',
  '党政红风格', '教学课件风', '温暖手工风', '手绘白板风',
  '手绘技术解释风', '电子墨水杂志风', '创意杂志风', '复古扁平插画风',
] as const;

// ─── 示例问题 ─────────────────────────────────────────────────────────────────
type ExampleQuestion = {
  question: string;
  demoFile?: string;  // 内置 demo 文件路径（public/ 下），点击时自动上传
};

const EXAMPLE_QUESTIONS: ExampleQuestion[] = [
  // PPT（图片型）
  { question: '把大语言模型的发展脉络做成一套 12 页 PPT' },
  // PPT（可编辑）+ PDF
  { question: '做一套「Mixture-of-Experts 架构」可编辑幻灯片，并导出 PDF' },
  // Word 报告
  { question: '把「2024 年 AI 行业趋势」整理成一份 Word 报告' },
  // Excel 表格
  { question: '帮我生成一张公司季度业绩的 Excel 表格，含同比对比' },
  // 思维导图（.excalidraw → 工作台白板可编辑）
  { question: '把 Transformer 的核心组件画成一张思维导图，我要在白板里改' },
  // 上传资料 → 据内容生成 PPT
  {
    question: '根据这份讲义生成一套演示文稿',
    demoFile: '/demo/LongContextLLM.pptx',
  },
];

// ─── 子组件 ──────────────────────────────────────────────────────────────────

function Header({
  userId,
  onUserIdChange,
}: {
  userId: string;
  onUserIdChange: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(userId);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  return (
    <header className="flex items-center gap-2 px-4 py-3 border-b border-slate-200 text-sm font-medium text-slate-700">
      <Bot className="w-5 h-5 text-blue-600" />
      <span className="font-semibold text-slate-800">Online AI Office</span>
      <div className="ml-auto flex items-center gap-2">
        {editing ? (
          <input
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onBlur={() => {
              if (value.trim()) onUserIdChange(value.trim());
              setEditing(false);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                if (value.trim()) onUserIdChange(value.trim());
                setEditing(false);
              }
              if (e.key === 'Escape') {
                setValue(userId);
                setEditing(false);
              }
            }}
            className="bg-slate-50 border border-slate-200 rounded px-2 py-1 text-[13px] text-slate-800 outline-none w-36"
          />
        ) : (
          <button
            onClick={() => {
              setValue(userId);
              setEditing(true);
            }}
            className="flex items-center gap-1.5 text-[12px] text-slate-500 hover:text-slate-700 transition-colors bg-slate-100 hover:bg-slate-100 px-2.5 py-1 rounded-lg border border-slate-200"
          >
            <User className="w-3.5 h-3.5" />
            {userId}
          </button>
        )}
      </div>
    </header>
  );
}

function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end gap-3 mb-6 w-full max-w-4xl mx-auto px-4">
      <div className="bg-[#2563eb] text-white px-5 py-4 rounded-2xl rounded-tr-sm max-w-3xl leading-relaxed text-[15px] shadow-sm whitespace-pre-wrap">
        {text}
      </div>
      <div className="flex-shrink-0 w-8 h-8 bg-purple-900/80 rounded-full flex items-center justify-center border border-purple-700/50">
        <User className="w-5 h-5 text-purple-200" />
      </div>
    </div>
  );
}

function SubCallRow({ call }: { call: ToolCall }) {
  const [showResult, setShowResult] = useState(false);
  const hasArgs = call.args_summary && call.args_summary.length > 0;
  const hasResult = call.result_summary && call.result_summary.length > 0;

  // todo 工具：尝试解析 todos 数据
  const isTodo = call.tool_name === 'todo';
  const todos: TodoItem[] | null = useMemo(() => {
    if (!isTodo || !call.result_summary) return null;
    try {
      const parsed = JSON.parse(call.result_summary);
      return Array.isArray(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }, [isTodo, call.result_summary]);

  return (
    <div className="py-1.5">
      <div className="flex items-center gap-2 text-[13px]">
        {call.status === 'running' ? (
          <Loader2 className="w-3.5 h-3.5 text-amber-600 animate-spin flex-shrink-0" />
        ) : call.status === 'error' ? (
          <XCircle className="w-3.5 h-3.5 text-red-600 flex-shrink-0" />
        ) : (
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
        )}
        <span className="text-slate-400">{getToolIcon(call.tool_name)}</span>
        <span className="text-slate-700 font-medium">{call.display_name}</span>
        <span
          className={`px-1.5 py-0.5 rounded text-[11px] font-medium ${
            call.status === 'running'
              ? 'bg-amber-500/10 text-amber-600'
              : call.status === 'error'
                ? 'bg-red-500/10 text-red-600'
                : 'bg-emerald-500/10 text-emerald-600'
          }`}
        >
          {call.status === 'running' ? '执行中...' : call.status === 'error' ? '错误' : '完成'}
        </span>
        {!isTodo && hasResult && (
          <button
            className="ml-auto text-[11px] text-blue-600 hover:text-blue-700 transition-colors flex items-center gap-0.5"
            onClick={() => setShowResult(!showResult)}
          >
            {showResult ? (
              <>
                <ChevronDown className="w-3 h-3" />
                收起结果
              </>
            ) : (
              <>
                <ChevronRight className="w-3 h-3" />
                查看结果
              </>
            )}
          </button>
        )}
      </div>

      {/* 推理说明（始终显示） */}
      {hasArgs && (
        <div className="mt-1.5 ml-5.5 text-[13px] text-slate-400 leading-relaxed">
          {call.args_summary}
        </div>
      )}

      {/* todo 工具：渲染待办列表 */}
      {isTodo && call.status !== 'running' && todos && (
        <div className="mt-2 ml-5.5">
          <TodoCard todos={todos} />
        </div>
      )}

      {/* 返回结果（可展开） */}
      {!isTodo && showResult && hasResult && (
        <div className="mt-2 ml-5.5">
          <pre className={`text-[12px] rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-all font-mono leading-relaxed max-h-80 overflow-y-auto ${
            call.status === 'error'
              ? 'bg-red-50 text-red-700'
              : 'bg-slate-100 text-slate-400'
          }`}>
            {call.result_summary}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── 待办列表卡片 ──────────────────────────────────────────────────────────

interface TodoItem {
  id: string;
  content: string;
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled';
}

function TodoIcon({ status }: { status: TodoItem['status'] }) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />;
    case 'in_progress':
      return <Loader2 className="w-4 h-4 text-blue-600 animate-spin shrink-0" />;
    case 'cancelled':
      return <XCircle className="w-4 h-4 text-slate-500 shrink-0" />;
    default:
      return <Circle className="w-4 h-4 text-slate-500 shrink-0" />;
  }
}

function TodoCard({ todos }: { todos: TodoItem[] }) {
  return (
    <div className="space-y-1.5">
      {todos.map((t) => (
        <div
          key={t.id}
          className={`flex items-start gap-2.5 px-3 py-2 rounded-lg text-[13px] ${
            t.status === 'completed'
              ? 'text-slate-400 line-through'
              : t.status === 'cancelled'
                ? 'text-slate-500 line-through'
                : t.status === 'in_progress'
                  ? 'text-slate-800 bg-blue-500/5 border border-blue-500/10'
                  : 'text-slate-700'
          }`}
        >
          <TodoIcon status={t.status} />
          <span className="leading-snug">{t.content}</span>
        </div>
      ))}
    </div>
  );
}

function ToolStepCard({ step }: { step: ToolStep }) {
  const [open, setOpen] = useState(true);
  const hasRunning = step.calls.some((c) => c.status === 'running');

  // 从子调用中归纳卡片标题
  const toolNames = [...new Set(step.calls.map((c) => c.display_name))];
  const title = toolNames.length <= 2
    ? toolNames.join(' + ')
    : `${toolNames[0]} + 等 ${toolNames.length - 1} 个工具`;

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-slate-100 transition-colors"
        onClick={() => setOpen(!open)}
      >
        <div className="flex items-center gap-3 text-[14px] text-slate-700">
          {open ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
          {hasRunning ? (
            <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />
          ) : (
            getToolIcon(step.calls[0]?.tool_name || '')
          )}
          <span className="font-medium">{title}</span>
        </div>
        <div className="text-[13px] text-slate-500">{step.call_count} 次调用</div>
      </div>
      {open && step.calls.length > 0 && (
        <div className="px-5 pb-3 pt-1">
          <div className="border-l-2 border-slate-200 pl-4 py-1 space-y-1">
            {step.calls.map((call) => (
              <SubCallRow key={call.id} call={call} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ThoughtCard({ thought, thinking = false }: { thought: ThoughtItem; thinking?: boolean }) {
  const [open, setOpen] = useState(thinking);
  // 思考时自动展开，思考结束自动收缩
  useEffect(() => {
    setOpen(thinking);
  }, [thinking]);
  return (
    <div className="inline-flex flex-col max-w-full">
      <div
        className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-50 border border-indigo-500/30 rounded-lg text-indigo-700 text-[14px] font-medium cursor-pointer hover:bg-indigo-100 transition-colors w-max"
        onClick={() => setOpen(!open)}
      >
        {open ? (
          <ChevronDown className="w-4 h-4" />
        ) : (
          <ChevronRight className="w-4 h-4" />
        )}
        {thinking ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Brain className="w-4 h-4" />
        )}
        <span>{thinking ? '思考中...' : '思考过程'}</span>
        {thought.narrated && (
          <span className="text-[12px] text-indigo-400/70 truncate max-w-xs">
            {thought.narrated}
          </span>
        )}
      </div>
      {open && (
        <div className="mt-1 px-4 py-3 bg-indigo-50 border border-indigo-500/20 rounded-lg text-[13px] text-slate-400 leading-relaxed whitespace-pre-wrap max-w-2xl">
          {thought.raw.replace(/\s+/g, ' ').trim()}
        </div>
      )}
    </div>
  );
}

function AssistantMessage({ msg }: { msg: HistoryMessage }) {
  const hasTools = msg.timeline?.some((t) => t.kind === 'tool');
  let textIndex = 0;
  const totalTexts = msg.timeline?.filter((t) => t.kind === 'text').length ?? 0;

  return (
    <div className="flex gap-4 w-full max-w-4xl mx-auto px-4 mb-6">
      <div className="w-8 h-8 bg-slate-100 rounded-full flex items-center justify-center border border-slate-200 flex-shrink-0 mt-1">
        <Bot className="w-4 h-4 text-blue-600" />
      </div>
      <div className="flex-1 flex flex-col gap-2 min-w-0">
        {/* 优先按时序渲染 */}
        {msg.timeline && msg.timeline.length > 0 ? (
          msg.timeline.map((item, i) => {
            if (item.kind === 'thought') {
              return <ThoughtCard key={`t-${i}`} thought={item.data} />;
            }
            if (item.kind === 'text') {
              textIndex++;
              const isFinal = hasTools && textIndex === totalTexts;
              return (
                <div key={`tx-${i}`}>
                  {isFinal && (
                    <div className="flex items-center gap-2 mb-1.5 px-1">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      <span className="text-[13px] font-medium text-emerald-600">最终结果</span>
                    </div>
                  )}
                  <div className="bg-white border border-slate-200 rounded-xl p-6 text-[15px] text-slate-800 prose-invert">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        table: ({ children }) => (
                          <div className="overflow-x-auto">
                            <table className="w-full text-left border-collapse">{children}</table>
                          </div>
                        ),
                        thead: ({ children }) => (
                          <thead className="border-b border-slate-300 text-slate-400 text-[14px]">
                            {children}
                          </thead>
                        ),
                        th: ({ children }) => (
                          <th className="py-3 px-4 font-medium">{children}</th>
                        ),
                        td: ({ children }) => (
                          <td className="py-3 px-4 text-slate-700 border-b border-slate-200">
                            {children}
                          </td>
                        ),
                        code: ({ children, className }) => {
                          const isBlock = className?.includes('language-');
                          if (isBlock) {
                            return (
                              <pre className="bg-slate-50 border border-slate-200 rounded-lg p-4 overflow-x-auto text-[13px]">
                                <code>{children}</code>
                              </pre>
                            );
                          }
                          return (
                            <code className="bg-slate-100 text-blue-700 px-2 py-0.5 rounded text-[13px] border border-slate-200">
                              {children}
                            </code>
                          );
                        },
                        a: ({ children, href }) => (
                          <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:text-blue-700 underline"
                          >
                            {children}
                          </a>
                        ),
                        p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
                        ul: ({ children }) => (
                          <ul className="list-disc pl-5 space-y-1 mb-3">{children}</ul>
                        ),
                        ol: ({ children }) => (
                          <ol className="list-decimal pl-5 space-y-1 mb-3">{children}</ol>
                        ),
                        strong: ({ children }) => (
                          <strong className="text-slate-900 font-bold">{children}</strong>
                        ),
                      }}
                    >
                      {item.text}
                    </ReactMarkdown>
                  </div>
                </div>
              );
            }
            // item.kind === 'tool'
            return <ToolStepCard key={`s-${item.step.step_id}`} step={item.step} />;
          })
        ) : (
          /* 旧消息兼容：没有 timeline 时按旧顺序渲染 */
          <>
            {msg.steps?.map((step) => (
              <ToolStepCard key={step.step_id} step={step} />
            ))}
            {msg.thoughts?.map((t, i) => (
              <ThoughtCard key={i} thought={t} />
            ))}
            {msg.text && (
              <div className="bg-white border border-slate-200 rounded-xl p-6 text-[15px] text-slate-800 prose-invert">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function LiveAgentRow({
  timeline,
  displayedText,
  isStreaming,
}: {
  timeline: TimelineItem[];
  displayedText: string;
  isStreaming: boolean;
}) {
  const hasRunningTool = timeline.some(
    (t) => t.kind === 'tool' && t.step.calls.some((c) => c.status === 'running'),
  );
  const lastItem = timeline[timeline.length - 1];
  const lastWasThought = lastItem?.kind === 'thought';

  // 根据当前阶段显示更精确的状态
  const getStatusText = () => {
    if (hasRunningTool) return '工具执行中...';
    if (lastWasThought) return '思考中...';
    if (timeline.length === 0) return '思考中...';
    // 工具执行完毕后，等待下一阶段（生成回答或继续思考）
    return '分析结果中...';
  };

  return (
    <div className="flex gap-4 w-full max-w-4xl mx-auto px-4 mb-6">
      <div className="w-8 h-8 bg-slate-100 rounded-full flex items-center justify-center border border-slate-200 flex-shrink-0 mt-1">
        <Bot className="w-4 h-4 text-blue-600" />
      </div>
      <div className="flex-1 flex flex-col gap-2 min-w-0">
        {/* 时序渲染已刷入的内容 */}
        {timeline.map((item, i) => {
          if (item.kind === 'thought') {
            // 最后一项 thought 且仍在流式输出、尚无正式回答 → 正在思考
            const isThinking =
              isStreaming && i === timeline.length - 1 && !displayedText;
            return (
              <ThoughtCard key={`t-${i}`} thought={item.data} thinking={isThinking} />
            );
          }
          if (item.kind === 'text') {
            return (
              <div
                key={`tx-${i}`}
                className="bg-white border border-slate-200 rounded-xl p-6 text-[15px] text-slate-800"
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.text}</ReactMarkdown>
              </div>
            );
          }
          return <ToolStepCard key={`s-${item.step.step_id}`} step={item.step} />;
        })}

        {/* 状态指示：流式中且还没有正在显示的文本 */}
        {isStreaming && !displayedText && (
          <div className="flex items-center gap-2 px-4 py-3 bg-white border border-slate-200 rounded-xl text-[14px] text-slate-400">
            <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />
            {getStatusText()}
          </div>
        )}

        {/* 正在流式输出的文字（还未刷入 timeline） */}
        {displayedText && (
          <div className="bg-white border border-slate-200 rounded-xl p-6 text-[15px] text-slate-800">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayedText}</ReactMarkdown>
            {isStreaming && (
              <span className="inline-block w-0.5 h-4 bg-blue-500 ml-0.5 animate-pulse align-text-bottom" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ClarifyCard({
  clarify,
  onAnswer,
  disabled,
}: {
  clarify: ClarifyState;
  onAnswer: (answer: string) => void;
  disabled: boolean;
}) {
  const [custom, setCustom] = useState('');

  return (
    <div className="flex gap-4 w-full max-w-4xl mx-auto px-4 mb-6">
      <div className="w-8 h-8 bg-slate-100 rounded-full flex items-center justify-center border border-slate-200 flex-shrink-0 mt-1">
        <HelpCircle className="w-4 h-4 text-amber-600" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="bg-amber-50 border border-amber-500/30 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3 text-[13px] font-medium text-amber-600">
            <HelpCircle className="w-4 h-4" />
            需要你确认
          </div>
          <div className="text-[15px] text-slate-800 mb-4 whitespace-pre-wrap">
            {clarify.question}
          </div>
          {clarify.choices.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {clarify.choices.map((choice, i) => (
                <button
                  key={i}
                  disabled={disabled}
                  onClick={() => onAnswer(choice)}
                  className="px-4 py-2 text-[14px] rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-700 hover:bg-amber-500/20 hover:border-amber-500/50 transition-colors disabled:opacity-40"
                >
                  {choice}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-end gap-2">
            <textarea
              rows={1}
              value={custom}
              disabled={disabled}
              onChange={(e) => setCustom(e.target.value)}
              onKeyDown={(e) => {
                if (e.nativeEvent.isComposing) return;
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if (custom.trim()) onAnswer(custom.trim());
                }
              }}
              placeholder="或输入你的回答..."
              className="flex-1 bg-slate-50 border border-slate-300 focus:border-amber-500/50 rounded-lg text-[14px] text-slate-800 placeholder:text-slate-500 resize-none outline-none py-2.5 px-3 max-h-32 min-h-[42px]"
            />
            <button
              disabled={disabled || !custom.trim()}
              onClick={() => onAnswer(custom.trim())}
              className="p-2.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg transition-colors shrink-0 disabled:opacity-40"
            >
              <ArrowUp className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function App({
  userId: extUserId,
  hideHeader = false,
  openFile = null,
  onDocChanged,
}: {
  userId?: string;
  hideHeader?: boolean;
  openFile?: { path: string; name: string } | null;
  onDocChanged?: () => void;
} = {}) {
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [userId, setUserId] = useState(extUserId ?? 'default_user');

  // 顶层切换器传入的 userId 覆盖本地（工作台与对话共享同一租户）
  useEffect(() => {
    if (extUserId) setUserId(extUserId);
  }, [extUserId]);
  const [style, setStyle] = useState<string>('');  // 选中的预设模版风格，空=不指定

  // 流式中间状态
  const [liveSteps, setLiveSteps] = useState<ToolStep[]>([]);
  const [liveThoughts, setLiveThoughts] = useState<ThoughtItem[]>([]);
  const [liveTimeline, setLiveTimeline] = useState<TimelineItem[]>([]);
  const [displayedText, setDisplayedText] = useState('');
  const targetTextRef = useRef('');
  const textBufferRef = useRef('');
  const timelineRef = useRef<TimelineItem[]>([]);
  const typingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 澄清提问（人在回路）：收集状态用 ref 以便回答后续接同一轮
  const [clarify, setClarify] = useState<ClarifyState | null>(null);
  const clarifyPendingRef = useRef(false);
  const collectedStepsRef = useRef<ToolStep[]>([]);
  const collectedThoughtsRef = useRef<ThoughtItem[]>([]);

  // 文件上传
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 默认不附带任何文件：只有本会话主动上传的文件才进提示词上下文
  // （不再 mount 时预加载 listUploads，避免新对话自动带上所有已有文件）

  // 自动滚底
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, displayedText, liveSteps, liveTimeline, clarify]);

  // 打字机效果
  const startTyping = useCallback(() => {
    if (typingTimerRef.current) return;
    typingTimerRef.current = setInterval(() => {
      setDisplayedText((prev) => {
        const target = targetTextRef.current;
        if (prev.length >= target.length) return prev;
        return target.slice(0, prev.length + TYPING_CHARS);
      });
    }, TYPING_INTERVAL);
  }, []);

  const stopTyping = useCallback(() => {
    if (typingTimerRef.current) {
      clearInterval(typingTimerRef.current);
      typingTimerRef.current = null;
    }
    setDisplayedText(targetTextRef.current);
  }, []);

  // ─── 文件上传 ──────────────────────────────────────────────────────────

  const doUpload = useCallback(async (file: File, uid?: string) => {
    setUploading(true);
    try {
      const result = await uploadFile(file, uid || userId);
      if (result.success) {
        setUploadedFiles((prev) => [
          ...prev,
          { name: result.filename, size: result.size, path: result.path || '' },
        ]);
      }
    } catch (err) {
      console.error('Upload failed:', err);
    } finally {
      setUploading(false);
    }
  }, []);

  const handleFileSelect = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) doUpload(file);
      e.target.value = '';
    },
    [doUpload],
  );

  // ─── 示例问题点击 ──────────────────────────────────────────────────────

  const handleClickExample = useCallback(
    async (ex: ExampleQuestion) => {
      if (ex.demoFile && !isStreaming) {
        // 自动上传内置 demo 文件
        setUploading(true);
        try {
          const resp = await fetch(ex.demoFile);
          const blob = await resp.blob();
          const fileName = ex.demoFile.split('/').pop()!;
          const file = new File([blob], fileName, { type: blob.type });
          await doUpload(file, userId);
        } catch (err) {
          console.error('Demo file upload failed:', err);
        } finally {
          setUploading(false);
        }
      }
      setInput(ex.question);
    },
    [doUpload, isStreaming],
  );

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file) doUpload(file);
    },
    [doUpload],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  // 仅从提示词上下文移除（不带该文件名/路径），不删除后端文件
  const handleClearFiles = useCallback(() => {
    setUploadedFiles([]);
  }, []);

  const handleRemoveFile = useCallback((fileName: string) => {
    setUploadedFiles((prev) => prev.filter((f) => f.name !== fileName));
  }, []);

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  // ─── 发送消息 ──────────────────────────────────────────────────────────

  // 将累积的文字刷入 timeline
  const flushText = useCallback(() => {
    if (textBufferRef.current) {
      timelineRef.current.push({ kind: 'text', text: textBufferRef.current });
      setLiveTimeline([...timelineRef.current]);
      textBufferRef.current = '';
    }
    // 重置打字机状态 — 已刷入的文字由 timeline 渲染，避免重复显示
    targetTextRef.current = '';
    setDisplayedText('');
  }, []);

  // 把当前实时 timeline 收尾为一条 assistant 历史消息，并重置实时状态
  const finalizeAssistant = useCallback(() => {
    const finalText = targetTextRef.current;
    flushText();
    const finalTimeline = [...timelineRef.current];
    const steps = collectedStepsRef.current;
    const thoughts = collectedThoughtsRef.current;
    if (finalText || steps.length > 0 || thoughts.length > 0 || finalTimeline.length > 0) {
      const assistantMsg: HistoryMessage = {
        id: `assistant_${Date.now()}`,
        role: 'assistant',
        text: finalText || undefined,
        steps: steps.length > 0 ? [...steps] : undefined,
        thoughts: thoughts.length > 0 ? [...thoughts] : undefined,
        timeline: finalTimeline.length > 0 ? finalTimeline : undefined,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    }
    targetTextRef.current = '';
    textBufferRef.current = '';
    timelineRef.current = [];
    collectedStepsRef.current = [];
    collectedThoughtsRef.current = [];
    setDisplayedText('');
    setLiveSteps([]);
    setLiveThoughts([]);
    setLiveTimeline([]);
  }, [flushText]);

  // 消费一个 SSE 事件流（首轮 streamChat 与 clarify 续接 answerChat 共用）
  const processStream = useCallback(
    async (gen: AsyncGenerator<SSEEvent>) => {
      for await (const evt of gen) {
        switch (evt.type) {
          case 'text': {
            const chunk = evt.text as string;
            targetTextRef.current += chunk;
            textBufferRef.current += chunk;
            startTyping();
            break;
          }

          case 'thought': {
            flushText();
            const rawChunk = evt.raw as string;
            const narrated = (evt.narrated as string) || null;
            const lastTlItem = timelineRef.current[timelineRef.current.length - 1];
            const shouldMerge = lastTlItem?.kind === 'thought';
            if (shouldMerge) {
              const last = collectedThoughtsRef.current[collectedThoughtsRef.current.length - 1];
              last.raw += rawChunk;
              if (narrated) last.narrated = narrated;
              setLiveThoughts([...collectedThoughtsRef.current]);
              timelineRef.current[timelineRef.current.length - 1] = { kind: 'thought', data: { ...last } };
              setLiveTimeline([...timelineRef.current]);
            } else {
              const t: ThoughtItem = { raw: rawChunk, narrated };
              collectedThoughtsRef.current.push(t);
              setLiveThoughts([...collectedThoughtsRef.current]);
              timelineRef.current.push({ kind: 'thought', data: t });
              setLiveTimeline([...timelineRef.current]);
            }
            break;
          }

          case 'tool_step': {
            flushText();
            const step: ToolStep = {
              step_id: evt.step_id as string,
              summary: evt.summary as string,
              call_count: evt.call_count as number,
              calls: (evt.calls as ToolCall[]) || [],
            };
            collectedStepsRef.current.push(step);
            setLiveSteps((prev) => [...prev, step]);
            timelineRef.current.push({ kind: 'tool', step });
            setLiveTimeline([...timelineRef.current]);
            break;
          }

          case 'tool_call': {
            const step_id = evt.step_id as string;
            const call_id = evt.call_id as string;
            const status = evt.status as 'done' | 'error';
            const result_summary = evt.result_summary as string;
            const updateCall = (steps: ToolStep[]) =>
              steps.map((s) =>
                s.step_id !== step_id
                  ? s
                  : {
                      ...s,
                      calls: s.calls.map((c) =>
                        c.id === call_id ? { ...c, status, result_summary } : c,
                      ),
                    },
              );
            setLiveSteps((prev) => updateCall(prev));
            const idx = collectedStepsRef.current.findIndex((s) => s.step_id === step_id);
            if (idx >= 0) collectedStepsRef.current[idx] = updateCall([collectedStepsRef.current[idx]])[0];
            const tl = timelineRef.current.map((item) =>
              item.kind === 'tool' && item.step.step_id === step_id
                ? ({ ...item, step: updateCall([item.step])[0] } as TimelineItem)
                : item,
            );
            timelineRef.current = tl;
            setLiveTimeline(tl);
            break;
          }

          case 'clarify': {
            flushText();
            clarifyPendingRef.current = true;
            setClarify({
              session_id: evt.session_id as string,
              call_id: evt.call_id as string,
              question: (evt.question as string) || '',
              choices: (evt.choices as string[]) || [],
            });
            break;
          }

          case 'done': {
            stopTyping();
            flushText();
            // 触发了澄清提问：保留实时 timeline，停止 spinner，等待用户回答后续接
            if (clarifyPendingRef.current) {
              setIsStreaming(false);
              return;
            }
            finalizeAssistant();
            setIsStreaming(false);
            break;
          }
        }
      }
    },
    [startTyping, stopTyping, flushText, finalizeAssistant],
  );

  // 流式异常统一处理（中止 / 网络错误）
  const handleStreamError = useCallback(
    (err: unknown) => {
      stopTyping();
      clarifyPendingRef.current = false;
      setClarify(null);
      if (err instanceof DOMException && err.name === 'AbortError') {
        finalizeAssistant();
        return;
      }
      console.error('SSE error:', err);
      const errMsg = err instanceof Error ? err.message : '未知错误';
      finalizeAssistant();
      setMessages((prev) => [
        ...prev,
        { id: `error_${Date.now()}`, role: 'assistant', text: `请求失败: ${errMsg}` },
      ]);
    },
    [stopTyping, finalizeAssistant],
  );

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput('');
    setIsStreaming(true);
    setClarify(null);
    clarifyPendingRef.current = false;

    // 文件提示
    let fileHint = '';
    if (uploadedFiles.length > 0) {
      fileHint = '\n\n[已上传文件: ' + uploadedFiles.map((f) => f.name).join(', ') + ']';
    }
    // 模版风格提示：让 agent 用选定的预设风格生成 PPT
    const styleHint = style ? `\n\n[PPT 模版风格: ${style}]` : '';
    // 文档上下文提示：工作台正打开某文件时，让 agent 知道针对该文件工作
    const isWhiteboard = !!openFile && openFile.name.toLowerCase().endsWith('.excalidraw');
    let docHint = '';
    if (openFile && isWhiteboard) {
      // 白板：只给文件名/路径，让 agent 围绕主题产出整份新场景覆盖同名文件。
      // 不注入完整 JSON —— 会撑大消息体、每轮吃掉大量 token（内容本就由主题可推导）。
      docHint =
        `\n\n[当前工作台打开的是白板「${openFile.name}」(路径 ${openFile.path})。` +
        `若用户要新增/修改/删除图中的节点或连线，请用 excalidraw-diagram 技能围绕该主题产出【完整的新 .excalidraw JSON】，` +
        `再调用 save_to_workspace("${openFile.path}", 新JSON) 覆盖保存这个同名文件，不要另存别的文件名；跳过 SKILL 里的渲染校验步骤。]`;
    } else if (openFile) {
      docHint = `\n\n[当前正在工作台编辑文件: ${openFile.name}（路径 ${openFile.path}），若用户的修改请求针对该文件，请对其内容操作]`;
    }
    setMessages((prev) => [
      ...prev,
      { id: `user_${Date.now()}`, role: 'user', text: text + fileHint + styleHint },
    ]);

    // 重置流式状态
    targetTextRef.current = '';
    textBufferRef.current = '';
    timelineRef.current = [];
    collectedStepsRef.current = [];
    collectedThoughtsRef.current = [];
    setDisplayedText('');
    setLiveSteps([]);
    setLiveThoughts([]);
    setLiveTimeline([]);

    const ac = new AbortController();
    abortRef.current = ac;

    try {
      await processStream(streamChat(text + styleHint + docHint, userId, ac.signal));
      // 流结束但未收到 'done' 事件时，手动收尾
      if (!clarifyPendingRef.current) {
        finalizeAssistant();
      }
      // 白板走「整图重画覆盖磁盘」→ 需重挂编辑器重读磁盘。
      // office 走 enqueue_office_op → 改动落在编辑器 live 会话（非磁盘），重挂会重读旧磁盘反而把改动冲掉，故不重挂。
      // ponytail: 若哪天 office 又出现「agent 直接重写磁盘」的流程，那条另需重挂；当前 office 编辑一律走 live 插件。
      if (isWhiteboard) onDocChanged?.();
    } catch (err: unknown) {
      handleStreamError(err);
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [input, isStreaming, uploadedFiles, processStream, handleStreamError, userId, style, openFile, onDocChanged]);

  // 回答 clarify 澄清提问，续接同一 session
  const submitAnswer = useCallback(
    async (answer: string) => {
      if (!clarify || isStreaming || !answer) return;
      const c = clarify;
      setClarify(null);
      clarifyPendingRef.current = false;
      setIsStreaming(true);

      const ac = new AbortController();
      abortRef.current = ac;
      try {
        await processStream(answerChat(c.session_id, c.call_id, answer, userId, ac.signal));
      } catch (err: unknown) {
        handleStreamError(err);
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [clarify, isStreaming, processStream, handleStreamError, userId],
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.nativeEvent.isComposing) return;
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    },
    [sendMessage],
  );

  // 自动调整 textarea 高度
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 128) + 'px';
    }
  }, [input]);

  return (
    <div className="h-full flex flex-col bg-slate-50 font-sans selection:bg-blue-500/30">
      {!hideHeader && <Header userId={userId} onUserIdChange={setUserId} />}

      <main className="flex-1 overflow-y-auto py-6">
        {/* 欢迎消息 */}
        {messages.length === 0 && !isStreaming && (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <Bot className="w-12 h-12 text-blue-600/50 mb-4" />
            <h2 className="text-xl font-semibold text-slate-700 mb-2">Online AI Office</h2>
            <p className="text-slate-500 text-sm max-w-md mb-8">
              一句话生成 PPT / PDF / Word / Excel / 思维导图 · 可在工作台在线编辑
            </p>
            <div className="flex flex-wrap justify-center gap-2 max-w-2xl">
              {EXAMPLE_QUESTIONS.map((ex, i) => (
                <button
                  key={i}
                  className={`group flex items-center gap-2 px-4 py-2.5 text-[13px] rounded-xl transition-colors text-left leading-snug ${
                    ex.demoFile
                      ? 'text-amber-600/80 bg-amber-500/5 border border-amber-500/20 hover:bg-amber-500/10 hover:text-amber-700 hover:border-amber-500/30'
                      : 'text-slate-600 bg-slate-100 border border-slate-200 hover:bg-slate-200 hover:text-slate-800 hover:border-slate-300'
                  }`}
                  onClick={() => handleClickExample(ex)}
                  disabled={isStreaming || uploading}
                >
                  {ex.demoFile && (
                    <FileText className="w-3.5 h-3.5 shrink-0 text-amber-600/60 group-hover:text-amber-600/80" />
                  )}
                  <span>{ex.question}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 历史消息 */}
        {messages.map((msg) =>
          msg.role === 'user' ? (
            <UserMessage key={msg.id} text={msg.text || ''} />
          ) : (
            <AssistantMessage key={msg.id} msg={msg} />
          ),
        )}

        {/* 流式实时渲染（澄清等待期间也保持可见） */}
        {(isStreaming || clarify) && (
          <LiveAgentRow
            timeline={liveTimeline}
            displayedText={displayedText}
            isStreaming={isStreaming}
          />
        )}

        {/* 澄清提问卡片 */}
        {clarify && (
          <ClarifyCard clarify={clarify} onAnswer={submitAnswer} disabled={isStreaming} />
        )}

        <div ref={messagesEndRef} />
      </main>

      {/* 已上传文件栏 */}
      {uploadedFiles.length > 0 && (
        <div className="w-full max-w-4xl mx-auto px-4 pb-2">
          <div className="flex flex-wrap items-center gap-1.5 py-2">
            {uploadedFiles.map((f, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 bg-slate-100 text-slate-700 px-2 py-1 rounded-lg text-[12px] border border-slate-200"
                title={f.path}
              >
                <Paperclip className="w-3 h-3 text-slate-500" />
                {f.name} ({formatSize(f.size)})
                <button
                  className="text-slate-500 hover:text-red-600 ml-0.5"
                  onClick={() => handleRemoveFile(f.name)}
                >
                  <XCircle className="w-3 h-3" />
                </button>
              </span>
            ))}
            <button
              className="text-slate-500 hover:text-red-600 text-[12px] flex items-center gap-1 px-1.5"
              onClick={handleClearFiles}
            >
              <Trash2 className="w-3 h-3" />
              清除全部
            </button>
          </div>
        </div>
      )}

      {/* 文件拖拽区域 */}
      <div
        className={`w-full max-w-4xl mx-auto px-4 transition-opacity ${
          isDragging ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
      >
        <div className="border-2 border-dashed border-blue-500/50 rounded-xl py-3 text-center text-[13px] text-blue-600 bg-blue-500/5 mb-2">
          {uploading ? '上传中...' : '松开鼠标上传文件'}
        </div>
      </div>

      {/* 文档上下文条：工作台打开某文件时显示，助手作用域绑定该文件 */}
      {openFile && (
        <div className="w-full max-w-4xl mx-auto px-4 pt-1">
          <div className="flex items-center gap-1.5 text-[12px] text-blue-700 bg-blue-500/10 border border-blue-500/20 rounded-lg px-2.5 py-1.5">
            <FileText className="w-3.5 h-3.5 shrink-0 text-blue-600/80" />
            <span className="truncate">
              正在编辑 <span className="font-medium">{openFile.name}</span> · 可让我改其中某段/某图
            </span>
          </div>
        </div>
      )}

      {/* 输入区域 */}
      <div className="w-full max-w-4xl mx-auto px-4 pb-6 pt-2 shrink-0">
        {/* 模版风格行：仅生成 PPT 时用，移出输入行避免喧宾夺主 */}
        <div className="flex items-center gap-2 mb-2 px-1">
          <span className="text-[12px] text-slate-500">PPT 模版</span>
          <select
            value={style}
            onChange={(e) => setStyle(e.target.value)}
            title="PPT 模版风格"
            className="shrink-0 bg-slate-50 border border-slate-300 rounded-lg text-[12px] text-slate-700 outline-none py-1 px-2 max-w-[9rem] focus:border-slate-500/60"
          >
            <option value="">不指定</option>
            {PPT_STYLES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div
          className={`bg-white border rounded-2xl flex items-end p-2 transition-colors shadow-lg shadow-black/20 ${
            isDragging ? 'border-blue-500/60' : 'border-slate-300 focus-within:border-slate-500/60'
          }`}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          <button
            className="p-3 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-xl transition-colors mb-0.5"
            onClick={() => fileInputRef.current?.click()}
            title="上传文件"
          >
            {uploading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Upload className="w-5 h-5" />
            )}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            onChange={handleFileSelect}
            className="hidden"
          />
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming || !!clarify}
            placeholder={
              clarify
                ? '请先回答上方的确认问题...'
                : isStreaming
                  ? 'AI 正在思考...'
                  : '描述你想生成的内容，如：把季度业绩做成 Excel 表格'
            }
            className="flex-1 bg-transparent text-[15px] text-slate-800 placeholder:text-slate-500 resize-none outline-none py-3 px-3 max-h-32 min-h-[44px] disabled:opacity-50"
          />
          {isStreaming ? (
            <button
              className="p-2.5 m-0.5 bg-red-600 hover:bg-red-500 text-white rounded-xl transition-colors shrink-0"
              onClick={handleStop}
              title="停止"
            >
              <Square className="w-5 h-5" />
            </button>
          ) : (
            <button
              className="p-2.5 m-0.5 bg-[#2563eb] hover:bg-blue-600 text-white rounded-xl transition-colors shrink-0 disabled:opacity-40"
              onClick={sendMessage}
              disabled={!input.trim() || !!clarify}
            >
              <ArrowUp className="w-5 h-5" />
            </button>
          )}
        </div>
        <div className="text-center mt-3 text-[12px] text-slate-500">
          内容由 AI 生成，请仔细甄别。
        </div>
      </div>
    </div>
  );
}
