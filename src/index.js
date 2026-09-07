import express from 'express'
import fs from 'node:fs/promises'
import pino from 'pino'
import qrcode from 'qrcode-terminal'
import makeWASocket, { DisconnectReason, fetchLatestBaileysVersion, useMultiFileAuthState } from '@whiskeysockets/baileys'
import { Boom } from '@hapi/boom'
import { config } from './config.js'
import { getText, parseCommand } from './lib/utils.js'
import { buildContext } from './lib/context.js'
import { commands } from './commands/index.js'
import { createSessionStore } from './lib/session-store.js'

const logger = pino({ level: config.logLevel })
const startedAt = new Date()
const runtime = { connection: 'starting', connectedAt: null, lastDisconnectAt: null, lastDisconnectCode: null, qrPending: false, reconnectAttempts: 0 }
let currentSock = null
let reconnectTimer = null
let shuttingDown = false
let sessionBackupTimer = null

await fs.mkdir(config.sessionDir, { recursive: true })
async function assertSessionDirWritable() { const probe = `${config.sessionDir}/.write-test-${process.pid}`; await fs.writeFile(probe, 'ok'); await fs.unlink(probe) }
await assertSessionDirWritable()

const sessionStore = await createSessionStore({ redisUrl: config.redisUrl, key: config.sessionBackupKey, sessionDir: config.sessionDir, encryptionKey: config.sessionEncryptionKey, logger: console })
await sessionStore.restore().catch(error => console.error('Session restore failed:', error))
if (sessionStore.enabled) {
  sessionBackupTimer = setInterval(() => { sessionStore.backup().catch(error => console.error('Session backup failed:', error)) }, config.sessionBackupIntervalMs)
  sessionBackupTimer.unref?.()
  console.log('💾 Persistent session backup: enabled')
}

const app = express(); app.disable('x-powered-by')
app.get('/', (_, res) => res.json({ ok: true, bot: config.botName, environment: config.env, connection: runtime.connection, uptimeSeconds: Math.floor(process.uptime()), startedAt: startedAt.toISOString(), connectedAt: runtime.connectedAt, reconnectAttempts: runtime.reconnectAttempts }))
app.get('/health', (_, res) => res.status(200).json({ ok: true, status: 'alive' }))
app.get('/ready', (_, res) => { const ready = runtime.connection === 'open'; res.status(ready ? 200 : 503).json({ ok: ready, status: ready ? 'ready' : 'not_ready', connection: runtime.connection, qrPending: runtime.qrPending, lastDisconnectCode: runtime.lastDisconnectCode }) })
const healthServer = app.listen(config.port, config.host, () => { console.log(`🩺 Health server: http://${config.host}:${config.port}/health`); console.log(`💾 Session directory: ${config.sessionDir}`) })

function scheduleReconnect(reason = 'connection closed') {
  if (shuttingDown || reconnectTimer) return
  runtime.connection = 'reconnecting'; runtime.reconnectAttempts += 1
  console.log(`🔄 Reconectando en ${config.reconnectDelayMs} ms (${reason})`)
  reconnectTimer = setTimeout(async () => { reconnectTimer = null; try { await startBot() } catch (error) { console.error('Reconnect failed:', error); scheduleReconnect('startup failure') } }, config.reconnectDelayMs)
}

async function startBot() {
  runtime.connection = runtime.reconnectAttempts > 0 ? 'reconnecting' : 'starting'
  const { state, saveCreds } = await useMultiFileAuthState(config.sessionDir)
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }))
  const sock = makeWASocket({ auth: state, version, logger, markOnlineOnConnect: true, syncFullHistory: false, generateHighQualityLinkPreview: false, browser: [config.botName, 'Chrome', '1.0.0'] })
  currentSock = sock
  sock.ev.on('creds.update', async () => { await saveCreds(); if (sessionStore.enabled) await sessionStore.backup().catch(() => {}) })
  sock.ev.on('connection.update', update => {
    const { connection, lastDisconnect, qr } = update
    if (qr) { runtime.qrPending = true; runtime.connection = 'waiting_for_qr'; console.log('\n📱 Escanea este QR en WhatsApp → Dispositivos vinculados:\n'); qrcode.generate(qr, { small: true }) }
    if (connection === 'open') { runtime.connection = 'open'; runtime.connectedAt = new Date().toISOString(); runtime.lastDisconnectCode = null; runtime.qrPending = false; runtime.reconnectAttempts = 0; sessionStore.backup().catch(() => {}); console.log(`✅ ${config.botName} conectado como ${sock.user?.id || 'bot'}`) }
    if (connection === 'close') {
      const statusCode = new Boom(lastDisconnect?.error)?.output?.statusCode
      const loggedOut = statusCode === DisconnectReason.loggedOut
      runtime.lastDisconnectAt = new Date().toISOString(); runtime.lastDisconnectCode = statusCode || null; runtime.qrPending = false
      console.log(`⚠️ Conexión cerrada. Código: ${statusCode || 'desconocido'}`)
      if (shuttingDown) { runtime.connection = 'stopped'; return }
      if (loggedOut) { runtime.connection = 'logged_out'; console.log('❌ WhatsApp cerró la sesión. Vuelve a vincular el dispositivo.'); return }
      scheduleReconnect(`disconnect code ${statusCode || 'unknown'}`)
    }
  })
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return
    for (const msg of messages) {
      try {
        if (!msg?.message || msg.key.fromMe) continue
        const jid = msg.key.remoteJid; if (!jid || jid === 'status@broadcast') continue
        const parsed = parseCommand(getText(msg), config.prefix); if (!parsed) continue
        const handler = commands[parsed.command]; if (!handler) continue
        const ctx = await buildContext(sock, msg, parsed); await handler(ctx)
      } catch (error) {
        console.error('Command error:', error)
        const jid = msg?.key?.remoteJid
        if (jid) await sock.sendMessage(jid, { text: '❌ Ocurrió un error ejecutando ese comando.' }, { quoted: msg }).catch(() => {})
      }
    }
  })
  return sock
}

async function shutdown(signal) {
  if (shuttingDown) return
  shuttingDown = true; runtime.connection = 'stopping'; console.log(`\n🛑 ${signal} recibido. Cerrando ${config.botName}...`)
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (sessionBackupTimer) clearInterval(sessionBackupTimer)
  await sessionStore.backup().catch(() => {}); await sessionStore.close().catch(() => {})
  try { currentSock?.end?.(new Error(`Process shutdown: ${signal}`)) } catch {}
  healthServer.close(() => { runtime.connection = 'stopped'; process.exit(0) })
  setTimeout(() => process.exit(0), 5000).unref()
}
process.on('SIGTERM', () => shutdown('SIGTERM'))
process.on('SIGINT', () => shutdown('SIGINT'))
process.on('unhandledRejection', error => console.error('Unhandled rejection:', error))
process.on('uncaughtException', error => { console.error('Uncaught exception:', error); process.exit(1) })
startBot().catch(error => { console.error('Initial WhatsApp startup failed:', error); scheduleReconnect('initial startup failure') })
