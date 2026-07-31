/**
 * 复制文本到剪贴板，兼容非安全上下文（HTTP）。
 * 安全上下文走 navigator.clipboard，否则降级 execCommand 兜底。
 * 全部失败时抛错，调用方自行 catch 提示。
 */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
    return
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  const ok = document.execCommand('copy')
  document.body.removeChild(ta)
  if (!ok) throw new Error('copy failed')
}
