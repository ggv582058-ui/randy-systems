import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'
import { createClient } from 'redis'

const SESSION_FILE_RE = /^[^/]+$/
async function listSessionFiles(dir) { const entries = await fs.readdir(dir, { withFileTypes: true }).catch(() => []); const files = {}; for (const entry of entries) { if (!entry.isFile() || !SESSION_FILE_RE.test(entry.name)) continue; const data = await fs.readFile(path.join(dir, entry.name)); files[entry.name] = data.toString('base64') } return files }
async function writeSessionFiles(dir, files = {}) { await fs.mkdir(dir, { recursive: true }); for (const [name, b64] of Object.entries(files)) { if (!SESSION_FILE_RE.test(name) || typeof b64 !== 'string') continue; await fs.writeFile(path.join(dir, name), Buffer.from(b64, 'base64')) } }
function deriveKey(secret = '') { if (!secret) return null; return crypto.createHash('sha256').update(secret).digest() }
function encryptJson(value, secret) { const key = deriveKey(secret); if (!key) return JSON.stringify({ v: 0, data: value }); const iv = crypto.randomBytes(12); const cipher = crypto.createCipheriv('aes-256-gcm', key, iv); const encrypted = Buffer.concat([cipher.update(JSON.stringify(value), 'utf8'), cipher.final()]); const tag = cipher.getAuthTag(); return JSON.stringify({ v: 1, alg: 'aes-256-gcm', iv: iv.toString('base64'), tag: tag.toString('base64'), data: encrypted.toString('base64') }) }
function decryptJson(raw, secret) { const envelope = JSON.parse(raw); if (envelope?.v === 0) return envelope.data; if (envelope?.v !== 1) return envelope; const key = deriveKey(secret); if (!key) throw new Error('SESSION_ENCRYPTION_KEY is required to restore this encrypted session.'); const decipher = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(envelope.iv, 'base64')); decipher.setAuthTag(Buffer.from(envelope.tag, 'base64')); const decrypted = Buffer.concat([decipher.update(Buffer.from(envelope.data, 'base64')), decipher.final()]); return JSON.parse(decrypted.toString('utf8')) }

export async function createSessionStore({ redisUrl, key, sessionDir, encryptionKey, logger = console }) {
  if (!redisUrl) return { enabled: false, async restore() {}, async backup() {}, async close() {} }
  const client = createClient({ url: redisUrl }); client.on('error', err => logger.error?.('Session store Redis error:', err?.message || err)); await client.connect()
  return {
    enabled: true,
    async restore() { const current = await listSessionFiles(sessionDir); if (Object.keys(current).length > 0) return false; const raw = await client.get(key); if (!raw) return false; const payload = decryptJson(raw, encryptionKey); await writeSessionFiles(sessionDir, payload.files || {}); logger.log?.(`♻️ Sesión restaurada (${Object.keys(payload.files || {}).length} archivos)`); return true },
    async backup() { const files = await listSessionFiles(sessionDir); if (Object.keys(files).length === 0) return false; await client.set(key, encryptJson({ savedAt: new Date().toISOString(), files }, encryptionKey)); return true },
    async close() { if (client.isOpen) await client.quit() }
  }
}
