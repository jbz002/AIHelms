import { marked } from 'marked'
import DOMPurify from 'dompurify'

const MARKDOWN_MIME_TYPES = new Set([
  'text/markdown',
  'text/x-markdown',
  'text/md',
  'text/plain',
])

/**
 * 将内容渲染为安全的 HTML。
 * - 明确标记为 markdown 的 MIME 类型 → markdown→HTML + DOMPurify 净化
 * - text/plain（.txt 等文档）→ 按 markdown 渲染（docs-mcp 爬取的 txt 实际是 markdown）
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

/**
 * 在容器 DOM 中查找 mermaid 代码块并渲染为 SVG 图表。
 * 使用动态 import 加载 mermaid，仅在存在 mermaid 块时才加载。
 * 渲染失败时保留原始代码块作为降级展示。
 */
export async function renderMermaidBlocks(container: HTMLElement): Promise<void> {
  const mermaidCodes = container.querySelectorAll<HTMLElement>(
    'pre code[class*="language-mermaid"]',
  )
  if (mermaidCodes.length === 0) return

  try {
    const mermaid = await import('mermaid')
    mermaid.default.initialize({ startOnLoad: false })

    for (let i = 0; i < mermaidCodes.length; i++) {
      const codeEl = mermaidCodes[i]
      const preEl = codeEl.parentElement
      if (!preEl) continue

      const content = codeEl.textContent || ''
      const id = `mermaid-${Date.now()}-${i}`

      try {
        const { svg } = await mermaid.default.render(id, content)
        const wrapper = document.createElement('div')
        wrapper.className = 'mermaid-chart my-4 flex justify-center'
        wrapper.innerHTML = svg
        preEl.replaceWith(wrapper)
      } catch {
        preEl.classList.add('border', 'border-yellow-300')
      }
    }
  } catch {
    for (let i = 0; i < mermaidCodes.length; i++) {
      const preEl = mermaidCodes[i].parentElement
      if (preEl) preEl.classList.add('border', 'border-red-500')
    }
  }
}
