import fs from 'node:fs'
import path from 'node:path'

const target = path.resolve('src/index.js')
if (!fs.existsSync(target)) process.exit(0)

let source = fs.readFileSync(target, 'utf8')
const oldGuard = "if (runtime.connection === 'open' || currentSock?.user?.id) return res.status(409).json({ error: 'El bot ya está vinculado. Cierra la sesión actual antes de vincular otro número.' })"
const newGuard = "if (runtime.connection === 'open') return res.status(409).json({ error: 'El bot ya está vinculado. Cierra la sesión actual antes de vincular otro número.' })"

if (source.includes(oldGuard)) {
  source = source.replace(oldGuard, newGuard)
  fs.writeFileSync(target, source)
  console.log('[app-pairing-patch] stale linked-state guard removed')
} else {
  console.log('[app-pairing-patch] guard already fixed or not found')
}
