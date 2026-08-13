import type { JsonSchema } from '../types/openapi-subset'

/** 展平后的 schema 行：驱动请求体/响应表格渲染，depth 控制缩进 */
export interface SchemaRow {
  name: string
  type: string
  required: boolean
  description: string
  depth: number
}

/** depth → 名称列左内距 Tailwind class，规避动态 class 编译问题，避免 inline style */
export const SCHEMA_PAD_CLASS: string[] = [
  'pl-2',
  'pl-6',
  'pl-10',
  'pl-14',
  'pl-18',
  'pl-22',
  'pl-26',
  'pl-30',
]

const MAX_DEPTH = 10

function typeText(schema: JsonSchema | undefined): string {
  if (!schema) return ''
  const ty = schema.type
  if (ty) {
    const base = Array.isArray(ty) ? ty.join(' | ') : String(ty)
    if (base === 'array' && schema.items) {
      const itemTy = typeText(schema.items)
      return itemTy ? `array<${itemTy}>` : 'array'
    }
    return base
  }
  if (schema.properties) return 'object'
  if (schema['$ref']) return String(schema['$ref'])
  return ''
}

function is_array(schema: JsonSchema): boolean {
  const ty = schema.type
  return Array.isArray(ty) ? ty.includes('array') : ty === 'array'
}

function collect(schema: JsonSchema | undefined, depth: number, rows: SchemaRow[]): void {
  if (!schema || depth > MAX_DEPTH) return
  const props = schema.properties
  if (!props || !Object.keys(props).length) return
  const reqSet = new Set<string>((schema.required ?? []).map(String))
  for (const [name, child] of Object.entries(props)) {
    rows.push({
      name,
      type: typeText(child),
      required: reqSet.has(name),
      description: typeof child.description === 'string' ? child.description : '',
      depth,
    })
    if (child.properties && Object.keys(child.properties).length) {
      collect(child, depth + 1, rows)
    }
    if (is_array(child) && child.items?.properties && Object.keys(child.items.properties).length) {
      collect(child.items, depth + 1, rows)
    }
  }
}

/** 把递归 JsonSchema 拍平成表格行；空 schema 返回 [] */
export function flattenSchemaRows(schema: JsonSchema | undefined): SchemaRow[] {
  const rows: SchemaRow[] = []
  if (schema && !schema.properties && is_array(schema) && schema.items?.properties) {
    collect(schema.items, 0, rows)
    return rows
  }
  collect(schema, 0, rows)
  return rows
}
