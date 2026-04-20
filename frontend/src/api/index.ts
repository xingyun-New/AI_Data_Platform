import client from './client';
import type {
  BatchFileLogItem,
  BatchSummary,
  DepartmentOut,
  DocumentContent,
  DocumentItem,
  IndexRuleCreate,
  IndexRuleItem,
  LoginRequest,
  LoginResponse,
  PaginatedResponse,
  PromptFile,
  ResolvedPath,
  RoleBindingOut,
  RoleName,
  RuleCreate,
  RuleItem,
  SettingUpdatePayload,
  SettingsGroup,
  UserInfo,
  UserOut,
} from './types';

export const authApi = {
  login: (data: LoginRequest) => client.post<LoginResponse>('/api/auth/login', data),
  me: () => client.get<UserInfo>('/api/auth/me'),
};

export const userApi = {
  list: (params?: { keyword?: string; department?: string; role?: RoleName }) =>
    client.get<UserOut[]>('/api/users', { params }),
  get: (id: number) => client.get<UserOut>(`/api/users/${id}`),
  update: (id: number, data: { display_name?: string; is_active?: boolean }) =>
    client.patch<UserOut>(`/api/users/${id}`, data),
  grantRole: (userId: number, data: { role: RoleName; department_id?: number | null }) =>
    client.post<RoleBindingOut>(`/api/users/${userId}/roles`, data),
  revokeRole: (userId: number, bindingId: number) =>
    client.delete(`/api/users/${userId}/roles/${bindingId}`),
};

export const deptApi = {
  list: () => client.get<DepartmentOut[]>('/api/departments'),
  create: (data: { code: string; name?: string; is_active?: boolean }) =>
    client.post<DepartmentOut>('/api/departments', data),
  update: (id: number, data: { name?: string; is_active?: boolean }) =>
    client.patch<DepartmentOut>(`/api/departments/${id}`, data),
};

