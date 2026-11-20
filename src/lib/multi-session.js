import fs from 'node:fs/promises'
import pino from 'pino'
import { createClient } from 'redis'
import { Boom } from '@hapi/boom'
import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState
} from '@whiskeysockets/baileys'
import { createSessionStore } from './session-store.js'
import { accountPaths, maskedAccount, normalizeAccountNumber } from './multi-session-paths.js'

function pairingError(message, status = 409) {
  const error = new Error(message)
  error.httpStatus = status
  return error
}

// Keep the existing primary WhatsApp session untouched. Secondary accounts
// each own their auth directory, persistent Redis key, socket and reconnect
// timer. No account ever logs out or deletes another account's credentials.
export async function createExtraAccountManager({ config, logger, onMessage }) {
  const accounts = new Map()
  const registryKey = config.sessionBackupKey + ':accounts'
  const accountLimit = Math.max(1, Number(config.maxLinkedAccounts) || 6)
  let registry = null
  let stopping = false

  async function openSocket(account) {
    if (stopping) return null
    if (account.opening) return account.opening
    account.opening = (async () => {
      const { state, saveCreds } = await useMultiFileAuthState(account.directory)
      const versionInfo = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }))
      const sock = makeWASocket({
        auth: state,
        version: versionInfo.version,
        logger,
        markOnlineOnConnect: true,
        syncFullHistory: false,
        generateHighQualityLinkPreview: false,
        browser: Browsers.ubuntu('Chrome')
      })
      account.socket = sock
      account.connection = account.reconnectAttempts ? 'reconnecting' : 'starting'
      sock.ev.on('creds.update', async () => {
        try {
          await saveCreds()
          await account.store.backup()
        } catch (error) {
          console.error('[multi-session] credentials backup failed', maskedAccount(account.phone), error?.message)
        }
      })
      sock.ev.on('connection.update', update => {
        if (account.socket !== sock || stopping) return
        const { connection, lastDisconnect, qr } = update
        if (qr) account.connection = 'waiting_for_pairing'
        if (connection === 'open') {
          account.connection = 'open'
          account.connectedAt = new Date().toISOString()
          account.reconnectAttempts = 0
          account.lastDisconnectCode = null
          void account.store.backup().catch(error => console.error('[multi-session] backup:', error?.message))
          console.log('[multi-session] connected', maskedAccount(account.phone))
        }
        if (connection === 'close') {
          const code = new Boom(lastDisconnect?.error)?.output?.statusCode || null
          account.lastDisconnectCode = code
          account.connection = code === DisconnectReason.loggedOut ? 'logged_out' : 'disconnected'
          if (code === DisconnectReason.loggedOut) {
            console.warn('[multi-session] WhatsApp logged out', maskedAccount(account.phone))
            return
          }
          scheduleReconnect(account)
        }
      })
      sock.ev.on('messages.upsert', ({ messages, type }) => {
        if (type !== 'notify') return
        for (const message of messages) {
          void onMessage(sock, message).catch(error => console.error('[multi-session] command error', error?.message))
        }
      })
      return sock
    })()
    try {
      return await account.opening
    } finally {
      account.opening = null
    }
  }

  function scheduleReconnect(account) {
    if (stopping || account.reconnectTimer || account.connection === 'logged_out') return
    account.connection = 'reconnecting'
    account.reconnectAttempts += 1
    const delay = Math.max(config.reconnectDelayMs, 1000)
    account.reconnectTimer = setTimeout(async () => {
      account.reconnectTimer = null
      try { await openSocket(account) }
      catch (error) {
        console.error('[multi-session] reconnect error', maskedAccount(account.phone), error?.message)
        scheduleReconnect(account)
      }
    }, delay)
  }

  async function ensureAccount(phone) {
    const number = normalizeAccountNumber(phone)
    if (accounts.has(number)) return accounts.get(number)
    const { directory, backupKey } = accountPaths(config.sessionDir, config.sessionBackupKey, number)
    await fs.mkdir(directory, { recursive: true })
    const store = await createSessionStore({
      redisUrl: config.redisUrl,
      key: backupKey,
      sessionDir: directory,
      encryptionKey: config.sessionEncryptionKey,
      logger: console
    })
    try { await store.restore() }
    catch (error) { await store.close(); throw error }
    const account = {
      phone: number, directory, store, socket: null, opening: null,
      connection: 'starting', connectedAt: null, reconnectAttempts: 0,
      reconnectTimer: null, backupTimer: null, lastPairAt: 0,
      lastDisconnectCode: null
    }
    account.backupTimer = setInterval(() => {
      void store.backup().catch(error => console.error('[multi-session] backup:', error?.message))
    }, config.sessionBackupIntervalMs)
    account.backupTimer.unref?.()
    accounts.set(number, account)
    return account
  }

  async function restore() {
    if (!config.redisUrl) {
      console.warn('[multi-session] REDIS_URL missing: additional accounts disabled to protect them from restart losses.')
      return
    }
    try {
      registry = createClient({ url: config.redisUrl })
      registry.on('error', error => console.error('[multi-session] Redis registry:', error?.message))
      await registry.connect()
      const phoneNumbers = await registry.sMembers(registryKey)
      for (const phone of phoneNumbers.slice(0, accountLimit)) {
        try {
          const account = await ensureAccount(phone)
          await openSocket(account)
        } catch (error) {
          console.error('[multi-session] could not restore account', maskedAccount(phone), error?.message)
        }
      }
      console.log('[multi-session] restored', accounts.size, 'secondary account slots')
    } catch (error) {
      console.error('[multi-session] registry unavailable:', error?.message)
      if (registry?.isOpen) await registry.quit().catch(() => {})
      registry = null
    }
  }

  async function pair(phone) {
    if (!registry?.isReady) {
      throw pairingError('Para agregar varios números sin perder sus sesiones, configura REDIS_URL y vuelve a intentar.', 503)
    }
    if (!config.sessionEncryptionKey) {
      throw pairingError('Configura SESSION_ENCRYPTION_KEY para proteger las sesiones de las cuentas adicionales.', 503)
    }
    const number = normalizeAccountNumber(phone)
    let account = accounts.get(number)
    if (!account && accounts.size >= accountLimit) {
      throw pairingError('Se alcanzó el límite de cuentas activas. Amplía MAX_LINKED_ACCOUNTS solo si el servidor tiene capacidad.', 409)
    }
    if (account?.connection === 'open' || account?.socket?.user?.id) {
      throw pairingError('Este número ya está vinculado o reconectando. No se cerró ninguna sesión.', 409)
    }
    if (account && Date.now() - account.lastPairAt < config.pairingCooldownMs) {
      throw pairingError('Espera unos segundos antes de solicitar otro código para ese número.', 429)
    }
    if (!account) {
      // The account index is persistent before WhatsApp can accept a pairing.
      await registry.sAdd(registryKey, number)
      account = await ensureAccount(number)
    }
    const sock = account.socket || await openSocket(account)
    if (typeof sock?.requestPairingCode !== 'function') {
      throw pairingError('WhatsApp no habilitó la vinculación de esta cuenta.', 503)
    }
    account.lastPairAt = Date.now()
    const code = String(await sock.requestPairingCode(number) || '').replace(/\s/g, '')
    if (!code) throw pairingError('WhatsApp devolvió un código vacío.', 502)
    account.connection = 'pairing'
    return { phone: number, code }
  }

  function overview() {
    return [...accounts.values()].map(account => ({
      phone: maskedAccount(account.phone),
      connection: account.connection,
      connectedAt: account.connectedAt,
      lastDisconnectCode: account.lastDisconnectCode
    }))
  }

  async function close() {
    stopping = true
    const all = [...accounts.values()]
    await Promise.allSettled(all.map(async account => {
      if (account.reconnectTimer) clearTimeout(account.reconnectTimer)
      if (account.backupTimer) clearInterval(account.backupTimer)
      await account.store.backup().catch(() => {})
      await account.store.close().catch(() => {})
      try { await account.socket?.end?.(new Error('Process shutting down')) } catch {}
    }))
    if (registry?.isOpen) await registry.quit().catch(() => {})
  }

  return {
    restore, pair, overview, close,
    connectedCount: () => [...accounts.values()].filter(x => x.connection === 'open').length,
    isReady: () => Boolean(registry?.isReady)
  }
}
