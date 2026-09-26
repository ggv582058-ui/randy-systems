import { randomUUID } from 'node:crypto'
import { createClient } from 'redis'

const counterKey = 'randy:portfolio:access:sequence'
const visitorPrefix = 'randy:portfolio:access:visitor:'
const cookieName = 'randy_portfolio_access'
const yearSeconds = 365 * 24 * 60 * 60
const assignAccess = `
local previous = redis.call('GET', KEYS[2])
if previous then return {tonumber(previous), 1} end
redis.call('SETNX', KEYS[1], 1000000)
local next = redis.call('INCR', KEYS[1])
redis.call('SET', KEYS[2], next, 'EX', ${365 * 24 * 60 * 60})
return {next, 0}
`

let client = null
let connecting = null

async function counterClient(url) {
  if (client?.isReady) return client
  if (client && !client.isReady) {
    client.destroy()
    client = null
    connecting = null
  }
  if (!connecting) {
    const next = createClient({ url, socket: { connectTimeout: 2500, reconnectStrategy: false } })
    next.on('error', error => console.error('Portfolio counter Redis:', error.message))
    connecting = next.connect().then(() => {
      client = next
      return next
    }).catch(error => {
      connecting = null
      next.destroy()
      throw error
    })
  }
  return connecting
}

export async function handlePortfolioAccess(request, response, redisUrl) {
  response.set('Cache-Control', 'no-store')
  response.set('X-Content-Type-Options', 'nosniff')
  if (!redisUrl) return response.status(503).json({ error: 'Access sequence unavailable' })

  const match = request.headers.cookie?.match(/(?:^|;\s*)randy_portfolio_access=([0-9a-f-]{36})(?:;|$)/i)
  const visitorId = match ? match[1] : randomUUID()

  try {
    const redis = await counterClient(redisUrl)
    const result = await redis.sendCommand([
      'EVAL', assignAccess, '2', counterKey, visitorPrefix + visitorId
    ])
    const accessId = Number(result?.[0])
    if (!Number.isSafeInteger(accessId)) throw new Error('Invalid access sequence')
    response.cookie(cookieName, visitorId, {
      httpOnly: true,
      secure: request.secure || request.headers['x-forwarded-proto'] === 'https',
      sameSite: 'lax',
      path: '/randy',
      maxAge: yearSeconds * 1000
    })
    return response.json({ accessId, returning: Number(result[1]) === 1 })
  } catch (error) {
    console.error('Portfolio access sequence failed:', error.message)
    return response.status(503).json({ error: 'Access sequence temporarily unavailable' })
  }
}
