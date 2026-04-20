import type { RoleBinding, RoleName } from '../api/types';

const ROLES_KEY = 'roles';

export function saveRoles(roles: RoleBinding[] | undefined): void {
  localStorage.setItem(ROLES_KEY, JSON.stringify(roles ?? []));
}

export function loadRoles(): RoleBinding[] {
  try {
    const raw = localStorage.getItem(ROLES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function roleNames(): Set<RoleName> {
  return new Set(loadRoles().map((r) => r.role));
}

export function hasRole(role: RoleName): boolean {
  return roleNames().has(role);
}

export function hasAnyRole(...roles: RoleName[]): boolean {
  const names = roleNames();
  return roles.some((r) => names.has(r));
}

export function isSysAdmin(): boolean {
  return hasRole('SYS_ADMIN');
}

export function isBeCross(): boolean {
  return hasRole('BE_CROSS');
}

export function picDepartmentCodes(): Set<string> {
  return new Set(
    loadRoles()
      .filter((r) => r.role === 'DEPT_PIC' && r.department_code)
      .map((r) => r.department_code as string),
  );
}

/** Can the current user upload / modify documents for a specific department code? */
export function canUploadToDept(departmentCode: string | null | undefined): boolean {
  if (isSysAdmin() || isBeCross()) return true;
  if (!departmentCode) return false;
  return picDepartmentCodes().has(departmentCode);
}

/** Convenience: does the user have *any* write capability on *any* department? */
export function canUploadAnywhere(): boolean {
  if (isSysAdmin() || isBeCross()) return true;
  return picDepartmentCodes().size > 0;
}

/**
 * Filter a full list of department codes down to the ones the current user
 * may upload to. SYS_ADMIN / BE_CROSS keep the full list; PIC gets their
 * managed departments plus (optionally) their home department as fallback.
 */
export function writableDepartmentCodes(allCodes: string[]): string[] {
  if (isSysAdmin() || isBeCross()) return allCodes;
  const allowed = new Set<string>(picDepartmentCodes());
  return allCodes.filter((c) => allowed.has(c));
}

export function canManageRules(): boolean {
  return isSysAdmin();
}

/** Batch execution & monitoring are limited to SYS_ADMIN and BE_CROSS. */
export function canUseBatch(): boolean {
  return isSysAdmin() || isBeCross();
}

export function canManageSettings(): boolean {
  return isSysAdmin();
}

export function canManageUsers(): boolean {
  return isSysAdmin();
}

/** Can the user view a document belonging to ``departmentCode``? */
export function canViewDepartment(departmentCode: string | null | undefined): boolean {
  if (isSysAdmin() || isBeCross()) return true;
  if (!departmentCode) return false;
  const home = localStorage.getItem('department') || '';
  if (home && home === departmentCode) return true;
  return picDepartmentCodes().has(departmentCode);
}

export const ROLE_LABELS: Record<RoleName, string> = {
  SYS_ADMIN: '系统管理员',
  BE_CROSS: 'BE 跨部门管理员',
  DEPT_PIC: '部门 PIC',
  MEMBER: '普通成员',
};
