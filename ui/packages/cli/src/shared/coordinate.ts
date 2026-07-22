/**
 * AIHelms Skill 坐标：UUID skill_id（无 namespace/slug）。
 * install/search 既接受 UUID，也接受 skill name（name 经 search 解析为 skillId）。
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function isUuid(value: string): boolean {
  return UUID_RE.test(value)
}

export interface ParsedCoordinate {
  /** 命中 UUID 时为 skill_id；否则为 undefined，表示按 name 解析。 */
  skillId?: string
  /** 按 name 解析时的 skill 名称。 */
  name?: string
}

export function parseCoordinate(arg: string): ParsedCoordinate {
  if (isUuid(arg)) return { skillId: arg }
  return { name: arg }
}
