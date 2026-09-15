import { existsSync, readFileSync } from 'node:fs'

export function hostPorts() {
  const path = new URL('../ports.env', import.meta.url)
  const values = existsSync(path)
    ? Object.fromEntries(readFileSync(path, 'utf8').trim().split('\n').map(line => line.split('=', 2)))
    : {}
  const port = (name: string) => {
    const value = Number(process.env[name] ?? values[name])
    if (!Number.isInteger(value) || value < 10240 || value > 65535) {
      throw new Error(`${name} must be a host port from 10240 through 65535`)
    }
    return value
  }
  return { ui: port('UI_PORT'), vite: port('VITE_PORT') }
}
