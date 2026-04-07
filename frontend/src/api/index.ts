import client from './client';
import type {
  BatchFileLogItem,
  BatchSummary,
  DocumentContent,
  DocumentItem,
  IndexRuleCreate,
  IndexRuleItem,
  LoginRequest,
  LoginResponse,
  PaginatedResponse,
  PromptFile,
  RuleCreate,
  RuleItem,
} from './types';

export const authApi = {
  login: (data: LoginRequest) => client.post<LoginResponse>('/api/auth/login', data),
  me: () => client.get<{ username: string; display_name: string; department: string; section: string }>('/api/auth/me'),
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
  uploadToDify: (id: number) =>
    client.post(`/api/documents/${id}/upload-to-dify`),
  upload: (file: File, department?: string) => {
    const form = new FormData();
    form.append('file', file);
    return client.post('/api/documents/upload', form, {
      params: department ? { department } : {},
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
  run: () => client.post('/api/batch/run'),
  status: () => client.get<{ is_running: boolean; current_batch_id: string | null }>('/api/batch/status'),
  history: (params?: { page?: number; size?: number }) =>
    client.get<PaginatedResponse<BatchSummary>>('/api/batch/history', { params }),
  logs: (batchId: string) => client.get<BatchFileLogItem[]>(`/api/batch/logs/${batchId}`),
};

export type { DocumentItem, RuleItem, IndexRuleItem, PromptFile, BatchSummary, BatchFileLogItem, PaginatedResponse };
