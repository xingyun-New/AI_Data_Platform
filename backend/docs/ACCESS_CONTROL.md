# 权限管理文档 (Access Control)

本文档描述 AI Data Platform 项目的 RBAC（基于角色的访问控制）设计。所有权限均通过"角色" + "部门归属"两层判断来实现，权限取各角色的并集。

---

## 1. 角色定义

| 角色 | 值 | 说明 |
|------|---|------|
| **SYS_ADMIN** 系统管理员 | `"SYS_ADMIN"` | 全权：文档、规则、系统设置、用户管理、Batch 执行均可操作。 |
| **BE_CROSS** 跨部门文档管理员 | `"BE_CROSS"` | 可跨部门上传/维护文档、可执行 Batch 监控；无权修改规则或系统设置。 |
| **DEPT_PIC** 部门负责人 | `"DEPT_PIC"` | 仅限所负责的部门（可指定多个部门）上传/维护文档；无权跨部门。 |
| **MEMBER** 普通成员 | `"MEMBER"` | 默认角色，只能查看本部门的文档列表与知识图谱。 |

> **多角色叠加**：一个用户可绑定多个角色，权限取并集。例如某人同时拥有 `DEPT_PIC`（负责 A 部门）和 `BE_CROSS`，则他既能管理 A 部门的文档，也能管理所有部门的文档。

---

## 2. 角色分配规则

### 2.1 自动授予（登录时）

| 条件 | 自动授予 |
|------|---------|
| `username` 在 `settings.admin_usernames` 配置中 | `SYS_ADMIN` |
| `department == settings.be_department_code`（默认 `BE`） | `BE_CROSS` |
| 登录时没有任何角色 | `MEMBER`（安全默认） |

### 2.2 手动授予（仅 SYS_ADMIN）

通过 **用户管理页面**（`/users`）或 `POST /api/users/{id}/roles` API：

- 可为任意用户授予任何角色。
- `DEPT_PIC` 必须指定负责的部门（`department_id`）。
- 可随时撤销（`DELETE /api/users/{id}/roles/{binding_id}`）。

### 2.3 数据模型

- `users` 表：`id`, `username`, `display_name`, `department`, `section`, `is_active`, …
- `departments` 表：`id`, `code`, `name`, `is_active`（部门主数据）
- `user_roles` 表：`user_id`, `role`, `department_id`(可选), `granted_by`, `granted_at`
  - `department_id` 仅对 `DEPT_PIC` 有意义，限定该 PIC 负责的部门。

---

## 3. 功能权限矩阵

| 功能模块 | API 路由 | SYS_ADMIN | BE_CROSS | DEPT_PIC | MEMBER |
|----------|----------|-----------|----------|----------|--------|
| 文档列表 | `GET /api/documents` | 全部门 | 全部门 | 本部门+所管 | 本部门 |
| 文档上传 | `POST /api/documents/upload` | 任意部门 | 任意部门 | 所管部门 | 无权限 |
| 文档详情/查看 | `GET /api/documents/{id}` | ✓ | ✓ | ✓(本部门) | ✓(本部门) |
| 文档脱敏 | `POST /api/documents/{id}/desensitize` | ✓ | ✓ | ✓(本部门) | 无权限 |
| 文档索引 | `POST /api/documents/{id}/generate-index` | ✓ | ✓ | ✓(本部门) | 无权限 |
| 文档上传 Dify | `POST /api/documents/{id}/upload-to-dify` | ✓ | ✓ | ✓(本部门) | 无权限 |
| 文档删除 | `DELETE /api/documents/{id}` | ✓ | ✓ | ✓(本部门) | 无权限 |
| 脱敏规则 CRUD | `/api/rules` | ✓ | — | — | — |
| 索引规则 CRUD | `/api/index-rules` | ✓ | — | — | — |
| 提示词管理 | `/api/prompts` | ✓ | — | — | — |
| Batch 执行 | `POST /api/batch/run` | ✓ | ✓ | — | — |
| Batch 状态 | `GET /api/batch/status` | ✓ | ✓ | — | — |
| Batch 历史/日志 | `/api/batch/history`, `/api/batch/logs` | ✓ | ✓ | — | — |
| 系统设置 | `/api/settings` | ✓ | — | — | — |
| 知识库管理 | `GET/PUT /api/knowledge-bases` | ✓ | — | — | — |
| 知识图谱 | `/api/graph/*` | ✓ | ✓ | ✓ | ✓ |
| KG 检索 | `POST /api/graph/retrieve` | — | — | — | — |
| 用户列表 | `GET /api/users` | ✓ | — | — | — |
| 角色授予/撤销 | `/api/users/{id}/roles` | ✓ | — | — | — |
| 部门主数据 | `GET /api/departments` | ✓ | ✓ | ✓ | ✓ |
| 部门管理 | `POST/PATCH /api/departments` | ✓ | — | — | — |

> `—` 表示无权访问（返回 403 或菜单项不显示）；`POST /api/graph/retrieve` 故意不设鉴权，供 Dify 外部调用。

---

## 4. 部门过滤规则

### 4.1 文档列表

后端在 `documents.py` 的列表查询中按角色自动过滤：

- **SYS_ADMIN / BE_CROSS**：不过滤，可看到所有部门的文档。
- **DEPT_PIC**：限制为 `department in (home_dept, managed_dept_1, managed_dept_2, …)`。
- **MEMBER**：仅 `department == 登录用户的 department`。

### 4.2 文档上传 — 目标部门

上传页面顶部提供"目标部门"下拉选择器：

