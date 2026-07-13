import { marked } from 'marked'
import DOMPurify from 'dompurify'

const MARKDOWN_MIME_TYPES = new Set([
  'text/markdown',
  'text/x-markdown',
  'text/md',
])

/**
 * 将内容渲染为安全的 HTML。
 * - 明确标记为 markdown 的 MIME 类型 → markdown→HTML + DOMPurify 净化
 * - null/undefined → 默认按 markdown 处理（与 docs-mcp-server 一致）
 * - 其他 MIME 类型 → 转义后包裹在 <pre><code> 中
 */
export function renderMarkdownToHtml(
  content: string,
  mimeType?: string | null,
): string {
  const isMarkdown = !mimeType || MARKDOWN_MIME_TYPES.has(mimeType)

  if (!isMarkdown) {
    const escaped = content
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
    return `<pre><code>${escaped}</code></pre>`
  }

  const rawHtml = marked.parse(content, { async: false }) as string
  return DOMPurify.sanitize(rawHtml)
}
