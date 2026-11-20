import path from 'node:path'

export function normalizeAccountNumber(phone) {
  const value = String(phone ?? '').replace(/\D/g, '')
  if (!/^\d{8,15}$/.test(value)) throw new TypeError('Número de WhatsApp inválido')
  return value
}

export function accountPaths(sessionDir, baseKey, phone) {
  const number = normalizeAccountNumber(phone)
  return {
    number,
    directory: path.join(sessionDir + '-accounts', number),
    backupKey: baseKey + ':account:' + number
  }
}

export function maskedAccount(phone) {
  const value = normalizeAccountNumber(phone)
  return '+' + value.slice(0, Math.min(2, value.length - 4)) + '••••' + value.slice(-4)
}

export function isMatchingAccountJid(jid, phone) {
  if (typeof jid !== 'string') return false
  return jid.split('@')[0].split(':')[0] === normalizeAccountNumber(phone)
}
