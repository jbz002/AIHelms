export function isWindows(): boolean {
  return process.platform === 'win32'
}

export function isTTY(): boolean {
  return process.stdin.isTTY === true && process.stdout.isTTY === true
}
