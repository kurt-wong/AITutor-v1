/**
 * 集中类型定义
 * 
 * Phase 2 improvement: eliminates type duplication across pages.
 * All shared interfaces and constants defined here.
 */

// ═══ 通用常量 ═══

export const DIFFICULTY_LABELS: Record<number, string> = {
  1: "简单", 2: "基础", 3: "中等", 4: "困难", 5: "综合",
};
export const DIFFICULTY_COLORS: Record<number, string> = {
  1: "green", 2: "blue", 3: "orange", 4: "red", 5: "purple",
};
export const ERROR_COLORS: Record<string, string> = {
  conceptual: "red", calculation: "orange", careless: "gold", unknown: "default",
};
export const SUBJECTS = [
  { value: "数学", label: "数学" },
  { value: "物理", label: "物理" },
  { value: "化学", label: "化学" },
  { value: "英语", label: "英语" },
  { value: "语文", label: "语文" },
  { value: "生物", label: "生物" },
  { value: "历史", label: "历史" },
  { value: "地理", label: "地理" },
  { value: "道德与法治", label: "道德与法治" },
];
export const GRADES = [
  { value: "初一", label: "初一" },
  { value: "初二", label: "初二" },
  { value: "初三", label: "初三" },
  { value: "高一", label: "高一" },
  { value: "高二", label: "高二" },
  { value: "高三", label: "高三" },
];
export const CATEGORIES = [
  { value: "试卷", label: "试卷" },
  { value: "练习", label: "练习" },
  { value: "笔记", label: "笔记" },
  { value: "答案", label: "答案" },
  { value: "课件", label: "课件" },
  { value: "其他", label: "其他" },
];

/** Subject → color mapping (shared across StatisticsPage and other pages) */
export const SUBJECT_COLORS: Record<string, string> = {
  "数学": "#1890ff", "物理": "#52c41a", "化学": "#722ed1",
  "英语": "#fa8c16", "语文": "#eb2f96", "生物": "#13c2c2",
  "历史": "#f5222d", "地理": "#2f54eb", "道德与法治": "#faad14",
};

// ═══ 实体类型 ═══

export interface Document_ {
  id: number;
  filename: string;
  file_type: string;
  file_size: number;
  object_key: string;
  processing_status: string;
  subject: string | null;
  grade: string | null;
  category: string | null;
  created_at: string;
}

export interface DocumentListResponse {
  documents: Document_[];
  total: number;
}

export interface DocumentAnalysis {
  document: Document_;
  questions: {
    id: number;
    content: string;
    difficulty: number | null;
    question_number: number | null;
    source_type: string;
    /** Session #130: 1-based sequential display number within document */
    display_number?: number;
    /** Session #130: shared reading/experiment passage text */
    passage_text?: string | null;
  }[];
  questions_count: number;
  difficulty_distribution: Record<number, number>;
  comparison: {
    document: Document_;
    questions_count: number;
    difficulty_distribution: Record<number, number>;
  }[] | null;
}

export interface Question {
  id: number;
  document_id: number | null;
  subject_id: number | null;
  question_number: number | null;
  content: string;
  difficulty: number | null;
  source_type: string;
  created_at: string;
  /** Session #130: 1-based sequential display number within document */
  display_number?: number;
  /** Session #130: shared reading/experiment passage text */
  passage_text?: string | null;
}

export interface QuestionRow {
  id: number;
  content: string;
  difficulty: number | null;
  subject_id: number | null;
  created_at: string;
}

export interface SolutionData {
  final_answer: string;
  solution_steps: { step: number; description: string }[];
  knowledge_points?: string[];
  explanation: string;
}

export interface WrongQuestion {
  id: number;
  question_id: number;
  question_content?: string;
  error_type: string;
  wrong_count: number;
  image_key: string | null;
  mastery_level?: number;
  review_count?: number;
  subject?: string | null;
  difficulty?: number | null;
  created_at: string | null;
}

export interface KnowledgeNode {
  id: number;
  name: string;
  code: string;
  parent_id: number | null;
}

export interface CostRecord {
  id: number;
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  created_at: string;
}

export interface TrainingSet {
  id: number;
  title: string;
  generation_type: string;
  subject: string | null;
  topic: string | null;
  question_count: number;
  questions?: TrainingQuestion[];
}

export interface TrainingQuestion {
  question_id: number;
  content: string;
  question_type: string | null;
  subject_id: number | null;
  image_key: string | null;
  difficulty: number | null;
  answer: string | null;
  solution_steps: { step: number; description: string }[] | null;
  explanation: string | null;
}

export interface SubmitResult {
  total: number;
  correct: number;
  results: {
    question_id: number;
    content: string;
    question_type: string | null;
    student_answer: string;
    correct_answer: string;
    is_correct: boolean | null;
    explanation: string | null;
    solution_steps: { step: number; description: string }[] | null;
  }[];
}

export interface Exam {
  id: number;
  title: string;
  subject: string | null;
  question_count: number;
  duration_minutes: number;
}

// ═══ SSE 事件（判别联合类型） ═══

/** Base fields common to all SSE events */
interface SSEEventBase {
  phase: string;
  session_id?: string;
  student_question_id?: number;
}

/** Processing status event */
export interface SSEProcessingEvent extends SSEEventBase {
  phase: "processing" | "processing_done";
  step?: string;
  message?: string;
  success?: boolean;
  question_text?: string;
  vision_error?: string;
}

/** Hint delivered event */
export interface SSEHintEvent extends SSEEventBase {
  phase: "hint";
  thinking_hint?: string;
  difficulty?: number;
  student_question_id: number;
}

/** Waiting for student choice */
export interface SSEChoosingEvent extends SSEEventBase {
  phase: "choosing" | "done";
}

/** Solution delivered event */
export interface SSESolutionEvent extends SSEEventBase {
  phase: "solution";
  solution: SolutionData;
}

/** Error event */
export interface SSEErrorEvent extends SSEEventBase {
  phase: "error";
  error_code?: string;
  message: string;
  fallback_options?: string[];
}

/** Thinking prompt event (student chose "think first") */
export interface SSEThinkingEvent extends SSEEventBase {
  phase: "thinking";
  message: string;
}

/** Question reveal event (student confirms extracted question text) */
export interface SSERevealEvent extends SSEEventBase {
  phase: "question_reveal";
  question_text: string;
  questions?: { index: number; text: string; label: string; images?: string[] }[];
  is_exam?: boolean;
  images?: string[];
}

export type SSEEvent =
  | SSEProcessingEvent
  | SSEHintEvent
  | SSEChoosingEvent
  | SSESolutionEvent
  | SSEErrorEvent
  | SSEThinkingEvent
  | SSERevealEvent;

// ═══ 学生 QuestionRecord ═══

export interface QuestionRecord {
  id: number;
  text: string;
  image: string | null;
  status: "asking" | "processing" | "revealing" | "hint" | "choosing" | "thinking" | "solving" | "done" | "error";
  sessionId?: string;
  hint?: string;
  difficulty?: number;
  solution?: SolutionData;
  error?: string;
  studentQuestionId?: number;
  examQuestions?: { index: number; text: string; label: string; images?: string[] }[];
  images?: string[];  // MinIO object keys for figure images
}