export const docApi = {
  list: (params?: { department?: string; status?: string; keyword?: string; page?: number; size?: number }) =>
    client.get<PaginatedResponse<DocumentItem>>('/api/documents', { params }),
  get: (id: number) => client.get<DocumentContent>(`/api/documents/${id}`),
  getRedacted: (id: number) => client.get<DocumentContent>(`/api/documents/${id}/redacted`),
  getIndex: (id: number) => client.get(`/api/documents/${id}/index`),
  desensitize: (id: number) => client.post(`/api/documents/${id}/desensitize`),
  generateIndex: (id: number) => client.post(`/api/documents/${id}/generate-index`),
  delete: (id: number) => client.delete(`/api/documents/${id}`),
  uploadToDify: (id: number, knowledgeBaseId?: string) =>
    client.post(`/api/documents/${id}/upload-to-dify`, null, {
      params: knowledgeBaseId ? { knowledge_base_id: knowledgeBaseId } : {},
    }),
  upload: (
    file: File,
    department?: string,
    knowledgeBaseId?: string,
    section?: string,
  ) => {
    const form = new FormData();
    form.append('file', file);
    const params: Record<string, string> = {};
    if (department) params.department = department;
    if (knowledgeBaseId) params.knowledge_base_id = knowledgeBaseId;
    if (section !== undefined) params.section = section;
    return client.post('/api/documents/upload', form, {
      params,
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};

export const ruleApi = {
  list: (params?: { department?: string; page?: number; size?: number }) =>
    client.get<PaginatedResponse<RuleItem>>('/api/rules', { params }),
  create: (data: RuleCreate) => client.post<RuleItem>('/api/rules', data),
  update: (id: number, data: Partial<RuleCreate>) => client.put<RuleItem>(`/api/rules/${id}`, data),
  delete: (id: number) => client.delete(`/api/rules/${id}`),
};

export const indexRuleApi = {
  list: (params?: { department?: string; rule_type?: string; page?: number; size?: number }) =>
    client.get<PaginatedResponse<IndexRuleItem>>('/api/index-rules', { params }),
  create: (data: IndexRuleCreate) =>
    client.post<IndexRuleItem>('/api/index-rules', data),
  update: (id: number, data: Partial<IndexRuleCreate>) =>
    client.put<IndexRuleItem>(`/api/index-rules/${id}`, data),
  delete: (id: number) =>
    client.delete(`/api/index-rules/${id}`),
};

export const promptApi = {
  list: () => client.get<PromptFile[]>('/api/prompts'),
  get: (filename: string) => client.get<PromptFile>(`/api/prompts/${filename}`),
  update: (filename: string, content: string) =>
    client.put<PromptFile>(`/api/prompts/${filename}`, { content }),
};

export const batchApi = {
  run: (params?: { department?: string; knowledge_base_id?: string }) =>
    client.post('/api/batch/run', null, { params }),
  status: () => client.get<{ is_running: boolean; current_batch_id: string | null }>('/api/batch/status'),
  history: (params?: { page?: number; size?: number }) =>
    client.get<PaginatedResponse<BatchSummary>>('/api/batch/history', { params }),
  logs: (batchId: string) => client.get<BatchFileLogItem[]>(`/api/batch/logs/${batchId}`),
};

export const graphApi = {
  stats: () => client.get<import('./types').KgStats>('/api/graph/stats'),
  listEntities: (params?: { q?: string; entity_type?: string; page?: number; size?: number }) =>
    client.get<PaginatedResponse<import('./types').KgEntity>>('/api/graph/entities', { params }),
  entityDocuments: (entityId: number) =>
    client.get<{ entity: { id: number; name: string; entity_type: string }; documents: import('./types').KgEntityDocument[] }>(
      `/api/graph/entities/${entityId}/documents`,
    ),
  documentGraph: (docId: number) =>
    client.get<import('./types').KgDocumentGraph>(`/api/graph/document/${docId}`),
  deleteDocumentGraph: (docId: number) =>
    client.delete(`/api/graph/document/${docId}`),
  rebuild: (data?: { document_ids?: number[] | null; only_missing?: boolean; limit?: number | null }) =>
    client.post<import('./types').KgRebuildResult>('/api/graph/rebuild', data || {}),
  retrieve: (data: { query: string; top_k?: number; department?: string | null }) =>
    client.post<{
      query: string;
      matched_entities: { id: number; name: string; type: string }[];
      documents: import('./types').KgRetrieveDoc[];
      doc_relations: import('./types').KgRetrieveDocRelation[];
      knowledge_db_names: string[];
    }>('/api/graph/retrieve', data),
};

export const settingsApi = {
  getAll: () => client.get<SettingsGroup>('/api/settings'),
  updateAll: (data: SettingUpdatePayload) => client.put('/api/settings', data),
  updateSingle: (key: string, value: string, pathMode?: string) =>
    client.put(`/api/settings/${key}`, { value, path_mode: pathMode }),
  resolvePath: (relativePath: string) =>
    client.get<ResolvedPath>('/api/settings/resolve-path', { params: { relative_path: relativePath } }),
  getKnowledgeBases: () => client.get<{ knowledge_bases: import('./types').KnowledgeBase[]; default_id: string }>('/api/knowledge-bases'),
  saveKnowledgeBases: (data: { knowledge_bases: import('./types').KnowledgeBase[]; default_id: string }) =>
    client.put('/api/knowledge-bases', data),
};

export type {
  BatchFileLogItem,
  BatchSummary,
  DepartmentOut,
  DocumentItem,
  IndexRuleItem,
  KnowledgeBase,
  PaginatedResponse,
  PromptFile,
  RoleBinding,
  RoleBindingOut,
  RoleName,
  RuleItem,
  SettingsGroup,
  SettingUpdatePayload,
  UserInfo,
  UserOut,
} from './types';
