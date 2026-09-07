import express from 'express'
import fs from 'node:fs/promises'
import pino from 'pino'
import qrcode from 'qrcode-terminal'
import makeWASocket, { Browsers, DisconnectReason, fetchLatestBaileysVersion, useMultiFileAuthState } from '@whiskeysockets/baileys'
import { Boom } from '@hapi/boom'
import { config } from './config.js'
import { getText, parseCommand } from './lib/utils.js'
import { buildContext } from './lib/context.js'
import { commands } from './commands/index.js'
import { createSessionStore } from './lib/session-store.js'

const logger = pino({ level: config.logLevel })
const startedAt = new Date()
const runtime = { connection: 'starting', connectedAt: null, lastDisconnectAt: null, lastDisconnectCode: null, qrPending: false, reconnectAttempts: 0, pairingPhone: null, pairingRequestedAt: null }
let currentSock = null
let reconnectTimer = null
let shuttingDown = false
let sessionBackupTimer = null
let pairingBusy = false
let pairingRestartInProgress = false

await fs.mkdir(config.sessionDir, { recursive: true })
async function assertSessionDirWritable() { const probe = `${config.sessionDir}/.write-test-${process.pid}`; await fs.writeFile(probe, 'ok'); await fs.unlink(probe) }
async function clearUnlinkedSession() { await fs.rm(config.sessionDir, { recursive: true, force: true }); await fs.mkdir(config.sessionDir, { recursive: true }) }
await assertSessionDirWritable()

const sessionStore = await createSessionStore({ redisUrl: config.redisUrl, key: config.sessionBackupKey, sessionDir: config.sessionDir, encryptionKey: config.sessionEncryptionKey, logger: console })
await sessionStore.restore().catch(error => console.error('Session restore failed:', error))
if (sessionStore.enabled) {
  sessionBackupTimer = setInterval(() => { sessionStore.backup().catch(error => console.error('Session backup failed:', error)) }, config.sessionBackupIntervalMs)
  sessionBackupTimer.unref?.()
  console.log('💾 Persistent session backup: enabled')
}

