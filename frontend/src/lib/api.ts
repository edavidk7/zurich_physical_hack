// ---------------------------------------------------------------------------
// API client for DocOps backend
// ---------------------------------------------------------------------------

import type { DocumentsResponse, ExecuteResult, ChatMessage, ChatResponse, PipelineStage, SearchResultEvent, SearchErrorEvent, RobotExecuteResponse, RunStepResponse, ConfirmMoveResponse, PendingMoveResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export async function getDocuments(): Promise<DocumentsResponse> {
  return apiFetch<DocumentsResponse>("/api/documents");
}

export async function uploadDocument(file: File): Promise<{ status: string; message: string }> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch("/api/documents/upload", { method: "POST", body: form });
}

export async function getDocumentContent(docName: string): Promise<{ name: string; content: string; images: string[]; size_kb: number }> {
  return apiFetch(`/api/documents/${encodeURIComponent(docName)}`);
}

export async function executeTask(task: string): Promise<ExecuteResult> {
  return apiFetch<ExecuteResult>("/api/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task }),
  });
}

export type StreamCallback = {
  onStage?: (stage: PipelineStage) => void;
  onSearchResult?: (result: SearchResultEvent) => void;
  onSearchError?: (err: SearchErrorEvent) => void;
  onDone?: (result: ExecuteResult) => void;
  onError?: (error: string) => void;
};

export async function executeTaskStream(
  task: string,
  callbacks: StreamCallback
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/execute/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task }),
  });

  if (!res.ok) {
    const body = await res.text();
    callbacks.onError?.(`API ${res.status}: ${body}`);
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    callbacks.onError?.("No response body");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let currentEvent = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        const data = JSON.parse(line.slice(6));
        switch (currentEvent) {
          case "stage":
            callbacks.onStage?.(data as PipelineStage);
            break;
          case "search_result":
            callbacks.onSearchResult?.(data as SearchResultEvent);
            break;
          case "search_error":
            callbacks.onSearchError?.(data as SearchErrorEvent);
            break;
          case "done":
            callbacks.onDone?.(data as ExecuteResult);
            break;
          case "error":
            callbacks.onError?.(data.message);
            break;
        }
      }
    }
  }
}

export function imageUrl(docName: string, imageName: string): string {
  return `${API_BASE}/api/documents/${encodeURIComponent(docName)}/images/${encodeURIComponent(imageName)}`;
}

export async function chatWithAgent(
  message: string,
  history: ChatMessage[]
): Promise<ChatResponse> {
  return apiFetch<ChatResponse>("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
  });
}

export async function executeOnRobot(
  taskPlan: Record<string, unknown>,
  feedback?: string
): Promise<RobotExecuteResponse> {
  return apiFetch<RobotExecuteResponse>("/api/robot/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_plan: taskPlan, feedback: feedback || null }),
  });
}

// ---------------------------------------------------------------------------
// Kinematics (FK / IK)
// ---------------------------------------------------------------------------

export interface EEPosition {
  x: number;
  y: number;
  z: number;
  roll_deg: number;
  pitch_deg: number;
  yaw_deg: number;
}

export interface FKResult {
  ee_position: EEPosition;
  joint_violations: string[];
}

export interface IKResult {
  joints_deg: Record<string, number>;
  joints_list: number[];
  ee_position: EEPosition;
  error_mm: number;
  success: boolean;
  joint_violations: string[];
}

export interface HomeResult {
  joints_deg: number[];
  joint_names: string[];
  ee_position: EEPosition;
}

export async function forwardKinematics(joints_deg: number[]): Promise<FKResult> {
  return apiFetch<FKResult>("/api/kinematics/fk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ joints_deg }),
  });
}

export async function inverseKinematics(params: {
  x: number;
  y: number;
  z: number;
  roll?: number;
  pitch?: number;
  yaw?: number;
  init_joints_deg?: number[];
  gripper_deg?: number;
}): Promise<IKResult> {
  return apiFetch<IKResult>("/api/kinematics/ik", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function getHomePosition(): Promise<HomeResult> {
  return apiFetch<HomeResult>("/api/kinematics/home");
}

export interface TooltipProjection {
  visible: boolean;
  u_norm: number;   // horizontal position in image, 0 = left, 1 = right
  v_norm: number;   // vertical position in image,   0 = top,  1 = bottom
  error?: string;
}

export async function getTooltipProjection(): Promise<TooltipProjection> {
  return apiFetch<TooltipProjection>("/api/camera/tooltip_projection");
}

// ---------------------------------------------------------------------------
// Motor Control
// ---------------------------------------------------------------------------

export interface MotorConnectResult {
  status: string;
  port: string;
  positions_deg?: Record<string, number> | null;
  error?: string;
}

export interface MotorStatusResult {
  connected: boolean;
  port: string | null;
  positions_deg: Record<string, number> | null;
  positions_list?: number[];
  error?: string;
}

export interface MotorMoveResult {
  status: string;
  motors_moved: string[];
}

export async function motorConnect(port?: string): Promise<MotorConnectResult> {
  return apiFetch<MotorConnectResult>("/api/motor/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ port: port || null }),
  });
}

export async function motorDisconnect(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/api/motor/disconnect", {
    method: "POST",
  });
}

