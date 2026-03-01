// ---------------------------------------------------------------------------
// Shared types for DocOps
// ---------------------------------------------------------------------------

export interface Document {
  name: string;
  filename: string;
  size_kb: number;
  image_count: number;
}

export interface DocumentsResponse {
  documents: Document[];
  stats: {
    count: number;
    total_images: number;
    total_size_kb: number;
  };
}

export interface Spec {
  name: string;
  value: string;
  min?: string;
  max?: string;
  unit?: string;
  conditions?: string;
}

export interface Pin {
  pin_name: string;
  pin_number?: string;
  function: string;
  voltage_range?: { min: number; max: number; unit: string };
  notes?: string;
}

export interface ExtractedInfo {
  specs: Spec[];
  pins_involved: Pin[];
  procedures: string[];
  safety_warnings: string[];
  additional_context: string;
  relevant_images: string[];
}

export interface SearchResult {
  relevant: boolean;
  document_name: string;
  task_understanding: string;
  extracted_info: ExtractedInfo;
}

export interface Step {
  step_id: number;
  action: string;
  target?: string;
  description: string;
  parameters: {
    pin?: string;
    measurement_type?: string;
    expected_value?: {
      nominal?: number;
      min?: number;
      max?: number;
      unit?: string;
    };
    probe_positive?: string;
    probe_negative?: string;
  };
  pass_criteria: string;
  fail_action: string;
}

export interface TaskPlan {
  task_plan: {
    id: string;
    user_request: string;
    description: string;
    confidence_score: number;
    equipment: {
      robot: string;
      tool: string;
      dut: string;
    };
    setup: {
      multimeter_mode: string;
      multimeter_range: string;
      dut_power: string;
      notes?: string;
    };
    steps: Step[];
    summary: {
      total_steps: number;
      estimated_duration_seconds: number;
      critical_checks: string[];
    };
  };
}

export interface ExecuteResult {
  search_results: SearchResult[];
  task_plan: TaskPlan | null;
  errors?: { document?: string; stage?: string; error: string }[];
  message?: string;
}

// ---------------------------------------------------------------------------
// Pipeline progress events
// ---------------------------------------------------------------------------

export interface PipelineStage {
  stage: "init" | "searching" | "search_complete" | "planning" | "complete";
  message: string;
  document?: string;
  documents?: string[];
  progress?: number;
  relevant_count?: number;
  total?: number;
}

export interface SearchResultEvent {
  document: string;
  relevant: boolean;
  task_understanding?: string;
}

export interface SearchErrorEvent {
  document: string;
  error: string;
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  reply: string;
}

export interface RobotExecuteResponse {
  status: string;
  message: string;
  steps: number;
  feedback_applied: boolean;
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

// ---------------------------------------------------------------------------
// Run-Step Pipeline (automated: plan step -> VLM -> ArUco -> IK -> trajectory)
// ---------------------------------------------------------------------------

export interface RunStepResponse {
  status: "pending_confirmation";
  annotated_image: string;
  keypoints: { label: string; point: [number, number] }[];
  prompt: string;
  target_keypoint: { label: string; point: [number, number] } | null;
  probe_keypoint: { label: string; point: [number, number] } | null;
  pixel_uv: [number, number];
  pos_cam_m: [number, number, number];
  pos_board_m: [number, number, number];
  depth_m: number;
  target_robot_m: [number, number, number];
  current_tip_m: [number, number, number];
  delta_m: [number, number, number];
  distance_m: number;
  q_current_deg: Record<string, number>;
  q_target_deg: Record<string, number>;
  ik_error_m: number;
  motion_steps: number;
  n_markers: number;
  reprojection_err_px: number;
  camera_size: [number, number];
}

export interface ConfirmMoveResponse {
  status: "executed";
  waypoints_sent: number;
  speed: number;
  target_robot_m: [number, number, number];
  distance_m: number;
  final_positions_deg: Record<string, number> | null;
  step: Record<string, unknown>;
  message: string;
}

export interface PendingMoveResponse {
  has_pending: boolean;
  target_keypoint?: { label: string; point: [number, number] };
  target_robot_m?: [number, number, number];
  current_tip_m?: [number, number, number];
  distance_m?: number;
  q_target_deg?: Record<string, number>;
  motion_steps?: number;
  speed?: number;
  step?: Record<string, unknown>;
}