| 角色 | 可选部门 |
|------|---------|
| `SYS_ADMIN` / `BE_CROSS` | 所有启用的部门 |
| `DEPT_PIC` | 本部门 + 所负责的部门 |
| `MEMBER` | 上传按钮整体隐藏 |

上传时：
- **本部门**：`department` + `section` 均继承用户自身信息。
- **其他部门**：`department` = 所选目标部门，`section` = `""`，避免上传者的 `section` 污染目标部门的规则匹配。

---

## 5. 认证流程

```
用户输入用户名/密码
  └─► Innomate API 查询部门/课/显示名
      └─► 创建/更新 users 表
      └─► 自动授予 SYS_ADMIN / BE_CROSS（如匹配配置）
      └─► 若无任何角色 → 授予 MEMBER
      └─► 从 user_roles 加载全部角色绑定
      └─► 签发 JWT（roles 嵌入 token）
      └─► 前端保存 token + roles → localStorage
```

每次 API 请求通过 `Authorization: Bearer <token>` 携带令牌。后端 `get_current_user` 解码 JWT 后得到：
- `username`、`department`、`section`、`display_name`
- `roles` 列表（含 `role` 和 `department_id`）
- `role_names`（便捷字段）
- `pic_department_ids`（DEPT_PIC 绑定的部门 ID 列表）

---

## 6. 后端权限判断逻辑

核心代码位于 `backend/app/api/deps_rbac.py`：

| 函数 | 用途 |
|------|------|
| `require_roles(*roles)` | 路由级依赖：缺少任一角色时返回 403 |
| `require_sys_admin` | 快捷版，仅检查 SYS_ADMIN |
| `can_upload_document(user, db, department_code)` | 判断用户能否向某部门上传文档 |
| `can_manage_rule(user)` | 判断用户能否维护规则 |
| `can_view_document(user, dept)` | 判断用户能否查看某部门的文档 |
| `is_sys_admin(user)` / `is_be_cross(user)` | 角色检查快捷函数 |

典型权限校验示例（文档上传）：
```python
if not can_upload_document(user, db, target_dept):
    raise HTTPException(403, f"无权向部门「{target_dept}」上传文档")
```

典型权限校验示例（批量操作）：
```python
_batch_guard = require_roles(ROLE_SYS_ADMIN, ROLE_BE_CROSS)

@router.post("/run")
async def run_batch(_user: dict = Depends(_batch_guard)):
    ...
```

---

## 7. 前端权限判断逻辑

核心代码位于 `frontend/src/utils/permissions.ts`：

| 函数 | 用途 |
|------|------|
| `hasRole(role)` | 检查当前用户是否有某角色 |
| `isSysAdmin()` / `isBeCross()` | 角色检查 |
| `picDepartmentCodes()` | 获取 DEPT_PIC 绑定的部门代码集合 |
| `canUploadToDept(deptCode)` | 能否向指定部门上传/维护文档 |
| `canUploadAnywhere()` | 是否有任何部门的上传权限 |
| `canManageRules()` | 能否管理规则（仅 SYS_ADMIN） |
| `canManageSettings()` | 能否管理系统设置（仅 SYS_ADMIN） |
| `canManageUsers()` | 能否管理用户（仅 SYS_ADMIN） |
| `canUseBatch()` | 能否使用 Batch（SYS_ADMIN + BE_CROSS） |
| `canViewDepartment(deptCode)` | 能否查看某部门的文档 |
| `writableDepartmentCodes(allCodes)` | 过滤出当前用户可上传的部门 |

前端使用场景：
- **菜单显隐**：`App.tsx` 的 `MENU_ITEMS` 每项有 `visible: () => boolean`。
- **路由守卫**：`<RequireRole allow={canManageRules}>` 包裹受保护的页面。
- **按钮禁用**：`DocumentListPage` 中每行操作按钮按 `canUploadToDept(record.department)` 动态启用/禁用。
- **角色标签显示**：Header 栏显示当前用户的所有角色。

---

## 8. 异常处理

| 场景 | 后端响应 | 前端表现 |
|------|---------|---------|
| 未登录 / token 过期 | 401 | 跳转登录页 |
| 缺少所需角色 | 403 `{detail: "权限不足"}` | 菜单不显示 / 页面显示"权限不足" / 按钮灰掉 |
| 账户被禁用 (`is_active=false`) | 登录 403 `账户已被禁用` | 登录页提示 |
| 跨部门上传未选部门 | 前端拦截，不发起请求 | 按钮禁用 + Tooltip 提示 |

---

## 9. 配置项

`backend/.env` 中的相关配置：

```ini
# 逗号分隔的用户名，首次登录自动授予 SYS_ADMIN
admin_usernames=admin

# 该部门的成员自动获得 BE_CROSS 角色
be_department_code=BE
```

---

## 10. 安全注意事项

1. `POST /api/graph/retrieve` **无鉴权**，专供 Dify 外部调用，应确保该接口仅在内网暴露或通过反向代理做 IP 限制。
2. 所有其他 API 均要求 `Authorization: Bearer <token>`。
3. `JWT secret_key` 必须在生产环境中设置为强随机值，否则系统将自动报警并生成临时密钥（导致已有 token 失效）。
4. `unified_password` 为全局统一密码，生产环境应配合 LDAP/SSO 使用。
5. 权限判断在**后端**执行（前端仅做 UI 收敛），不可信任前端逻辑作为安全边界。
6. 用户被撤销角色后，已签发的 JWT 仍会携带旧角色（直到过期或重新登录）。
