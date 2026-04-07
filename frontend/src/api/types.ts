export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  username: string;
  display_name: string;
  department: string;
  section: string;
}

export interface UserInfo {
  username: string;
  display_name: string;
  department: string;
  section: string;
}

export interface DocumentItem {
  id: number;
  filename: string;
  department: string;
  section: string;
  uploaded_by: string;
  status: string;
  file_hash: string;
  raw_path: string;
  redacted_path: string;
  index_path: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentContent {
  filename: string;
  content: string;
  version: string;
}

export interface RuleItem {
  id: number;
  department: string;
  rule_name: string;
  rule_description: string;
  rule_type: string;
  priority: number;
  is_active: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface RuleCreate {
  department: string;
  rule_name: string;
  rule_description: string;
  rule_type: string;
  priority: number;
  is_active: boolean;
}

export interface IndexRuleItem {
  id: number;
  department: string;
  rule_name: string;
  rule_description: string;
  rule_type: string;
  target_departments: string[];
  priority: number;
  is_active: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface IndexRuleCreate {
  department: string;
  rule_name: string;
  rule_description: string;
  rule_type: string;
  target_departments: string[];
  priority: number;
  is_active: boolean;
}

export interface PromptFile {
  filename: string;
  content: string;
}

export interface BatchSummary {
  id: number;
  batch_id: string;
  status: string;
  total_files: number;
  success_count: number;
  fail_count: number;
  started_at: string;
  finished_at: string;
}

export interface BatchFileLogItem {
  id: number;
  document_id: number;
  step: string;
  status: string;
  error_message: string;
  duration_ms: number;
  created_at: string;
}

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  size: number;
  items: T[];
}