const app = express(); app.disable('x-powered-by'); app.use(express.json({ limit: '16kb' })); app.use(express.urlencoded({ extended: false }))
function setupAuthorized(req) { if (!config.setupToken) return true; return req.query.token === config.setupToken || req.headers['x-setup-token'] === config.setupToken || req.body?.token === config.setupToken }
function setupPage() {
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${config.botName} • Vincular WhatsApp</title><style>*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#17233a 0,#070d18 48%,#03070e 100%);color:#f5f7fb;font-family:system-ui,-apple-system,sans-serif;min-height:100vh;display:grid;place-items:center;padding:22px}.card{width:min(560px,100%);background:linear-gradient(180deg,#172235ee,#0e1727f4);border:1px solid #2b3b59;border-radius:26px;padding:26px;box-shadow:0 28px 90px #000a}.brand{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}.dot{display:inline-flex;align-items:center;gap:7px;color:#67e1ad;font-size:13px}.dot:before{content:'';width:9px;height:9px;border-radius:50%;background:#45d89a;box-shadow:0 0 18px #45d89a}h1{margin:0 0 7px;font-size:30px}.muted{color:#9aabc5;margin:0 0 24px;line-height:1.45}.row{display:grid;grid-template-columns:145px 1fr;gap:12px}label{display:block;font-size:12px;color:#8798b4;text-transform:uppercase;letter-spacing:.12em;margin:15px 0 8px}input,select{width:100%;background:#0a1322;border:1px solid #304563;color:#fff;border-radius:14px;padding:15px;font-size:16px;outline:none}input:focus,select:focus{border-color:#4d9aff;box-shadow:0 0 0 3px #2f7df622}button{width:100%;margin-top:21px;border:0;border-radius:14px;padding:16px;font-size:16px;font-weight:850;letter-spacing:.04em;background:linear-gradient(90deg,#3d8cff,#2468ef);color:#fff;cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}.status{margin-top:18px;padding:15px;border-radius:14px;background:#091321;border:1px solid #21334e;white-space:pre-wrap;line-height:1.45}.ok{color:#71e6a8}.err{color:#ff8e9b}.code{font-size:32px;font-weight:900;letter-spacing:.18em;text-align:center;color:#79b5ff;margin:14px 0}.tiny{font-size:12px;color:#71839f;margin-top:16px;text-align:center}@media(max-width:480px){.row{grid-template-columns:1fr}.card{padding:20px}h1{font-size:26px}}</style></head><body><main class="card"><div class="brand"><strong>${config.botName}</strong><span class="dot">SERVIDOR ACTIVO</span></div><h1>Vincular WhatsApp</h1><p class="muted">Elige el país y escribe el número al que quieres agregar el bot. Te generaré un código para vincularlo sin QR.</p><form id="f"><label>País y número de WhatsApp</label><div class="row"><select id="cc"><option value="1">🇺🇸 +1</option><option value="52">🇲🇽 +52</option><option value="34">🇪🇸 +34</option><option value="57">🇨🇴 +57</option><option value="58">🇻🇪 +58</option><option value="51">🇵🇪 +51</option><option value="54">🇦🇷 +54</option><option value="56">🇨🇱 +56</option><option value="593">🇪🇨 +593</option><option value="502">🇬🇹 +502</option><option value="503">🇸🇻 +503</option><option value="504">🇭🇳 +504</option><option value="505">🇳🇮 +505</option><option value="506">🇨🇷 +506</option><option value="507">🇵🇦 +507</option><option value="1809">🇩🇴 +1 809</option><option value="1787">🇵🇷 +1 787</option></select><input id="phone" inputmode="numeric" autocomplete="tel" placeholder="3477694617" required></div><button id="btn">GENERAR CÓDIGO</button></form><div id="s" class="status">Preparando panel…</div><div class="tiny">Sesión protegida • Baileys • RANDY SYSTEMS</div></main><script>const token=(location.hash||'').slice(1)||new URLSearchParams(location.search).get('token')||'';const s=document.getElementById('s'),btn=document.getElementById('btn');if(!token){s.className='status err';s.textContent='Falta la clave privada del panel. Abre el enlace privado que te dio Randy Systems.';btn.disabled=true}else{fetch('/status').then(r=>r.json()).then(j=>{s.className='status';s.textContent=j.connection==='open'?'✅ El bot ya está vinculado.':'✅ Panel listo. Escribe el número y genera el código.'}).catch(()=>{s.textContent='Panel listo.'})}document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();if(!token)return;s.className='status';s.textContent='Creando una sesión nueva y generando código…';btn.disabled=true;const cc=document.getElementById('cc').value;let local=document.getElementById('phone').value.replace(/\D/g,'');if(local.startsWith(cc)&&local.length>10)local=local.slice(cc.length);const phone=(cc+local).replace(/\D/g,'');try{const r=await fetch('/api/pair',{method:'POST',headers:{'content-type':'application/json','x-setup-token':token},body:JSON.stringify({phone})});const j=await r.json();if(!r.ok)throw new Error(j.error||'No se pudo generar el código');s.className='status';s.innerHTML='<div class="ok">Código generado para +'+j.phone+'</div><div class="code">'+j.code+'</div><div>Úsalo de inmediato en WhatsApp. El código expira y esta sesión se creó exclusivamente para este intento.</div>'}catch(err){s.className='status err';s.textContent=err.message}finally{btn.disabled=false}})</script></body></html>`
}

app.get('/', (_, res) => res.type('html').send(setupPage()))
app.get('/status', (_, res) => res.json({ ok: true, bot: config.botName, environment: config.env, connection: runtime.connection, uptimeSeconds: Math.floor(process.uptime()), startedAt: startedAt.toISOString(), connectedAt: runtime.connectedAt, reconnectAttempts: runtime.reconnectAttempts }))
app.get('/health', (_, res) => res.status(200).json({ ok: true, status: 'alive' }))
app.get('/ready', (_, res) => { const ready = runtime.connection === 'open'; res.status(ready ? 200 : 503).json({ ok: ready, status: ready ? 'ready' : 'not_ready', connection: runtime.connection, qrPending: runtime.qrPending, lastDisconnectCode: runtime.lastDisconnectCode }) })
app.post('/api/pair', async (req, res) => {
  if (!setupAuthorized(req)) return res.status(401).json({ error: 'Acceso no autorizado.' })
  if (runtime.connection === 'open' || currentSock?.user?.id) return res.status(409).json({ error: 'El bot ya está vinculado. Cierra la sesión actual antes de vincular otro número.' })
  const phone = String(req.body?.phone || '').replace(/\D/g, '')
  if (phone.length < 8 || phone.length > 15) return res.status(400).json({ error: 'Escribe el número completo con código de país.' })
  const elapsed = runtime.pairingRequestedAt ? Date.now() - new Date(runtime.pairingRequestedAt).getTime() : Infinity
  if (pairingBusy || elapsed < config.pairingCooldownMs) return res.status(429).json({ error: 'Espera unos segundos antes de generar otro código.' })
  pairingBusy = true
  pairingRestartInProgress = true
  try {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    const oldSock = currentSock
    currentSock = null
    if (oldSock?.end) await oldSock.end(new Error('Restarting with clean session for phone pairing')).catch(() => {})
    await clearUnlinkedSession()
    runtime.connection = 'pairing_starting'; runtime.qrPending = false; runtime.lastDisconnectCode = null
    const pairingSock = await startBot()
    if (!pairingSock?.requestPairingCode) throw new Error('Pairing API unavailable')
    runtime.pairingPhone = phone; runtime.pairingRequestedAt = new Date().toISOString()
    const rawCode = await pairingSock.requestPairingCode(phone)
    const code = String(rawCode || '').replace(/\s/g, '')
    console.log(`🔐 Fresh pairing code requested for +${phone.slice(0, 3)}******${phone.slice(-2)}`)
    return res.json({ ok: true, phone, code })
  } catch (error) {
    console.error('Pairing code error:', error)
    return res.status(500).json({ error: 'WhatsApp no pudo generar una sesión válida. Intenta nuevamente en unos segundos.' })
  } finally { pairingRestartInProgress = false; pairingBusy = false }
})
const healthServer = app.listen(config.port, config.host, () => { console.log(`🩺 Health server: http://${config.host}:${config.port}/health`); console.log(`💾 Session directory: ${config.sessionDir}`) })

