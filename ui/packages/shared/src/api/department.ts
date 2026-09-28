import { request } from './request'
import type {
  Department,
  DeptTreeNode,
  CreateDepartmentParams,
  UpdateDepartmentParams,
  DeptMember,
} from '../types/department'

export function getDepartmentTree(): Promise<DeptTreeNode[]> {
  return request<DeptTreeNode[]>('/api/v1/departments/tree')
}

export interface FullDepartmentItem {
  id: number
  name: string
  parent_id: number | null
  sort_order: number
}

/** 全量部门扁平列表（后端先尽力同步 AI Hub 再返回本地全量），选择器用 */
export function getAllDepartments(): Promise<FullDepartmentItem[]> {
  return request<FullDepartmentItem[]>('/api/v1/departments/all')
}

/** 强制全量同步 AI Hub 部门到本地，返回统计 */
export function syncAihubDepartments(): Promise<{ fetched: number; inserted: number; updated: number; linked: number }> {
  return request('/api/v1/departments/sync-aihub', { method: 'POST' })
}

export function getDepartmentById(id: number): Promise<Department> {
  return request<Department>(`/api/v1/departments/${id}`)
}

export function createDepartment(params: CreateDepartmentParams): Promise<Department> {
  return request<Department>('/api/v1/departments', {
    method: 'POST',
    body: params,
  })
}

export function updateDepartment(id: number, params: UpdateDepartmentParams): Promise<Department> {
  return request<Department>(`/api/v1/departments/${id}`, {
    method: 'PUT',
    body: params,
  })
}

export function deleteDepartment(id: number): Promise<null> {
  return request<null>(`/api/v1/departments/${id}`, { method: 'DELETE' })
}

export function getDepartmentMembers(id: number): Promise<DeptMember[]> {
  return request<DeptMember[]>(`/api/v1/departments/${id}/members`)
}

export function addDepartmentMember(deptId: number, userId: number): Promise<null> {
  return request<null>(`/api/v1/departments/${deptId}/members`, {
    method: 'POST',
    body: { user_id: userId },
  })
}

export function removeDepartmentMember(deptId: number, userId: number): Promise<null> {
  return request<null>(`/api/v1/departments/${deptId}/members/${userId}`, {
    method: 'DELETE',
  })
}

export function updateDepartmentManagers(id: number, managerUserIds: number[]): Promise<null> {
  return request<null>(`/api/v1/departments/${id}/managers`, {
    method: 'PUT',
    body: { manager_user_ids: managerUserIds },
  })
}
