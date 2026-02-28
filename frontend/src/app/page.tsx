"use client";

import { useState, useEffect } from "react";
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
} from "lucide-react";

import {
  getDocuments,
  uploadDocument,
  executeTask,
  imageUrl,
} from "@/lib/api";

import type {
  DocumentsResponse,
  ExecuteResult,
  SearchResult,
  Step,
} from "@/lib/types";

// ===========================================================================
// Main App
// ===========================================================================

export default function Home() {
  const [page, setPage] = useState<"task" | "kb">("task");
  const [docs, setDocs] = useState<DocumentsResponse | null>(null);
  const [result, setResult] = useState<ExecuteResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [taskInput, setTaskInput] = useState("");
  const [activeTab, setActiveTab] = useState<"plan" | "sources" | "json">("plan");
  const [robotStatus, setRobotStatus] = useState<"idle" | "running" | "complete" | "error">("idle");

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
    setStatusMessage("Searching documents for relevant specifications…");
    setActiveTab("plan");
    try {
      const res = await executeTask(taskInput.trim());
      setResult(res);
      setRobotStatus(res.task_plan ? "complete" : "error");
      setStatusMessage("");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setStatusMessage(`Error: ${msg}`);
      setRobotStatus("error");
    } finally {
      setLoading(false);
    }
  }

  async function handleUpload(files: FileList | null) {
    if (!files) return;
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
            {page === "task" ? "⚙️ Task Execution" : "📚 Knowledge Base"}
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
              onExecute={handleExecute}
              docs={docs}
            />
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
  result, activeTab, setActiveTab, robotStatus, onExecute, docs,
}: {
  taskInput: string;
  setTaskInput: (v: string) => void;
  examples: string[];
  loading: boolean;
  statusMessage: string;
  result: ExecuteResult | null;
  activeTab: "plan" | "sources" | "json";
  setActiveTab: (v: "plan" | "sources" | "json") => void;
  robotStatus: string;
  onExecute: () => void;
  docs: DocumentsResponse | null;
}) {
  return (
    <div className="flex gap-6 p-6 h-full">
      {/* Left column */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Task input */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
            <FileText size={16} className="text-teal-600" /> Task Definition
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

          <div className="flex items-center justify-between mt-3">
            <span className="text-xs text-gray-400">{docs?.stats.count ?? 0} document(s) will be searched</span>
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
            {activeTab === "json" && <JsonTab result={result} />}
          </div>
        </div>
      </div>

      {/* Right column */}
      <div className="w-72 flex-shrink-0 space-y-4">
        <RobotPanel status={robotStatus} />
        <CameraFeed />
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
  return (
    <div className="rounded-xl overflow-hidden border-2 border-gray-800 bg-gray-900 aspect-video flex items-center justify-center relative">
      <div className="absolute top-2 left-3 flex items-center gap-1.5 text-[10px] text-gray-500">
        <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse-dot" />
        LIVE — CAM 1
      </div>
      <span className="text-gray-600 text-sm flex items-center gap-1.5"><Camera size={16} /> Camera feed</span>
    </div>
  );
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
              {info.relevant_images.map((img, j) => {
                let imgName = img.split("/").pop() ?? img;
                if (!imgName.endsWith(".png")) imgName += ".png";
                const clean = result.document_name.replace("_parsed", "");
                return (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    key={j}
                    src={imageUrl(clean, imgName)}
                    alt={imgName}
                    className="rounded-lg border border-gray-200 w-full object-contain"
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
/* Knowledge Base Page                                                       */
/* ========================================================================= */

function KBPage({ docs, onUpload }: { docs: DocumentsResponse | null; onUpload: (files: FileList | null) => void }) {
  const [filter, setFilter] = useState("");

  const filtered = docs?.documents.filter(
    (d) => !filter || d.name.toLowerCase().includes(filter.toLowerCase())
  ) ?? [];

  const stats = docs?.stats ?? { count: 0, total_images: 0, total_size_kb: 0 };

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
            <div key={doc.name} className="flex items-center gap-3 p-4 bg-white rounded-xl border border-gray-200 hover:border-teal-400 transition-colors">
              <div className="w-10 h-10 rounded-lg bg-teal-50 flex items-center justify-center text-teal-600 flex-shrink-0">
                <FileText size={20} />
              </div>
              <div className="flex-1">
                <div className="text-sm font-semibold text-gray-800">{doc.name}</div>
                <div className="text-xs text-gray-400">{doc.size_kb} KB · {doc.image_count} diagram(s)</div>
              </div>
              <ArrowRight size={16} className="text-gray-300" />
            </div>
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
        <input type="file" accept=".pdf" multiple className="hidden" onChange={(e) => onUpload(e.target.files)} />
      </label>
    </div>
  );
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