export async function motorStatus(): Promise<MotorStatusResult> {
  return apiFetch<MotorStatusResult>("/api/motor/status");
}

export async function motorMove(joints_deg: number[], speed?: number): Promise<MotorMoveResult> {
  return apiFetch<MotorMoveResult>("/api/motor/move", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ joints_deg, speed: speed ?? null }),
  });
}

export async function motorSetSpeed(speed: number): Promise<{ status: string; speed: number }> {
  return apiFetch<{ status: string; speed: number }>("/api/motor/speed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speed }),
  });
}

export async function motorDetectPort(): Promise<{ port: string | null; detected: boolean }> {
  return apiFetch<{ port: string | null; detected: boolean }>("/api/motor/detect-port");
}

export async function motorEnableTorque(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/api/motor/torque/enable", { method: "POST" });
}

export async function motorDisableTorque(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/api/motor/torque/disable", { method: "POST" });
}

// ---------------------------------------------------------------------------
// Keypoint Localisation
// ---------------------------------------------------------------------------

export interface KeypointResponse {
  annotated_image: string;
  keypoints: { label: string; point: [number, number] }[];
  prompt: string;
  camera_size: [number, number];
}

export async function locateKeypoints(
  prompt: string,
  referenceImages: { doc_name: string; image_name: string }[],
  model = "gemini-3-flash-preview",
  thinkingBudget = 0,
  thinkingLevel?: string,   // "minimal" | "low" | "medium" | "high"
  temperature = 1.0,
): Promise<KeypointResponse> {
  return apiFetch<KeypointResponse>("/api/keypoints", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      reference_images: referenceImages,
      model,
      thinking_budget: thinkingBudget,
      thinking_level: thinkingLevel ?? null,
      temperature,
    }),
  });
}

export interface MoveToKeypointResult {
  delta_cam_mm: { dx: number; dy: number };
  delta_robot_m: { x: number; y: number; z: number };
  distance_m: number;
  cam_height_mm: number;
  dry_run: boolean;
  moved: boolean;
  message: string;
}

export async function moveToKeypoint(
  norm_y: number,
  norm_x: number,
  dryRun = false,
): Promise<MoveToKeypointResult> {
  return apiFetch<MoveToKeypointResult>("/api/robot/move-to-keypoint", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ norm_y: norm_y, norm_x: norm_x, dry_run: dryRun }),
  });
}

export async function executeStepKeypoints(
  step: Record<string, unknown>,
  referenceImages: { doc_name: string; image_name: string }[],
  model = "gemini-3-flash-preview",
  thinkingBudget = 0,
  thinkingLevel?: string,   // "minimal" | "low" | "medium" | "high"
  temperature = 1.0,
): Promise<KeypointResponse> {
  return apiFetch<KeypointResponse>("/api/execute/step-keypoints", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      step,
      reference_images: referenceImages,
      model,
      thinking_budget: thinkingBudget,
      thinking_level: thinkingLevel ?? null,
      temperature,
    }),
  });
}

// ---------------------------------------------------------------------------
// Run-Step Pipeline (automated: plan step → VLM → ArUco → IK → trajectory)
// ---------------------------------------------------------------------------

export async function runStep(
  step: Record<string, unknown>,
  referenceImages: { doc_name: string; image_name: string }[],
  options?: {
    model?: string;
    thinkingBudget?: number;
    thinkingLevel?: string;
    temperature?: number;
    planeOffsetM?: number;
    motionSteps?: number;
    speed?: number;
  },
): Promise<RunStepResponse> {
  return apiFetch<RunStepResponse>("/api/execute/run-step", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      step,
      reference_images: referenceImages,
      model: options?.model ?? "gemini-3-flash-preview",
      thinking_budget: options?.thinkingBudget ?? 0,
      thinking_level: options?.thinkingLevel ?? null,
      temperature: options?.temperature ?? 1.0,
      plane_offset_m: options?.planeOffsetM ?? 0.003,
      motion_steps: options?.motionSteps ?? 40,
      speed: options?.speed ?? 15,
    }),
  });
}

export async function confirmMove(speed?: number): Promise<ConfirmMoveResponse> {
  return apiFetch<ConfirmMoveResponse>("/api/execute/confirm-move", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speed: speed ?? null }),
  });
}

export async function getPendingMove(): Promise<PendingMoveResponse> {
  return apiFetch<PendingMoveResponse>("/api/execute/pending-move");
}

export async function cancelPendingMove(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/api/execute/pending-move", {
    method: "DELETE",
  });
}
