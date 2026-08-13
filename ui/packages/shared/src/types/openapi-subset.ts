/**
 * 接口调试器实际渲染的 OpenAPI 3.1 子集类型。
 *
 * 后端 build_openapi_spec 产出形状极简（仅 openapi/info/paths），operation 字段全可选，
 * schema 为 JSONB 原样透传的 inline 递归结构（无 components、无 $ref 解析）。
 * 此处仅建模渲染器实际读取的字段；JsonSchema 用索引签名吸收 LLM 透传的其余键。
 */

export type HttpMethod = 'get' | 'post' | 'put' | 'delete' | 'patch'

export type ParameterLocation = 'query' | 'path' | 'header' | 'cookie'

export interface OpenApiInfo {
  title: string
  version: string
}

export interface OpenApiSpec {
  openapi: string
  info: OpenApiInfo
  paths: Record<string, Partial<Record<HttpMethod, Operation>>>
  servers?: { url: string }[]
}

export interface Operation {
  summary?: string
  description?: string
  operationId?: string
  tags?: string[]
  parameters?: Parameter[]
  requestBody?: RequestBody
  responses?: Record<string, ResponseObject>
}

export interface Parameter {
  name: string
  in: ParameterLocation
  required?: boolean
  schema?: JsonSchema
  description?: string
  example?: unknown
}

export interface MediaTypeObject {
  schema?: JsonSchema
  example?: unknown
}

export interface RequestBody {
  content?: Record<string, MediaTypeObject>
  required?: boolean
  description?: string
}

export interface ResponseObject {
  description: string
  content?: Record<string, MediaTypeObject>
}

export interface JsonSchema {
  type?: string | string[]
  format?: string
  description?: string
  enum?: unknown[]
  properties?: Record<string, JsonSchema>
  items?: JsonSchema
  required?: string[]
  /** 吸收 LLM 透传的其余键（nullable/example/default 等），不破坏类型 */
  [key: string]: unknown
}

/** Try-it-out 经后端代理转发的请求载荷 */
export interface ProxyRequestPayload {
  method: HttpMethod
  url: string
  headers?: Record<string, string>
  body?: string | null
}

/** 后端代理始终以 200 envelope 回传的响应结果（目标自身 4xx/5xx 也原样回传，不抛） */
export interface ProxyResult {
  status: number
  status_text: string
  headers: Record<string, string>
  body: string
  content_type: string
  duration_ms: number
  truncated: boolean
}
