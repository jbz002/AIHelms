import { existsSync, readFileSync } from 'fs';
import { join } from 'path';

/**
 * 极简 .env 读取：只填 process.env 里没有的键。
 * 查找顺序：ui/e2e/.env → 仓库根 .env（复用 WEB_PORT / AI_HUB_URL）。
 */
export function loadE2EEnv(): void {
  const candidates = [
    join(process.cwd(), 'e2e', '.env'),
    join(process.cwd(), '..', '.env'),
  ];
  for (const envPath of candidates) {
    if (!existsSync(envPath)) continue;
    for (const line of readFileSync(envPath, 'utf8').split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
      if (!m || line.trim().startsWith('#')) continue;
      if (process.env[m[1]] === undefined) {
        process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
      }
    }
  }
}
