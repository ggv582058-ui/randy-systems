import 'dotenv/config'
import path from 'node:path'

const number = (value, fallback) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export const config = {
  env: process.env.NODE_ENV || 'development',
  botName: process.env.BOT_NAME || 'RANDY SYSTEMS',
  prefix: process.env.PREFIX || '.',
  ownerNumber: (process.env.OWNER_NUMBER || '').replace(/\D/g, ''),
  groupLink: process.env.GROUP_LINK || '',
  host: process.env.HOST || '0.0.0.0',
  port: number(process.env.PORT, 3000),
  sessionDir: path.resolve(process.env.SESSION_DIR || './session'),
  logLevel: process.env.LOG_LEVEL || (process.env.NODE_ENV === 'production' ? 'info' : 'silent'),
  reconnectDelayMs: Math.max(1000, number(process.env.RECONNECT_DELAY_MS, 5000)),
  openaiKey: process.env.OPENAI_API_KEY || '',
  openaiModel: process.env.OPENAI_MODEL || 'gpt-5-mini',
  redisUrl: process.env.REDIS_URL || '',
  sessionBackupKey: process.env.SESSION_BACKUP_KEY || 'randy:whatsapp:session',
  sessionBackupIntervalMs: Math.max(5000, number(process.env.SESSION_BACKUP_INTERVAL_MS, 15000)),
  sessionEncryptionKey: process.env.SESSION_ENCRYPTION_KEY || ''
}
