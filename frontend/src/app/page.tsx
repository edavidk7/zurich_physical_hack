"use client";

import { useState, useEffect, useRef } from "react";
import {
  Settings,
  BookOpen,
  Play,
  Clock,
  Cpu,
  Camera,
  FileText,
  Upload,
  Search,
  ChevronRight,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Layers,
  Gauge,
  Zap,
  ArrowRight,
  Code2,
  BarChart3,
  Image,
  Paperclip,
  X,
  Loader2,
  MessageSquare,
  Send,
  Bot,
  User,
  Sparkles,
  Maximize2,
  Minimize2,
  Download,
  Crosshair,
  RotateCcw,
  Move3d,
  Plug,
  Unplug,
  Wifi,
  WifiOff,
  Home,
} from "lucide-react";

import {
  getDocuments,
  uploadDocument,
  executeTaskStream,
  imageUrl,
  chatWithAgent,
  executeOnRobot,
  getDocumentContent,
  locateKeypoints,
  executeStepKeypoints,
  forwardKinematics,
  inverseKinematics,
  getHomePosition,
  motorConnect,
  motorDisconnect,
  motorStatus,
  motorMove,
  motorSetSpeed,
  runClosedLoop,
} from "@/lib/api";
import type { EEPosition, IKResult, ClosedLoopIteration } from "@/lib/api";

import type {
  DocumentsResponse,
  ExecuteResult,
  SearchResult,
  Step,
  ChatMessage,
  SearchResultEvent,
  KeypointResponse,
} from "@/lib/types";

// ===========================================================================
// Main App
// ===========================================================================