function scheduleReconnect(reason = 'connection closed') {
  if (shuttingDown || pairingRestartInProgress || reconnectTimer) return
  runtime.connection = 'reconnecting'; runtime.reconnectAttempts += 1
  console.log(`🔄 Reconectando en ${config.reconnectDelayMs} ms (${reason})`)
  reconnectTimer = setTimeout(async () => { reconnectTimer = null; try { await startBot() } catch (error) { console.error('Reconnect failed:', error); scheduleReconnect('startup failure') } }, config.reconnectDelayMs)
}

async function startBot() {
  runtime.connection = pairingRestartInProgress ? 'pairing_starting' : (runtime.reconnectAttempts > 0 ? 'reconnecting' : 'starting')
  const { state, saveCreds } = await useMultiFileAuthState(config.sessionDir)
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }))
  const sock = makeWASocket({ auth: state, version, logger, markOnlineOnConnect: true, syncFullHistory: false, generateHighQualityLinkPreview: false, browser: Browsers.ubuntu('Chrome') })
  currentSock = sock
  sock.ev.on('creds.update', async () => { await saveCreds(); if (sessionStore.enabled) await sessionStore.backup().catch(() => {}) })
  sock.ev.on('connection.update', update => {
    const { connection, lastDisconnect, qr } = update
    if (sock !== currentSock) return
    if (qr) { runtime.qrPending = true; runtime.connection = pairingRestartInProgress ? 'pairing_ready' : 'waiting_for_qr'; console.log('\n📱 WhatsApp socket listo para vinculación.\n'); if (config.env !== 'production') qrcode.generate(qr, { small: true }) }
    if (connection === 'open') { runtime.connection = 'open'; runtime.connectedAt = new Date().toISOString(); runtime.lastDisconnectCode = null; runtime.qrPending = false; runtime.reconnectAttempts = 0; runtime.pairingPhone = null; sessionStore.backup().catch(() => {}); console.log(`✅ ${config.botName} conectado como ${sock.user?.id || 'bot'}`) }
    if (connection === 'close') {
      const statusCode = new Boom(lastDisconnect?.error)?.output?.statusCode
      const loggedOut = statusCode === DisconnectReason.loggedOut
      runtime.lastDisconnectAt = new Date().toISOString(); runtime.lastDisconnectCode = statusCode || null; runtime.qrPending = false
      console.log(`⚠️ Conexión cerrada. Código: ${statusCode || 'desconocido'}`)
      if (shuttingDown) { runtime.connection = 'stopped'; return }
      if (pairingRestartInProgress) { runtime.connection = 'pairing_starting'; return }
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
  try { await currentSock?.end?.(new Error(`Process shutdown: ${signal}`)) } catch {}
  healthServer.close(() => { runtime.connection = 'stopped'; process.exit(0) })
  setTimeout(() => process.exit(0), 5000).unref()
}
process.on('SIGTERM', () => shutdown('SIGTERM'))
process.on('SIGINT', () => shutdown('SIGINT'))
process.on('unhandledRejection', error => console.error('Unhandled rejection:', error))
process.on('uncaughtException', error => { console.error('Uncaught exception:', error); process.exit(1) })
startBot().catch(error => { console.error('Initial WhatsApp startup failed:', error); scheduleReconnect('initial startup failure') })
