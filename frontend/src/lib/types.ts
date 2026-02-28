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