export default function Home() {
  const [page, setPage] = useState<"task" | "kb" | "agent" | "ik">("task");
  const [docs, setDocs] = useState<DocumentsResponse | null>(null);
  const [result, setResult] = useState<ExecuteResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [taskInput, setTaskInput] = useState("");
  const [activeTab, setActiveTab] = useState<"plan" | "sources" | "json" | "keypoints">("plan");
  const [robotStatus, setRobotStatus] = useState<"idle" | "running" | "complete" | "error">("idle");
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [pipelineStages, setPipelineStages] = useState<{ message: string; status: "pending" | "active" | "done" | "error"; icon?: string }[]>([]);
  const [searchHits, setSearchHits] = useState<SearchResultEvent[]>([]);

  useEffect(() => {
    getDocuments().then(setDocs).catch(() => {});
  }, []);

  const now = new Date();
  const timestamp = now.toLocaleString("en-US", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });

  const EXAMPLES = [
    "Verify the Arduino 3.3V pin outputs correct voltage per datasheet specs",
    "Inspect conveyor belt tension according to maintenance manual",
    "Run pre-shift safety checklist for CNC lathe startup",
    "Check torque on M8 bolts per assembly SOP",
  ];

  async function handleExecute() {
    if (!taskInput.trim()) return;
    setLoading(true);
    setRobotStatus("running");
    setActiveTab("plan");
    setResult(null);
    setPipelineStages([]);
    setSearchHits([]);

    try {
      // Upload any attached files first
      if (attachedFiles.length > 0) {
        setPipelineStages([{ message: `Uploading ${attachedFiles.length} file(s)…`, status: "active" }]);
        for (const file of attachedFiles) {
          await uploadDocument(file);
        }
        const refreshed = await getDocuments();
        setDocs(refreshed);
        setAttachedFiles([]);
        setPipelineStages((prev) => prev.map((s) => ({ ...s, status: "done" as const })));
      }

      // Stream the pipeline execution
      setPipelineStages((prev) => [...prev, { message: "Initializing pipeline…", status: "active" }]);

      await executeTaskStream(taskInput.trim(), {
        onStage: (stage) => {
          setPipelineStages((prev) => {
            // Mark previous active stages as done
            const updated = prev.map((s) =>
              s.status === "active" ? { ...s, status: "done" as const } : s
            );
            // Add new stage
            return [
              ...updated,
              {
                message: stage.message,
                status: stage.stage === "complete" ? "done" as const : "active" as const,
              },
            ];
          });
        },
        onSearchResult: (sr) => {
          setSearchHits((prev) => [...prev, sr]);
        },
        onSearchError: () => {},
        onDone: (res) => {
          setResult(res);
          setRobotStatus(res.task_plan ? "complete" : "error");
          setPipelineStages([]);
          setSearchHits([]);
          setStatusMessage("");
        },
        onError: (errMsg) => {
          setStatusMessage(`Error: ${errMsg}`);
          setRobotStatus("error");
          setPipelineStages((prev) =>
            prev.map((s) =>
              s.status === "active" ? { ...s, status: "error" as const } : s
            )
          );
        },
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setStatusMessage(`Error: ${msg}`);
      setRobotStatus("error");
      setPipelineStages((prev) =>
        prev.map((s) =>
          s.status === "active" ? { ...s, status: "error" as const } : s
        )
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleUpload(files: FileList | null) {
    // When called with null, just refresh the documents list (used by KBPage after processing)
    if (!files) {
      const refreshed = await getDocuments();
      setDocs(refreshed);
      return;
    }
    for (const file of Array.from(files)) {
      try {
        await uploadDocument(file);
      } catch {
        /* skip */
      }
    }
    const refreshed = await getDocuments();
    setDocs(refreshed);
  }

  const statusDot: Record<string, string> = {
    idle: "bg-amber-400",
    running: "bg-emerald-400 animate-pulse-dot",
    complete: "bg-emerald-400",
    error: "bg-red-400",
  };
  const statusLabel: Record<string, string> = {
    idle: "Idle",
    running: "Executing…",
    complete: "Ready",
    error: "Error",
  };

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside
        className="w-56 flex-shrink-0 flex flex-col"
        style={{ background: "linear-gradient(180deg, #1a8a84 0%, #00695C 100%)" }}
      >
        <div className="px-5 pt-6 pb-4">
          <div className="flex items-center gap-2 text-white">
            <Settings size={22} className="opacity-80" />
            <span className="text-lg font-bold tracking-tight">DocOps</span>
          </div>
          <p className="text-xs text-white/50 mt-1">Test &amp; Verification</p>
        </div>

        <nav className="flex-1 px-3 space-y-1">
          <NavItem icon={<Zap size={18} />} label="Task" active={page === "task"} onClick={() => setPage("task")} />
          <NavItem icon={<BookOpen size={18} />} label="Knowledge Base" active={page === "kb"} onClick={() => setPage("kb")} />
          <NavItem icon={<MessageSquare size={18} />} label="AI Agent" active={page === "agent"} onClick={() => setPage("agent")} />
          <NavItem icon={<Move3d size={18} />} label="Arm Control" active={page === "ik"} onClick={() => setPage("ik")} />
        </nav>

        <div className="px-5 pb-5">
          <div className="text-xs text-white/40">{docs?.stats.count ?? 0} document(s) indexed</div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-12 flex items-center justify-between px-6 border-b border-gray-200 bg-white flex-shrink-0">
          <span className="text-sm font-semibold text-gray-800">
            {page === "task" ? "⚙️ Task Execution" : page === "agent" ? "🤖 AI Agent" : page === "ik" ? "🦾 Arm Control" : "📚 Knowledge Base"}
          </span>
          <div className="flex items-center gap-5 text-xs text-gray-400">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" /> System Online
            </span>
            <span className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full inline-block ${statusDot[robotStatus]}`} />
              Robot: {statusLabel[robotStatus]}
            </span>
            <span className="flex items-center gap-1"><Clock size={12} /> {timestamp}</span>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto">
          {page === "task" ? (
            <TaskPage
              taskInput={taskInput}
              setTaskInput={setTaskInput}
              examples={EXAMPLES}
              loading={loading}
              statusMessage={statusMessage}
              result={result}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              robotStatus={robotStatus}
              setRobotStatus={setRobotStatus}
              onExecute={handleExecute}
              docs={docs}
              attachedFiles={attachedFiles}
              setAttachedFiles={setAttachedFiles}
              pipelineStages={pipelineStages}
              searchHits={searchHits}
            />
          ) : page === "agent" ? (
            <AgentPage docs={docs} />
          ) : page === "ik" ? (
            <IKPage />
          ) : (
            <KBPage docs={docs} onUpload={handleUpload} />
          )}
        </main>

        <footer className="h-8 flex items-center justify-center text-xs text-gray-300 border-t border-gray-100 bg-white flex-shrink-0">
          DocOps — Documents don&apos;t just get read. They get run.
        </footer>
      </div>
    </div>
  );
}

/* ========================================================================= */
/* Sidebar nav item                                                          */
/* ========================================================================= */

function NavItem({ icon, label, active, onClick }: { icon: React.ReactNode; label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
        active ? "bg-white/20 text-white" : "text-white/70 hover:bg-white/10 hover:text-white"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

/* ========================================================================= */
/* Task Page                                                                 */
/* ========================================================================= */

function TaskPage({
  taskInput, setTaskInput, examples, loading, statusMessage,
  result, activeTab, setActiveTab, robotStatus, setRobotStatus, onExecute, docs,
  attachedFiles, setAttachedFiles, pipelineStages, searchHits,
}: {
  taskInput: string;
  setTaskInput: (v: string) => void;
  examples: string[];
  loading: boolean;
  statusMessage: string;
  result: ExecuteResult | null;
  activeTab: "plan" | "sources" | "json" | "keypoints";
  setActiveTab: (v: "plan" | "sources" | "json" | "keypoints") => void;
  robotStatus: string;
  setRobotStatus: (s: "idle" | "running" | "complete" | "error") => void;
  onExecute: () => void;
  docs: DocumentsResponse | null;
  attachedFiles: File[];
  setAttachedFiles: (files: File[]) => void;
  pipelineStages: { message: string; status: "pending" | "active" | "done" | "error" }[];
  searchHits: { document: string; relevant: boolean }[];
}) {
  const [feedback, setFeedback] = useState("");
  const [deploying, setDeploying] = useState(false);
  const [deployMessage, setDeployMessage] = useState("");

  async function handleDeploy() {
    if (!result?.task_plan) return;
    setDeploying(true);
    setDeployMessage("");
    try {
      const res = await executeOnRobot(result.task_plan as unknown as Record<string, unknown>, feedback || undefined);
      setDeployMessage(res.message);
      setRobotStatus("running");
      // Simulate completion after a few seconds
      setTimeout(() => {
        setRobotStatus("complete");
        setDeployMessage("Execution complete — all steps finished.");
      }, 5000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Deploy failed";
      setDeployMessage(`Error: ${msg}`);
      setRobotStatus("error");
    } finally {
      setDeploying(false);
    }
  }

  return (
    <div className="flex gap-6 p-6 h-full">
      {/* Left column */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Task input */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-5">
          <h2 className="text-lg font-bold text-gray-800 mb-4 flex items-center gap-2">
            <FileText size={20} className="text-teal-600" /> Task Definition
          </h2>

          <div className="mb-3">
            <p className="text-xs text-gray-400 mb-1.5">Try an example:</p>
            <div className="flex flex-wrap gap-1.5">
              {examples.map((ex, i) => (
                <button
                  key={i}
                  onClick={() => setTaskInput(ex)}
                  className="text-xs px-3 py-1.5 rounded-full border border-gray-200 text-gray-500 hover:border-teal-400 hover:text-teal-700 hover:bg-teal-50 transition-colors"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>

          <textarea
            value={taskInput}
            onChange={(e) => setTaskInput(e.target.value)}
            placeholder="Describe what you want to verify, measure, or test…"
            rows={3}
            className="w-full resize-none rounded-lg border border-gray-200 p-3 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400/40 focus:border-teal-400 placeholder:text-gray-300"
          />

          {/* Attached files */}
          {attachedFiles.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {attachedFiles.map((f, i) => (
                <span key={i} className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-teal-50 text-teal-700 border border-teal-200">
                  <FileText size={12} />
                  {f.name}
                  <button onClick={() => setAttachedFiles(attachedFiles.filter((_, j) => j !== i))} className="hover:text-red-500 transition-colors">
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}

          <div className="flex items-center justify-between mt-3">
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer hover:text-teal-600 transition-colors">
                <Paperclip size={14} />
                Attach PDF
                <input
                  type="file"
                  accept=".pdf"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files) {
                      setAttachedFiles([...attachedFiles, ...Array.from(e.target.files)]);
                      e.target.value = "";
                    }
                  }}
                />
              </label>
              <span className="text-xs text-gray-300">·</span>
              <span className="text-xs text-gray-400">{docs?.stats.count ?? 0} document(s) will be searched</span>
            </div>
            <button
              onClick={onExecute}
              disabled={loading || !taskInput.trim()}
              className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold text-white bg-teal-500 hover:bg-teal-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? (
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <Play size={15} />
              )}
              {loading ? "Running…" : "Execute"}
            </button>
          </div>
        </div>

        {/* Pipeline progress */}
        {(loading || pipelineStages.length > 0) && (
          <div className="mb-4 bg-white rounded-xl border border-gray-200 overflow-hidden animate-slide-up">
            <div className="px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
              {loading ? (
                <Loader2 size={14} className="text-teal-500 animate-spin" />
              ) : (
                <CheckCircle2 size={14} className="text-emerald-500" />
              )}
              <span className="text-xs font-semibold text-gray-700">
                {loading ? "Pipeline Running" : "Pipeline Complete"}
              </span>
              {searchHits.length > 0 && (
                <span className="ml-auto text-[11px] text-gray-400">
                  {searchHits.filter((h) => h.relevant).length}/{searchHits.length} docs matched
                </span>
              )}
            </div>
            <div className="px-4 py-2 space-y-1">
              {pipelineStages.map((s, i) => (
                <div key={i} className="flex items-center gap-2 py-1">
                  {s.status === "done" ? (
                    <CheckCircle2 size={13} className="text-emerald-500 flex-shrink-0" />
                  ) : s.status === "error" ? (
                    <XCircle size={13} className="text-red-500 flex-shrink-0" />
                  ) : s.status === "active" ? (
                    <Loader2 size={13} className="text-teal-500 animate-spin flex-shrink-0" />
                  ) : (
                    <span className="w-3.5 h-3.5 rounded-full border-2 border-gray-200 flex-shrink-0" />
                  )}
                  <span className={`text-xs ${s.status === "active" ? "text-teal-700 font-medium" : s.status === "done" ? "text-gray-500" : s.status === "error" ? "text-red-600" : "text-gray-400"}`}>
                    {s.message}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Status */}
        {statusMessage && (
          <div className={`mb-4 px-4 py-2.5 rounded-lg text-sm animate-slide-up ${
            statusMessage.startsWith("Error")
              ? "bg-red-50 text-red-700 border border-red-200"
              : "bg-teal-50 text-teal-700 border border-teal-200"
          }`}>
            {statusMessage}
          </div>
        )}

        {/* Result tabs */}
        <div className="flex-1 bg-white rounded-xl border border-gray-200 flex flex-col min-h-0">
          <div className="flex border-b border-gray-200">
            {([
              { key: "plan" as const, icon: <Layers size={14} />, label: "Task Plan" },
              { key: "sources" as const, icon: <Search size={14} />, label: "Source Documents" },
              { key: "keypoints" as const, icon: <Camera size={14} />, label: "Keypoints" },
              { key: "json" as const, icon: <Code2 size={14} />, label: "JSON" },
            ]).map((t) => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                className={`flex items-center gap-1.5 px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === t.key
                    ? "border-teal-500 text-teal-700"
                    : "border-transparent text-gray-400 hover:text-gray-600"
                }`}
              >
                {t.icon} {t.label}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto p-5">
            {activeTab === "plan" && <PlanTab result={result} />}
            {activeTab === "sources" && <SourcesTab result={result} />}
            {activeTab === "keypoints" && <KeypointsTab result={result} />}
            {activeTab === "json" && <JsonTab result={result} />}
          </div>
        </div>
      </div>

      {/* Right column */}
      <div className="w-72 flex-shrink-0 space-y-4">
        <RobotPanel status={robotStatus} />
        <CameraFeed />

        {/* Execute on Robot */}
        {result?.task_plan && (
          <div className="bg-white rounded-xl border border-gray-200 p-4 animate-slide-up">
            <h4 className="text-xs font-semibold text-gray-800 flex items-center gap-1.5 mb-3">
              <Play size={14} className="text-teal-600" /> Deploy to Robot
            </h4>

            {/* Feedback / adjustments */}
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Optional: add corrections or adjustments to the plan…"
              rows={2}
              className="w-full resize-none rounded-lg border border-gray-200 p-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-teal-400/40 focus:border-teal-400 placeholder:text-gray-300 mb-3"
            />

            <button
              onClick={handleDeploy}
              disabled={deploying || robotStatus === "running"}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                background: deploying || robotStatus === "running"
                  ? "#aaa"
                  : "linear-gradient(135deg, #37e0d8, #1a8a84)",
              }}
            >
              {deploying ? (
                <Loader2 size={15} className="animate-spin" />
              ) : robotStatus === "running" ? (
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <ArrowRight size={15} />
              )}
              {deploying ? "Sending…" : robotStatus === "running" ? "Executing…" : "Execute on Robot"}
            </button>

            {deployMessage && (
              <p className={`mt-2 text-xs ${deployMessage.startsWith("Error") ? "text-red-600" : "text-emerald-600"}`}>
                {deployMessage}
              </p>
            )}
          </div>
        )}

        <KBSummary docs={docs} />
      </div>
    </div>
  );
}

/* ========================================================================= */
/* Robot Panel                                                               */
/* ========================================================================= */

function RobotPanel({ status }: { status: string }) {
  const rows = [
    ["State", status === "running" ? "Executing…" : status === "complete" ? "Ready" : status === "error" ? "Error" : "Idle"],
    ["Position", "Home"],
    ["Tool", "Multimeter Probe"],
    ["Last Task", "—"],
    ["Uptime", "2h 14m"],
  ];

  return (
    <div className="rounded-xl p-5 text-white" style={{ background: "linear-gradient(135deg, #1a8a84 0%, #00695C 100%)" }}>
      <h3 className="text-sm font-semibold flex items-center gap-2 mb-4">
        <Cpu size={16} /> SO-ARM100 Status
      </h3>
      {rows.map(([label, value]) => (
        <div key={label} className="flex justify-between py-1.5 text-xs border-b border-white/15 last:border-0">
          <span className="text-white/70">{label}</span>
          <span className="font-semibold">{value}</span>
        </div>
      ))}
    </div>
  );
}

function CameraFeed() {
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const streamUrl = `${apiBase}/api/camera/stream`;
  const frameUrl = `${apiBase}/api/camera/frame`;
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [capturing, setCapturing] = useState(false);

  const captureSnapshot = async () => {
    setCapturing(true);
    try {
      const res = await fetch(frameUrl);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `robot-capture-${Date.now()}.jpg`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* ignore */
    } finally {
      setCapturing(false);
    }
  };

  const feed = (
    <div className={`rounded-xl overflow-hidden border-2 border-gray-800 bg-gray-900 aspect-video flex items-center justify-center relative ${expanded ? "w-full h-full rounded-none border-0" : ""}`}>
      <div className="absolute top-2 left-3 z-10 flex items-center gap-1.5 text-[10px] text-gray-500 bg-black/50 px-2 py-0.5 rounded-full">
        <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse-dot" />
        LIVE — CAM 1
      </div>
      <div className="absolute top-2 right-3 z-10 flex items-center gap-1">
        <button
          onClick={captureSnapshot}
          disabled={capturing || error}
          className="p-1 rounded bg-black/50 text-gray-400 hover:text-white hover:bg-black/70 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          title="Capture snapshot"
        >
          {capturing ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
        </button>
        <button
          onClick={() => setExpanded(!expanded)}
          className="p-1 rounded bg-black/50 text-gray-400 hover:text-white hover:bg-black/70 transition-colors cursor-pointer"
          title={expanded ? "Minimize" : "Expand"}
        >
          {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
      </div>
      {error ? (
        <span className="text-gray-600 text-sm flex items-center gap-1.5"><Camera size={16} /> Camera offline</span>
      ) : (
        <img
          src={streamUrl}
          alt="Robot camera feed"
          className={`w-full h-full ${expanded ? "object-contain" : "object-cover"}`}
          onError={() => setError(true)}
        />
      )}
    </div>
  );

  if (expanded) {
    return (
      <div
        className="fixed inset-0 z-50 bg-black flex items-center justify-center"
        onClick={() => setExpanded(false)}
      >
        <div className="w-full h-full" onClick={(e) => e.stopPropagation()}>
          {feed}
        </div>
      </div>
    );
  }

  return feed;
}

function KBSummary({ docs }: { docs: DocumentsResponse | null }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h4 className="text-xs font-semibold text-gray-800 flex items-center gap-1.5 mb-2">
        <BookOpen size={14} className="text-teal-600" /> Knowledge Base
      </h4>
      <div className="text-xs text-gray-500">
        <span className="font-bold text-gray-700">{docs?.stats.count ?? 0}</span> document(s) ·{" "}
        <span className="font-bold text-gray-700">{docs?.stats.total_images ?? 0}</span> diagrams
      </div>
    </div>
  );
}

/* ========================================================================= */
/* Plan Tab                                                                  */
/* ========================================================================= */

function PlanTab({ result }: { result: ExecuteResult | null }) {
  if (!result?.task_plan) {
    return <EmptyState icon={<Layers size={32} />} text="Execute a task to see the plan here." />;
  }

  const plan = result.task_plan.task_plan;
  const confidence = plan.confidence_score;
  const steps = plan.steps ?? [];
  const summary = plan.summary;
  const setup = plan.setup;

  return (
    <div className="animate-slide-up space-y-5">
      <div className="grid grid-cols-4 gap-3">
        <MetricCard label="Confidence" value={`${Math.round(confidence * 100)}%`} icon={<Gauge size={16} />} />
        <MetricCard label="Steps" value={String(steps.length)} icon={<Layers size={16} />} />
        <MetricCard label="Est. Duration" value={`${summary?.estimated_duration_seconds ?? "—"}s`} icon={<Clock size={16} />} />
        <MetricCard label="DUT" value={plan.equipment?.dut ?? "—"} icon={<Cpu size={16} />} />
      </div>

      <p className="text-sm font-medium text-gray-700">{plan.description}</p>

      {setup && (
        <details className="group">
          <summary className="cursor-pointer text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center gap-1">
            <ChevronRight size={14} className="group-open:rotate-90 transition-transform" /> Setup Requirements
          </summary>
          <div className="mt-2 grid grid-cols-3 gap-3 text-xs">
            <div className="bg-gray-50 rounded-lg p-3">
              <span className="text-gray-400 block mb-0.5">Mode</span>
              <span className="font-mono font-semibold text-gray-800">{setup.multimeter_mode}</span>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <span className="text-gray-400 block mb-0.5">Range</span>
              <span className="font-mono font-semibold text-gray-800">{setup.multimeter_range}</span>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <span className="text-gray-400 block mb-0.5">DUT Power</span>
              <span className="font-mono font-semibold text-gray-800">{setup.dut_power}</span>
            </div>
          </div>
          {setup.notes && (
            <p className="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2.5">{setup.notes}</p>
          )}
        </details>
      )}

      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Execution Sequence</h3>
        <div className="space-y-2">
          {steps.map((step) => <StepRow key={step.step_id} step={step} />)}
        </div>
      </div>

      {summary?.critical_checks?.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1">
            <AlertTriangle size={14} className="text-amber-500" /> Critical Checks
          </h3>
          <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
            {summary.critical_checks.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function StepRow({ step }: { step: Step }) {
  const params = step.parameters ?? {};
  const expected = params.expected_value;
  const meta: string[] = [];

  if (expected) {
    const range = expected.min != null && expected.max != null ? ` (${expected.min}–${expected.max} ${expected.unit ?? ""})` : "";
    if (expected.nominal != null) meta.push(`Expected: ${expected.nominal} ${expected.unit ?? ""}${range}`);
  }
  if (params.probe_positive) meta.push(`Probe+: ${params.probe_positive}`);
  if (params.probe_negative) meta.push(`Probe−: ${params.probe_negative}`);

  return (
    <div className="flex items-start gap-3 p-3 rounded-lg border border-gray-100 border-l-4 border-l-teal-400 bg-white hover:bg-teal-50/30 transition-colors">
      <div className="w-7 h-7 rounded-full bg-teal-500 text-white flex items-center justify-center text-xs font-bold flex-shrink-0">
        {step.step_id}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[11px] font-bold text-teal-700 uppercase tracking-wide">{step.action}</div>
        <div className="text-sm text-gray-800 mt-0.5">{step.description}</div>
        {meta.length > 0 && <div className="text-xs text-gray-400 mt-1">{meta.join(" · ")}</div>}
        <div className="flex gap-3 mt-2">
          {step.pass_criteria && (
            <span className="text-[11px] text-emerald-600 flex items-center gap-1">
              <CheckCircle2 size={12} /> {step.pass_criteria}
            </span>
          )}
          {step.fail_action && (
            <span className="text-[11px] text-red-500 flex items-center gap-1">
              <XCircle size={12} /> {step.fail_action}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ========================================================================= */
/* Sources Tab                                                               */
/* ========================================================================= */

function SourcesTab({ result }: { result: ExecuteResult | null }) {
  if (!result?.search_results?.length) {
    return <EmptyState icon={<Search size={32} />} text="Execute a task to see source documents here." />;
  }
  return (
    <div className="animate-slide-up space-y-4">
      {result.search_results.map((sr, i) => <SourceCard key={i} result={sr} />)}
    </div>
  );
}

function SourceCard({ result }: { result: SearchResult }) {
  const info = result.extracted_info;
  return (
    <details className="group border border-gray-200 rounded-xl overflow-hidden" open>
      <summary className="cursor-pointer bg-gray-50 px-5 py-3 flex items-center gap-2 text-sm font-semibold text-gray-800">
        <FileText size={16} className="text-teal-600" />
        {result.document_name}
        <ChevronRight size={14} className="ml-auto text-gray-400 group-open:rotate-90 transition-transform" />
      </summary>
      <div className="px-5 py-4 space-y-4">
        <p className="text-sm text-gray-500 italic">{result.task_understanding}</p>

        {info.specs?.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Specifications</h4>
            <div className="flex flex-wrap gap-1.5">
              {info.specs.map((s, j) => {
                const range = s.min && s.max ? ` (${s.min}–${s.max} ${s.unit ?? ""})` : "";
                return (
                  <span key={j} className="inline-block text-xs px-3 py-1.5 rounded-md bg-teal-50 text-teal-800 border border-teal-200 font-medium">
                    {s.name}: <strong>{s.value} {s.unit ?? ""}</strong>{range}
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {info.pins_involved?.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Pins</h4>
            <div className="flex flex-wrap gap-1.5">
              {info.pins_involved.map((p, j) => {
                const vr = p.voltage_range;
                const vStr = vr ? ` (${vr.min}–${vr.max} ${vr.unit})` : "";
                return (
                  <span key={j} className="inline-block text-xs px-3 py-1.5 rounded-md bg-amber-50 text-amber-800 border border-amber-200 font-medium">
                    📌 {p.pin_name}: {p.function}{vStr}
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {info.safety_warnings?.length > 0 && (
          <div className="space-y-1">
            {info.safety_warnings.map((w, j) => (
              <div key={j} className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2.5 flex items-start gap-1.5">
                <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" /> {w}
              </div>
            ))}
          </div>
        )}

        {info.procedures?.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Procedures</h4>
            <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
              {info.procedures.map((p, j) => <li key={j}>{p}</li>)}
            </ul>
          </div>
        )}

        {info.relevant_images?.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Relevant Diagrams</h4>
            <div className="grid grid-cols-3 gap-2">
              {info.relevant_images.map((img: string, j: number) => {
                // Extract just the filename — handle formats like:
                // "image_3.png", "arduino_uno_images/image_3.png",
                // "image_3.png — description text", "image_3"
                let imgName = img.split("/").pop() ?? img;
                // Strip anything after the filename (e.g. " — description")
                imgName = imgName.replace(/\s*[—–-]\s.*$/, "").trim();
                if (!imgName.endsWith(".png")) imgName += ".png";
                const clean = result.document_name.replace("_parsed", "");
                return (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    key={j}
                    src={imageUrl(clean, imgName)}
                    alt={imgName}
                    className="rounded-lg border border-gray-200 w-full object-contain bg-white p-1"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                );
              })}
            </div>
          </div>
        )}

        {info.additional_context && <p className="text-xs text-gray-400">{info.additional_context}</p>}
      </div>
    </details>
  );
}

/* ========================================================================= */
/* JSON Tab                                                                  */
/* ========================================================================= */

const KEYPOINT_COLORS = ["#00ff00", "#ff00ff", "#00ffff", "#ffff00", "#ff8800"];

function KeypointsTab({ result }: { result: ExecuteResult | null }) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [kpResult, setKpResult] = useState<KeypointResponse | null>(null);

  // Closed-loop state
  const [loopRunning, setLoopRunning] = useState(false);
  const [loopDryRun, setLoopDryRun] = useState(false);
  const [loopLog, setLoopLog] = useState<ClosedLoopIteration[]>([]);
  const [loopDone, setLoopDone] = useState<{ success: boolean; message: string } | null>(null);
  const [loopError, setLoopError] = useState("");
  const loopLogRef = useRef<HTMLDivElement>(null);

  const defaultPrompt = (() => {
    const steps = result?.task_plan?.task_plan?.steps ?? [];
    const probeStep = steps.find((s: Step) => ["PROBE", "MOVE", "MEASURE"].includes(s.action));
    if (!probeStep) return "";
    const pos = (probeStep.parameters as Record<string, string | undefined> | undefined)?.probe_positive;
    const neg = (probeStep.parameters as Record<string, string | undefined> | undefined)?.probe_negative;
    const parts = [pos, neg].filter(Boolean);
    return parts.length
      ? `Locate ${parts.join(" and ")} on the board, and the tip of the multimeter probe`
      : `Locate the target component and the tip of the multimeter probe`;
  })();

  const referenceImages = (result?.search_results ?? []).flatMap((sr) =>
    (sr.extracted_info?.relevant_images ?? []).map((img) => {
      const imgName = img.split("/").pop() ?? img;
      return {
        doc_name: sr.document_name.replace("_parsed", ""),
        image_name: imgName.endsWith(".png") ? imgName : imgName + ".png",
      };
    })
  );

  async function handleRun() {
    const p = prompt.trim() || defaultPrompt;
    if (!p) return;
    setLoading(true);
    setError("");
    setKpResult(null);
    try {
      const res = await locateKeypoints(p, referenceImages);
      setKpResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  async function handleStartLoop() {
    const p = prompt.trim() || defaultPrompt;
    if (!p) return;
    setLoopRunning(true);
    setLoopLog([]);
    setLoopDone(null);
    setLoopError("");
    try {
      await runClosedLoop(
        p,
        referenceImages,
        { dryRun: loopDryRun },
        {
          onIteration: (data) => {
            setLoopLog((prev) => [...prev, data]);
            setTimeout(() => {
              loopLogRef.current?.scrollTo({ top: loopLogRef.current.scrollHeight, behavior: "smooth" });
            }, 50);
          },
          onDone: (data) => setLoopDone(data),
          onError: (msg) => setLoopError(msg),
        },
      );
    } catch (e: unknown) {
      setLoopError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoopRunning(false);
    }
  }

  if (!result?.task_plan) {
    return <EmptyState icon={<Camera size={32} />} text="Execute a task first to enable keypoint localisation." />;
  }

  return (
    <div className="animate-slide-up space-y-5">
      {/* ── Prompt input ── */}
      <div className="space-y-2">
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Keypoint prompt
        </label>
        <textarea
          className="w-full text-sm border border-gray-200 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-teal-400 resize-none"
          rows={2}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={defaultPrompt || "e.g. locate the 5V LDO regulator and the multimeter probe tip"}
        />
        <div className="flex items-center gap-3 flex-wrap">
          {/* single-shot locate */}
          <button
            onClick={handleRun}
            disabled={loading || loopRunning}
            className="flex items-center gap-2 px-4 py-2 bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Camera size={14} />}
            {loading ? "Capturing & analysing…" : "Locate on Camera"}
          </button>

          {/* closed-loop run */}
          <button
            onClick={handleStartLoop}
            disabled={loading || loopRunning}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {loopRunning ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
            {loopRunning ? "Loop running…" : "Run Closed Loop"}
          </button>

          {/* dry-run toggle */}
          <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={loopDryRun}
              onChange={(e) => setLoopDryRun(e.target.checked)}
              className="rounded"
            />
            Dry run (no robot)
          </label>

          {referenceImages.length > 0 && (
            <span className="text-xs text-gray-400">
              {referenceImages.length} reference image{referenceImages.length !== 1 ? "s" : ""} from docs
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      {/* ── Single-shot result ── */}
      {kpResult && (
        <div className="space-y-4">
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Annotated Camera Frame</h4>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`data:image/png;base64,${kpResult.annotated_image}`}
              alt="Annotated camera frame with keypoints"
              className="w-full rounded-xl border border-gray-200 object-contain"
            />
          </div>

          {kpResult.keypoints.length > 0 ? (
            <div>
              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Detected Keypoints ({kpResult.keypoints.length})
              </h4>
              <div className="space-y-2">
                {kpResult.keypoints.map((kp, i) => (
                  <div key={i} className="flex items-center gap-3 px-4 py-3 rounded-xl border border-gray-200 bg-gray-50">
                    <span
                      className="w-3 h-3 rounded-full flex-shrink-0 border-2"
                      style={{ borderColor: KEYPOINT_COLORS[i % KEYPOINT_COLORS.length], backgroundColor: "black" }}
                    />
                    <span className="text-sm font-medium text-gray-800 flex-1">{kp.label}</span>
                    <span className="text-xs text-gray-400 font-mono">
                      norm ({kp.point[1]}, {kp.point[0]})
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="text-sm text-gray-400 text-center py-4">
              No keypoints detected &mdash; try rephrasing the prompt.
            </div>
          )}

          {(() => {
            const steps = result?.task_plan?.task_plan?.steps ?? [];
            const relevant = steps.filter((s: Step) =>
              ["PROBE", "MOVE", "MEASURE"].includes(s.action)
            );
            if (!relevant.length) return null;
            return (
              <div>
                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Planned Arm Movements
                </h4>
                <div className="space-y-2">
                  {relevant.map((s: Step, i: number) => (
                    <div key={i} className="flex gap-3 px-4 py-3 rounded-xl border border-teal-100 bg-teal-50">
                      <span className="text-xs font-bold text-teal-600 uppercase w-16 flex-shrink-0 pt-0.5">
                        {s.action}
                      </span>
                      <span className="text-sm text-gray-700">{s.description}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* ── Closed-loop log ── */}
      {(loopLog.length > 0 || loopDone || loopError) && (
        <div className="space-y-3">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Closed-loop log
          </h4>

          <div
            ref={loopLogRef}
            className="max-h-96 overflow-y-auto space-y-3 pr-1"
          >
            {loopLog.map((iter, i) => (
              <div
                key={i}
                className={`rounded-xl border p-3 space-y-2 ${
                  iter.action === "place"
                    ? "border-green-200 bg-green-50"
                    : "border-gray-200 bg-gray-50"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-gray-400">#{iter.iteration}</span>
                  <span
                    className={`text-xs font-bold uppercase px-2 py-0.5 rounded-full ${
                      iter.action === "place"
                        ? "bg-green-600 text-white"
                        : "bg-indigo-100 text-indigo-700"
                    }`}
                  >
                    {iter.action}
                  </span>
                  {iter.action === "place" && iter.confidence !== undefined && (
                    <span className="text-xs text-green-700 font-medium">
                      conf {(iter.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                  {!iter.pose_available && (
                    <span className="text-xs text-amber-600">no pose</span>
                  )}
                  {iter.cam_height_mm !== null && iter.cam_height_mm !== undefined && (
                    <span className="text-xs text-gray-400 font-mono ml-auto">
                      h={iter.cam_height_mm.toFixed(0)} mm
                    </span>
                  )}
                </div>

                {iter.action === "look" && iter.reason && (
                  <p className="text-xs text-gray-500 italic">{iter.reason}</p>
                )}
                {iter.action === "place" && iter.label && (
                  <p className="text-xs text-green-700 font-medium">{iter.label}</p>
                )}

                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`data:image/png;base64,${iter.annotated_image}`}
                  alt={`Iteration ${iter.iteration}`}
                  className="w-full rounded-lg border border-gray-200 object-contain"
                />
              </div>
            ))}
          </div>

          {loopDone && (
            <div
              className={`flex items-center gap-2 px-4 py-3 rounded-xl border text-sm font-medium ${
                loopDone.success
                  ? "border-green-200 bg-green-50 text-green-800"
                  : "border-red-200 bg-red-50 text-red-800"
              }`}
            >
              {loopDone.success ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
              {loopDone.message}
            </div>
          )}

          {loopError && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
              {loopError}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ========================================================================= */

function JsonTab({ result }: { result: ExecuteResult | null }) {
  if (!result) return <EmptyState icon={<Code2 size={32} />} text="Execute a task to see raw JSON here." />;
  return (
    <div className="animate-slide-up space-y-4">
      {result.task_plan && (
        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Task Plan</h4>
          <pre className="text-xs bg-gray-50 border border-gray-200 rounded-lg p-4 overflow-x-auto max-h-96 overflow-y-auto">
            {JSON.stringify(result.task_plan, null, 2)}
          </pre>
        </div>
      )}
      {result.search_results?.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Search Results</h4>
          <pre className="text-xs bg-gray-50 border border-gray-200 rounded-lg p-4 overflow-x-auto max-h-96 overflow-y-auto">
            {JSON.stringify(result.search_results, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

/* ========================================================================= */
/* Arm Control (IK/FK) Page                                                  */
/* ========================================================================= */

const JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"];
const HOME_JOINTS = [0, -90, 90, 90, -90, 90];

function IKPage() {
  const [joints, setJoints] = useState<number[]>(HOME_JOINTS);
  const [ee, setEE] = useState<EEPosition | null>(null);
  const [targetX, setTargetX] = useState("0.0");
  const [targetY, setTargetY] = useState("-0.2");
  const [targetZ, setTargetZ] = useState("0.15");
  const [useOrientation, setUseOrientation] = useState(false);
  const [targetRoll, setTargetRoll] = useState("90");
  const [targetPitch, setTargetPitch] = useState("0");
  const [targetYaw, setTargetYaw] = useState("0");
  const [ikResult, setIkResult] = useState<IKResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [violations, setViolations] = useState<string[]>([]);
  const [mode, setMode] = useState<"fk" | "ik">("fk");

  // Motor connection state
  const [robotConnected, setRobotConnected] = useState(false);
  const [robotPort, setRobotPort] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendStatus, setSendStatus] = useState<string | null>(null);
  const [livePositions, setLivePositions] = useState<Record<string, number> | null>(null);
  const [robotSpeed, setRobotSpeed] = useState(10); // 1-100 (default 10 = slow & safe)

  // Check robot connection on mount & poll status
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const s = await motorStatus();
        setRobotConnected(s.connected);
        setRobotPort(s.port);
        if (s.connected && s.positions_deg) {
          setLivePositions(s.positions_deg);
        }
      } catch { /* ignore */ }
    };
    checkStatus();
    const interval = setInterval(checkStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  // Load home position on mount
  useEffect(() => {
    getHomePosition().then((home) => {
      setJoints(home.joints_deg);
      setEE(home.ee_position);
      setTargetX(home.ee_position.x.toFixed(4));
      setTargetY(home.ee_position.y.toFixed(4));
      setTargetZ(home.ee_position.z.toFixed(4));
      setTargetRoll(home.ee_position.roll.toFixed(1));
      setTargetPitch(home.ee_position.pitch.toFixed(1));
      setTargetYaw(home.ee_position.yaw.toFixed(1));
    }).catch(() => {});
  }, []);

  const runFK = async (j?: number[]) => {
    setLoading(true);
    setError(null);
    try {
      const res = await forwardKinematics(j ?? joints);
      setEE(res.ee_position);
      setViolations(res.joint_violations);
      setTargetX(res.ee_position.x.toFixed(4));
      setTargetY(res.ee_position.y.toFixed(4));
      setTargetZ(res.ee_position.z.toFixed(4));
      setTargetRoll(res.ee_position.roll.toFixed(1));
      setTargetPitch(res.ee_position.pitch.toFixed(1));
      setTargetYaw(res.ee_position.yaw.toFixed(1));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "FK failed");
    } finally {
      setLoading(false);
    }
  };

  const runIK = async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Parameters<typeof inverseKinematics>[0] = {
        x: parseFloat(targetX),
        y: parseFloat(targetY),
        z: parseFloat(targetZ),
        init_joints_deg: joints,
      };
      if (useOrientation) {
        params.roll = parseFloat(targetRoll);
        params.pitch = parseFloat(targetPitch);
        params.yaw = parseFloat(targetYaw);
      }
      const res = await inverseKinematics(params);
      setIkResult(res);
      setJoints(res.joints_deg);
      setEE(res.ee_position);
      setViolations(res.joint_violations);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "IK failed");
    } finally {
      setLoading(false);
    }
  };

  const goHome = () => {
    setJoints(HOME_JOINTS);
    setIkResult(null);
    runFK(HOME_JOINTS);
  };

  const updateJoint = (idx: number, val: number) => {
    const next = [...joints];
    next[idx] = val;
    setJoints(next);
  };

  const handleConnect = async () => {
    setConnecting(true);
    setError(null);
    try {
      const res = await motorConnect();
      setRobotConnected(true);
      setRobotPort(res.port);
      setSendStatus(`Connected on ${res.port}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    setConnecting(true);
    try {
      await motorDisconnect();
      setRobotConnected(false);
      setRobotPort(null);
      setLivePositions(null);
      setSendStatus("Disconnected");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Disconnect failed");
    } finally {
      setConnecting(false);
    }
  };

  const handleSendToRobot = async () => {
    setSending(true);
    setSendStatus(null);
    setError(null);
    try {
      const res = await motorMove(joints, robotSpeed);
      setSendStatus(`Sent to ${res.motors_moved.length} motors`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to send to robot");
    } finally {
      setSending(false);
    }
  };

  const handleReadFromRobot = async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await motorStatus();
      if (s.positions_list && s.positions_list.length === 6) {
        setJoints(s.positions_list);
        setLivePositions(s.positions_deg);
        await runFK(s.positions_list);
        setSendStatus("Read positions from robot");
      } else {
        setError("Could not read positions");
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Read failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Mode toggle */}
      <div className="flex items-center gap-3">
        <div className="inline-flex rounded-lg bg-gray-100 p-1">
          <button
            onClick={() => setMode("fk")}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
              mode === "fk" ? "bg-white text-teal-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Forward Kinematics
          </button>
          <button
            onClick={() => setMode("ik")}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
              mode === "ik" ? "bg-white text-teal-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Inverse Kinematics
          </button>
        </div>
        <button
          onClick={goHome}
          className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-500 hover:text-teal-600 hover:bg-teal-50 rounded-lg transition-colors"
        >
          <RotateCcw size={14} /> Home Position
        </button>
      </div>

      {/* Robot connection bar */}
      <div className={`flex items-center justify-between p-3 rounded-xl border shadow-sm ${
        robotConnected ? "bg-emerald-50 border-emerald-200" : "bg-gray-50 border-gray-200"
      }`}>
        <div className="flex items-center gap-3">
          {robotConnected ? (
            <Wifi size={16} className="text-emerald-600" />
          ) : (
            <WifiOff size={16} className="text-gray-400" />
          )}
          <span className={`text-sm font-medium ${robotConnected ? "text-emerald-700" : "text-gray-500"}`}>
            {robotConnected ? `Robot connected on ${robotPort}` : "Robot not connected"}
          </span>
          {livePositions && robotConnected && (
            <span className="text-xs text-gray-400 ml-2">
              Live: [{Object.values(livePositions).map(v => v.toFixed(0)).join(", ")}]°
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {robotConnected && (
            <>
              <button
                onClick={handleReadFromRobot}
                disabled={loading}
                className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1.5"
              >
                <Download size={12} /> Read
              </button>
              <div className="flex items-center gap-2 px-2 py-1 bg-gray-50 rounded-lg border border-gray-200">
                <span className="text-[10px] font-medium text-gray-500 whitespace-nowrap">Speed</span>
                <input
                  type="range"
                  min={1}
                  max={100}
                  value={robotSpeed}
                  onChange={e => {
                    const v = Number(e.target.value);
                    setRobotSpeed(v);
                    motorSetSpeed(v).catch(() => {});
                  }}
                  className="w-20 h-1 accent-[#37e0d8] cursor-pointer"
                />
                <span className="text-[10px] font-mono text-gray-600 w-7 text-right">{robotSpeed}</span>
              </div>
              <button
                onClick={async () => {
                  setSending(true); setSendStatus(null); setError(null);
                  try {
                    const res = await motorMove([3, -26, -7, 92, -65, 39], robotSpeed);
                    setSendStatus(`Home: moved ${res.motors_moved.length} motors`);
                    setJoints([3, -26, -7, 92, -65, 39]);
                  } catch (e: unknown) { setError(e instanceof Error ? e.message : 'Home failed'); }
                  finally { setSending(false); }
                }}
                disabled={sending}
                className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1.5"
              >
                <Home size={12} /> Home
              </button>
              <button
                onClick={handleSendToRobot}
                disabled={sending}
                className="px-3 py-1.5 text-xs font-medium text-white rounded-lg transition-colors flex items-center gap-1.5"
                style={{ background: sending ? "#9ca3af" : "#37e0d8" }}
              >
                {sending ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                Send to Robot
              </button>
            </>
          )}
          <button
            onClick={robotConnected ? handleDisconnect : handleConnect}
            disabled={connecting}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors flex items-center gap-1.5 ${
              robotConnected
                ? "text-red-600 bg-white border border-red-200 hover:bg-red-50"
                : "text-white"
            }`}
            style={!robotConnected ? { background: connecting ? "#9ca3af" : "#37e0d8" } : undefined}
          >
            {connecting ? (
              <Loader2 size={12} className="animate-spin" />
            ) : robotConnected ? (
              <Unplug size={12} />
            ) : (
              <Plug size={12} />
            )}
            {robotConnected ? "Disconnect" : "Connect"}
          </button>
        </div>
      </div>
      {sendStatus && (
        <div className="flex items-center gap-2 p-2 text-xs text-teal-700 bg-teal-50 border border-teal-200 rounded-lg">
          <CheckCircle2 size={14} /> {sendStatus}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Joint angles panel */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-gray-100 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <Gauge size={16} className="text-teal-500" /> Joint Angles
            </h3>
            {mode === "fk" && (
              <button
                onClick={() => runFK()}
                disabled={loading}
                className="px-3 py-1.5 text-xs font-medium text-white rounded-lg transition-colors flex items-center gap-1.5"
                style={{ background: loading ? "#9ca3af" : "#37e0d8" }}
              >
                {loading ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
                Compute FK
              </button>
            )}
          </div>
          <div className="p-4 space-y-3">
            {JOINT_NAMES.map((name, i) => (
              <div key={name} className="flex items-center gap-3">
                <label className="text-xs font-mono text-gray-500 w-28 truncate">{name}</label>
                <input
                  type="range"
                  min={-180}
                  max={180}
                  step={0.5}
                  value={joints[i] ?? 0}
                  onChange={(e) => updateJoint(i, parseFloat(e.target.value))}
                  className="flex-1 h-1.5 accent-teal-500"
                />
                <input
                  type="number"
                  step={1}
                  value={joints[i]?.toFixed(1) ?? "0"}
                  onChange={(e) => updateJoint(i, parseFloat(e.target.value) || 0)}
                  className="w-20 px-2 py-1 text-xs font-mono border border-gray-200 rounded text-right"
                />
                <span className="text-[10px] text-gray-400 w-4">deg</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: End-effector panel */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-gray-100 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <Crosshair size={16} className="text-teal-500" /> End-Effector Position
            </h3>
            {mode === "ik" && (
              <button
                onClick={runIK}
                disabled={loading}
                className="px-3 py-1.5 text-xs font-medium text-white rounded-lg transition-colors flex items-center gap-1.5"
                style={{ background: loading ? "#9ca3af" : "#37e0d8" }}
              >
                {loading ? <Loader2 size={12} className="animate-spin" /> : <Crosshair size={12} />}
                Solve IK
              </button>
            )}
          </div>
          <div className="p-4 space-y-4">
            {/* Position */}
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">Position (metres)</p>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: "X", val: targetX, set: setTargetX },
                  { label: "Y", val: targetY, set: setTargetY },
                  { label: "Z", val: targetZ, set: setTargetZ },
                ].map(({ label, val, set }) => (
                  <div key={label}>
                    <label className="text-[10px] text-gray-400 uppercase tracking-wider">{label}</label>
                    <input
                      type="number"
                      step={0.01}
                      value={val}
                      onChange={(e) => set(e.target.value)}
                      disabled={mode === "fk"}
                      className="w-full mt-0.5 px-2 py-1.5 text-sm font-mono border border-gray-200 rounded focus:ring-1 focus:ring-teal-400 focus:border-teal-400 disabled:bg-gray-50"
                    />
                  </div>
                ))}
              </div>
            </div>
            {/* Orientation */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <p className="text-xs font-medium text-gray-500">Orientation (degrees)</p>
                {mode === "ik" && (
                  <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={useOrientation}
                      onChange={(e) => setUseOrientation(e.target.checked)}
                      className="w-3.5 h-3.5 accent-teal-500"
                    />
                    Track orientation
                  </label>
                )}
              </div>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: "Roll", val: targetRoll, set: setTargetRoll },
                  { label: "Pitch", val: targetPitch, set: setTargetPitch },
                  { label: "Yaw", val: targetYaw, set: setTargetYaw },
                ].map(({ label, val, set }) => (
                  <div key={label}>
                    <label className="text-[10px] text-gray-400 uppercase tracking-wider">{label}</label>
                    <input
                      type="number"
                      step={1}
                      value={val}
                      onChange={(e) => set(e.target.value)}
                      disabled={mode === "fk" || (mode === "ik" && !useOrientation)}
                      className="w-full mt-0.5 px-2 py-1.5 text-sm font-mono border border-gray-200 rounded focus:ring-1 focus:ring-teal-400 focus:border-teal-400 disabled:bg-gray-50"
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* Current EE readout */}
            {ee && (
              <div className="mt-3 p-3 rounded-lg bg-gray-50 border border-gray-100">
                <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wider mb-1.5">Current End-Effector</p>
                <div className="grid grid-cols-3 gap-2 text-xs font-mono text-gray-700">
                  <span>x: {ee.x.toFixed(4)} m</span>
                  <span>y: {ee.y.toFixed(4)} m</span>
                  <span>z: {ee.z.toFixed(4)} m</span>
                  <span>roll: {ee.roll.toFixed(1)}&deg;</span>
                  <span>pitch: {ee.pitch.toFixed(1)}&deg;</span>
                  <span>yaw: {ee.yaw.toFixed(1)}&deg;</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Status bar */}
      {(error || (ikResult && mode === "ik") || violations.length > 0) && (
        <div className="space-y-2">
          {error && (
            <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              <XCircle size={16} /> {error}
            </div>
          )}
          {ikResult && mode === "ik" && (
            <div
              className={`flex items-center gap-2 p-3 rounded-lg border text-sm ${
                ikResult.success
                  ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                  : "bg-amber-50 border-amber-200 text-amber-700"
              }`}
            >
              {ikResult.success ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              IK {ikResult.success ? "converged" : "did not converge"} — position error: {ikResult.error_mm.toFixed(3)} mm
            </div>
          )}
          {violations.length > 0 && (
            <div className="flex items-start gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700">
              <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
              <div>
                <p className="font-medium">Joint limit violations:</p>
                <ul className="mt-1 list-disc list-inside text-xs">
                  {violations.map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Camera feed */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="p-4 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <Camera size={16} className="text-teal-500" /> Robot Camera
          </h3>
        </div>
        <div className="p-4">
          <CameraFeed />
        </div>
      </div>
    </div>
  );
}

/* ========================================================================= */
/* Knowledge Base Page                                                       */
/* ========================================================================= */

function KBPage({ docs, onUpload }: { docs: DocumentsResponse | null; onUpload: (files: FileList | null) => void }) {
  const [filter, setFilter] = useState("");
  const [processing, setProcessing] = useState<{ name: string; status: "uploading" | "parsing" | "done" | "error"; error?: string }[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const [docContent, setDocContent] = useState<{ name: string; content: string; images: string[]; size_kb: number } | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [docTab, setDocTab] = useState<"content" | "images">("content");

  const filtered = docs?.documents.filter(
    (d) => !filter || d.name.toLowerCase().includes(filter.toLowerCase())
  ) ?? [];

  const stats = docs?.stats ?? { count: 0, total_images: 0, total_size_kb: 0 };

  async function handleKBUpload(files: FileList | null) {
    if (!files || files.length === 0) return;
    const fileArr = Array.from(files);

    // Initialize processing state for all files
    setProcessing(fileArr.map((f) => ({ name: f.name, status: "uploading" as const })));

    for (let i = 0; i < fileArr.length; i++) {
      const file = fileArr[i];
      try {
        // Show uploading
        setProcessing((prev) => prev.map((p, j) => j === i ? { ...p, status: "uploading" } : p));

        // Brief pause so user sees the uploading state
        await new Promise((r) => setTimeout(r, 300));

        // Show parsing
        setProcessing((prev) => prev.map((p, j) => j === i ? { ...p, status: "parsing" } : p));

        await uploadDocument(file);

        // Done
        setProcessing((prev) => prev.map((p, j) => j === i ? { ...p, status: "done" } : p));
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Upload failed";
        setProcessing((prev) => prev.map((p, j) => j === i ? { ...p, status: "error", error: msg } : p));
      }
    }

    // Refresh docs list
    onUpload(null);

    // Clear processing after a moment
    setTimeout(() => setProcessing([]), 3000);
  }

  async function openDocument(docName: string) {
    setSelectedDoc(docName);
    setDocLoading(true);
    setDocTab("content");
    try {
      const data = await getDocumentContent(docName);
      setDocContent(data);
    } catch {
      setDocContent(null);
    } finally {
      setDocLoading(false);
    }
  }

  function closeDocument() {
    setSelectedDoc(null);
    setDocContent(null);
  }

  // If a document is open, show the viewer
  if (selectedDoc) {
    return (
      <div className="max-w-5xl mx-auto p-8 animate-slide-up">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={closeDocument}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-teal-600 transition-colors"
          >
            <ChevronRight size={16} className="rotate-180" />
            Back to Knowledge Base
          </button>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {/* Doc header */}
          <div className="px-6 py-4 border-b border-gray-200 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-teal-50 flex items-center justify-center text-teal-600 flex-shrink-0">
              <FileText size={20} />
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-bold text-gray-800">{selectedDoc}</h2>
              {docContent && (
                <p className="text-xs text-gray-400">{docContent.size_kb} KB · {docContent.images.length} diagram(s)</p>
              )}
            </div>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-200">
            <button
              onClick={() => setDocTab("content")}
              className={`flex items-center gap-1.5 px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
                docTab === "content" ? "border-teal-500 text-teal-700" : "border-transparent text-gray-400 hover:text-gray-600"
              }`}
            >
              <FileText size={14} /> Content
            </button>
            <button
              onClick={() => setDocTab("images")}
              className={`flex items-center gap-1.5 px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
                docTab === "images" ? "border-teal-500 text-teal-700" : "border-transparent text-gray-400 hover:text-gray-600"
              }`}
            >
              <Image size={14} /> Diagrams {docContent ? `(${docContent.images.length})` : ""}
            </button>
          </div>

          {/* Content */}
          <div className="p-6 max-h-[calc(100vh-300px)] overflow-y-auto">
            {docLoading ? (
              <div className="flex items-center justify-center py-16 gap-2 text-gray-400">
                <Loader2 size={20} className="animate-spin" />
                <span className="text-sm">Loading document…</span>
              </div>
            ) : !docContent ? (
              <div className="text-center py-16 text-gray-400 text-sm">Failed to load document.</div>
            ) : docTab === "content" ? (
              <div className="prose prose-sm max-w-none prose-headings:text-gray-800 prose-p:text-gray-600 prose-li:text-gray-600">
                <MarkdownContent content={docContent.content} />
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {docContent.images.length > 0 ? (
                  docContent.images.map((img) => (
                    <div key={img} className="rounded-lg border border-gray-200 overflow-hidden bg-gray-50">
                      <img
                        src={imageUrl(selectedDoc, img)}
                        alt={img}
                        className="w-full h-auto"
                        loading="lazy"
                      />
                      <div className="px-3 py-2 text-xs text-gray-500 truncate border-t border-gray-100">{img}</div>
                    </div>
                  ))
                ) : (
                  <div className="col-span-full text-center py-16 text-gray-400 text-sm">No diagrams extracted from this document.</div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-8 animate-slide-up">
      <h2 className="text-xl font-bold text-gray-800 mb-6 flex items-center gap-2">
        <BookOpen className="text-teal-600" size={22} /> Knowledge Base
      </h2>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <StatCard value={String(stats.count)} label="Documents" icon={<FileText size={18} />} />
        <StatCard value={String(stats.total_images)} label="Diagrams" icon={<Image size={18} />} />
        <StatCard value={`${stats.total_size_kb.toFixed(0)} KB`} label="Indexed Text" icon={<BarChart3 size={18} />} />
      </div>

      <div className="relative mb-5">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-300" />
        <input
          type="text"
          placeholder="Filter by name…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full pl-9 pr-4 py-2.5 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400/40 focus:border-teal-400 placeholder:text-gray-300"
        />
      </div>

      <div className="space-y-2 mb-8">
        {filtered.length > 0 ? (
          filtered.map((doc) => (
            <button
              key={doc.name}
              onClick={() => openDocument(doc.name)}
              className="w-full flex items-center gap-3 p-4 bg-white rounded-xl border border-gray-200 hover:border-teal-400 hover:bg-teal-50/30 transition-colors cursor-pointer text-left"
            >
              <div className="w-10 h-10 rounded-lg bg-teal-50 flex items-center justify-center text-teal-600 flex-shrink-0">
                <FileText size={20} />
              </div>
              <div className="flex-1">
                <div className="text-sm font-semibold text-gray-800">{doc.name}</div>
                <div className="text-xs text-gray-400">{doc.size_kb} KB · {doc.image_count} diagram(s)</div>
              </div>
              <ArrowRight size={16} className="text-gray-300" />
            </button>
          ))
        ) : filter ? (
          <p className="text-sm text-gray-400 text-center py-4">No documents matching &ldquo;{filter}&rdquo;</p>
        ) : (
          <p className="text-sm text-gray-400 text-center py-4">No documents loaded yet. Upload PDFs below.</p>
        )}
      </div>

      <label className="block border-2 border-dashed border-gray-200 rounded-xl p-8 text-center cursor-pointer hover:border-teal-400 hover:bg-teal-50/30 transition-colors">
        <Upload size={28} className="mx-auto text-gray-300 mb-2" />
        <p className="text-sm text-gray-500 font-medium">Drop PDF files here or click to upload</p>
        <p className="text-xs text-gray-300 mt-1">Documents will be parsed and added to the knowledge base</p>
        <input type="file" accept=".pdf" multiple className="hidden" onChange={(e) => { handleKBUpload(e.target.files); e.target.value = ""; }} />
      </label>

      {/* Processing indicator */}
      {processing.length > 0 && (
        <div className="mt-5 bg-white rounded-xl border border-gray-200 overflow-hidden animate-slide-up">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
            <Loader2 size={16} className="text-teal-500 animate-spin" />
            <span className="text-sm font-semibold text-gray-700">Processing Documents</span>
          </div>
          <div className="divide-y divide-gray-50">
            {processing.map((p, i) => (
              <div key={i} className="px-5 py-3 flex items-center gap-3">
                {/* Status icon */}
                {p.status === "done" ? (
                  <CheckCircle2 size={18} className="text-emerald-500 flex-shrink-0" />
                ) : p.status === "error" ? (
                  <XCircle size={18} className="text-red-500 flex-shrink-0" />
                ) : (
                  <Loader2 size={18} className="text-teal-500 animate-spin flex-shrink-0" />
                )}

                {/* File info */}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-800 truncate">{p.name}</div>
                  <div className="text-xs text-gray-400">
                    {p.status === "uploading" && "Uploading file…"}
                    {p.status === "parsing" && "Parsing document & extracting images…"}
                    {p.status === "done" && "Successfully added to knowledge base"}
                    {p.status === "error" && (p.error ?? "Failed")}
                  </div>
                </div>

                {/* Progress bar */}
                {(p.status === "uploading" || p.status === "parsing") && (
                  <div className="w-24 h-1.5 bg-gray-100 rounded-full overflow-hidden flex-shrink-0">
                    <div
                      className={`h-full rounded-full transition-all duration-1000 ${
                        p.status === "uploading" ? "w-1/3 bg-teal-300" : "w-2/3 bg-teal-500"
                      }`}
                      style={{ animation: "progress-pulse 2s ease-in-out infinite" }}
                    />
                  </div>
                )}

                {p.status === "done" && (
                  <span className="text-[11px] text-emerald-600 font-medium flex-shrink-0">Done</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ========================================================================= */
/* AI Agent Chat Page                                                        */
/* ========================================================================= */

function AgentPage({ docs }: { docs: DocumentsResponse | null }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const SUGGESTIONS = [
    "What voltage does the Arduino 3.3V pin output?",
    "List all digital I/O pins and their functions",
    "What are the power consumption specs?",
    "Explain the USB connection pinout",
  ];

  async function handleSend() {
    const text = input.trim();
    if (!text || sending) return;

    const userMsg: ChatMessage = { role: "user", content: text };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInput("");
    setSending(true);

    try {
      const res = await chatWithAgent(text, messages);
      setMessages([...updatedMessages, { role: "assistant", content: res.reply }]);
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "Failed to get response";
      setMessages([...updatedMessages, { role: "assistant", content: `⚠️ Error: ${errMsg}` }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 ? (
          /* Welcome state */
          <div className="max-w-2xl mx-auto mt-12">
            <div className="text-center mb-10">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-teal-100 to-teal-50 flex items-center justify-center mx-auto mb-4">
                <Sparkles size={28} className="text-teal-600" />
              </div>
              <h2 className="text-xl font-bold text-gray-800 mb-2">DocOps AI Agent</h2>
              <p className="text-sm text-gray-400 max-w-md mx-auto">
                Ask questions about your uploaded documentation. I can find specs, explain pinouts,
                compare values, and help with troubleshooting.
              </p>
              {docs && (
                <p className="text-xs text-teal-600 mt-3 font-medium">
                  {docs.stats.count} document(s) • {docs.stats.total_images} diagrams indexed
                </p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => { setInput(s); }}
                  className="text-left p-4 rounded-xl border border-gray-200 hover:border-teal-400 hover:bg-teal-50/30 transition-colors group"
                >
                  <div className="flex items-start gap-2">
                    <MessageSquare size={14} className="text-gray-300 group-hover:text-teal-500 mt-0.5 flex-shrink-0" />
                    <span className="text-sm text-gray-600 group-hover:text-gray-800">{s}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Conversation */
          <div className="max-w-3xl mx-auto space-y-5">
            {messages.map((msg, i) => (
              <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"} animate-slide-up`}>
                {msg.role === "assistant" && (
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
                    <Bot size={16} className="text-white" />
                  </div>
                )}
                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-teal-600 text-white rounded-br-md"
                      : "bg-gray-100 text-gray-800 rounded-bl-md"
                  }`}
                >
                  {msg.role === "assistant" ? (
                    <div className="prose prose-sm max-w-none prose-headings:text-gray-800 prose-p:text-gray-700 prose-li:text-gray-700 prose-strong:text-gray-800 prose-code:bg-gray-200 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-teal-700 prose-pre:bg-gray-800 prose-pre:text-gray-100">
                      <MarkdownContent content={msg.content} />
                    </div>
                  ) : (
                    msg.content
                  )}
                </div>
                {msg.role === "user" && (
                  <div className="w-8 h-8 rounded-lg bg-gray-200 flex items-center justify-center flex-shrink-0 mt-1">
                    <User size={16} className="text-gray-500" />
                  </div>
                )}
              </div>
            ))}

            {/* Typing indicator */}
            {sending && (
              <div className="flex gap-3 animate-slide-up">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
                  <Bot size={16} className="text-white" />
                </div>
                <div className="bg-gray-100 rounded-2xl rounded-bl-md px-4 py-3">
                  <div className="flex gap-1.5">
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input bar */}
      <div className="border-t border-gray-200 bg-white px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex gap-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              placeholder="Ask about your documents…"
              disabled={sending}
              className="flex-1 px-4 py-3 rounded-xl border border-gray-200 text-sm focus:outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 disabled:opacity-50 disabled:bg-gray-50 placeholder:text-gray-300"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className="px-5 py-3 rounded-xl text-white text-sm font-semibold flex items-center gap-2 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ background: !input.trim() || sending ? "#ccc" : "linear-gradient(135deg, #37e0d8, #1a8a84)" }}
            >
              {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              Send
            </button>
          </div>
          <p className="text-[11px] text-gray-300 mt-2 text-center">
            Answers are generated from your uploaded documentation using Gemini AI
          </p>
        </div>
      </div>
    </div>
  );
}

/* Simple Markdown renderer */
function MarkdownContent({ content }: { content: string }) {
  // Basic markdown: bold, code blocks, inline code, headers, bullets, line breaks
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeLines: string[] = [];
  let codeKey = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith("```")) {
      if (inCodeBlock) {
        elements.push(
          <pre key={`code-${codeKey++}`} className="bg-gray-800 text-gray-100 rounded-lg p-3 text-xs overflow-x-auto my-2">
            <code>{codeLines.join("\n")}</code>
          </pre>
        );
        codeLines = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    if (!line.trim()) {
      elements.push(<br key={`br-${i}`} />);
      continue;
    }

    const formatted = formatInline(line);

    if (line.startsWith("### ")) {
      elements.push(<h3 key={i} className="font-bold text-sm mt-3 mb-1">{formatInline(line.slice(4))}</h3>);
    } else if (line.startsWith("## ")) {
      elements.push(<h2 key={i} className="font-bold text-base mt-3 mb-1">{formatInline(line.slice(3))}</h2>);
    } else if (line.startsWith("# ")) {
      elements.push(<h1 key={i} className="font-bold text-lg mt-3 mb-1">{formatInline(line.slice(2))}</h1>);
    } else if (line.match(/^[-*]\s/)) {
      elements.push(
        <div key={i} className="flex gap-2 ml-2">
          <span className="text-teal-500 mt-0.5">•</span>
          <span>{formatInline(line.replace(/^[-*]\s/, ""))}</span>
        </div>
      );
    } else if (line.match(/^\d+\.\s/)) {
      const num = line.match(/^(\d+)\./)?.[1];
      elements.push(
        <div key={i} className="flex gap-2 ml-2">
          <span className="text-teal-600 font-semibold text-xs mt-0.5">{num}.</span>
          <span>{formatInline(line.replace(/^\d+\.\s/, ""))}</span>
        </div>
      );
    } else {
      elements.push(<p key={i}>{formatted}</p>);
    }
  }

  return <>{elements}</>;
}

function formatInline(text: string): React.ReactNode {
  // Bold, inline code
  const parts: React.ReactNode[] = [];
  const regex = /(\*\*(.+?)\*\*|`([^`]+)`)/g;
  let lastIndex = 0;
  let match;
  let key = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[2]) {
      parts.push(<strong key={key++}>{match[2]}</strong>);
    } else if (match[3]) {
      parts.push(
        <code key={key++} className="bg-gray-200 px-1 py-0.5 rounded text-teal-700 text-xs">
          {match[3]}
        </code>
      );
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length === 1 ? parts[0] : <>{parts}</>;
}

/* ========================================================================= */
/* Shared                                                                    */
/* ========================================================================= */

function MetricCard({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 text-center">
      <div className="flex justify-center text-teal-600 mb-1">{icon}</div>
      <div className="text-lg font-bold text-teal-700">{value}</div>
      <div className="text-[10px] text-gray-400 uppercase tracking-wider">{label}</div>
    </div>
  );
}

function StatCard({ value, label, icon }: { value: string; label: string; icon: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 text-center">
      <div className="flex justify-center text-teal-600 mb-2">{icon}</div>
      <div className="text-2xl font-bold text-teal-700">{value}</div>
      <div className="text-xs text-gray-400 uppercase tracking-wide">{label}</div>
    </div>
  );
}

function EmptyState({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-48 text-gray-300">
      {icon}
      <p className="text-sm mt-2">{text}</p>
    </div>
  );
}
