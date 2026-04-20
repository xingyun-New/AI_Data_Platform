export interface LoginRequest {
  username: string;
  password: string;
}

export type RoleName = 'SYS_ADMIN' | 'BE_CROSS' | 'DEPT_PIC' | 'MEMBER';

export interface RoleBinding {
  role: RoleName;
  department_id: number | null;
  department_code?: string | null;
}

export interface LoginResponse {
  token: string;
  username: string;
  display_name: string;
  department: string;
  section: string;
  roles: RoleBinding[];
}

export interface UserInfo {
  username: string;
  display_name: string;
  department: string;
  section: string;
  roles?: RoleBinding[];
}

export interface RoleBindingOut extends RoleBinding {
  id: number;
  granted_by?: string;
  granted_at?: string;
}

export interface UserOut {
  id: number;
  username: string;
  display_name: string;
  department: string;
  section: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string | null;
  roles: RoleBindingOut[];
}

export interface DepartmentOut {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
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
  knowledge_base_id: string;
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

export interface KnowledgeBase {
  id: string;
  name: string;
  api_key: string;
  base_url: string;
  dataset_id: string;
}

export interface KnowledgeBasesResponse {
  knowledge_bases: KnowledgeBase[];
  default_id: string;
}

export interface SettingsGroup {
  dify: Record<string, string>;
  path: Record<string, string>;
  general: Record<string, string>;
}

export interface SettingUpdatePayload {
  dify: Record<string, string>;
  path: Record<string, string>;
}

export interface ResolvedPath {
  absolute_path: string;
}

export interface KgEntity {
  id: number;
  name: string;
  entity_type: string;
  aliases: string[];
  mention_count: number;
  created_at: string;
}

export interface KgStats {
  entity_count: number;
  document_entity_count: number;
  document_relation_count: number;
  entities_by_type: Record<string, number>;
}

export interface KgGraphNode {
  id: string;
  label: string;
  type: 'document' | 'entity';
  entity_type?: string;
  department?: string;
  mention_count?: number;
  is_root?: boolean;
}

export interface KgGraphEdge {
  source: string;
  target: string;
  type: string;
  weight?: number;
}

export interface KgDocumentGraph {
  nodes: KgGraphNode[];
  edges: KgGraphEdge[];
}

export interface KgEntityDocument {
  doc_id: number;
  filename: string;
  department: string;
  relation_type: string;
  status: string;
}

export interface KgRetrieveDoc {
  doc_id: number;
  filename: string;
  knowledge_db_name: string;
  department: string;
  status: string;
  score: number;
  matched_entities: number[];
}

export interface KgRetrieveDocRelation {
  src_doc_id: number;
  dst_doc_id: number;
  weight: number;
}

export interface KgRebuildResult {
  total: number;
  success: number;
  failed: number;
  errors: { doc_id: number; filename: string; error: string }[];
}
