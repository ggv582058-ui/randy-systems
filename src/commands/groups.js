import { config } from '../config.js'
import { jidToNumber } from '../lib/utils.js'
import { findGroupParticipant, normalizeWhatsAppJid } from '../lib/group-identity.js'

const needGroup = ctx => ctx.isGroup ? null : ctx.reply('❌ Este comando solo funciona en grupos.')
const needAdmin = ctx => (ctx.isAdmin || ctx.isOwner) ? null : ctx.reply('❌ Solo administradores pueden usar este comando.')
const needBotAdmin = ctx => ctx.isBotAdmin ? null : ctx.reply('❌ Necesito ser administrador del grupo.')
function guard(ctx, botAdmin = false) { return needGroup(ctx) || needAdmin(ctx) || (botAdmin ? needBotAdmin(ctx) : null) }

async function changeMember(ctx, action, successMessage) {
  const target = ctx.getTargetJid()
  if (!target) return ctx.reply('Etiqueta o responde al usuario.')
  try {
    const result = await ctx.sock.groupParticipantsUpdate(ctx.jid, [target], action)
    const failed = Array.isArray(result)
      ? result.find(item => item?.status != null && !['200', '201'].includes(String(item.status)))
      : null
    if (failed) return ctx.reply(`❌ WhatsApp rechazó la acción (código ${failed.status}).`)
    return ctx.reply(successMessage)
  } catch (error) {
    console.error(`Group ${action} failed:`, error)
    return ctx.reply('❌ WhatsApp no pudo modificar los permisos del participante.')
  }
}

async function removeNonAdmins(ctx) {
  const usage = 'Uso: ' + config.prefix + 'kill @all'
  if (!ctx.isGroup) return ctx.reply('❌ Este comando solo funciona en grupos.')
  if (!['@all', 'all'].includes(ctx.argText?.trim().toLowerCase())) return ctx.reply(usage + '\nExpulsa a todos los miembros sin rango de administrador.')
  try {
    // Always use fresh roles. Never use cached permissions for mass removal.
    const metadata = await ctx.sock.groupMetadata(ctx.jid)
    const participants = metadata?.participants
    if (!Array.isArray(participants) || !participants.length) return ctx.reply('❌ No pude verificar los miembros del grupo.')
    const sender = await findGroupParticipant(ctx.sock, participants, [ctx.sender, ctx.msg?.key?.participantAlt])
    const bot = await findGroupParticipant(ctx.sock, participants, [ctx.sock.user?.id, ctx.sock.user?.lid])
    const admin = p => Boolean(p?.admin || p?.isAdmin || p?.isSuperAdmin)
    if (!admin(sender)) return ctx.reply('❌ Solo administradores del grupo pueden usar este comando.')
    if (!admin(bot)) return ctx.reply('❌ Necesito ser administrador del grupo.')
    const owner = await findGroupParticipant(ctx.sock, participants, [metadata.owner, metadata.ownerPn])
    const protectedIds = new Set(participants.filter(p => admin(p) || p === sender || p === bot || p === owner).map(p => normalizeWhatsAppJid(p.id)).filter(Boolean))
    const targets = [...new Set(participants.filter(p => p?.id && !admin(p) && p !== sender && p !== bot && p !== owner && !protectedIds.has(normalizeWhatsAppJid(p.id)) && (p.admin == null || p.admin === false) && (p.id.endsWith('@lid') || p.id.endsWith('@s.whatsapp.net'))).map(p => p.id))]
    if (!targets.length) return ctx.reply('🛡️ No hay miembros sin administrador para expulsar.')
    const result = await ctx.sock.groupParticipantsUpdate(ctx.jid, targets, 'remove')
    const rows = Array.isArray(result) ? result : []
    const requested = new Set(targets.map(normalizeWhatsAppJid))
    const confirmed = new Set()
    const rejected = new Set()
    for (const item of rows) {
      const id = normalizeWhatsAppJid(item?.jid)
      if (!requested.has(id) || item?.status == null) continue
      if (['200', '201'].includes(String(item.status))) confirmed.add(id)
      else rejected.add(id)
    }
    const removed = confirmed.size
    const failed = [...rejected].filter(id => !confirmed.has(id)).length
    const unknown = targets.length - removed - failed
    return ctx.reply('🛡️ *RANDY SYSTEMS • ADMINISTRACIÓN*\n\n✅ Expulsiones confirmadas: ' + removed + '\n❌ Rechazadas: ' + failed + '\n⏳ Sin confirmación: ' + unknown + '\n🔒 Administradores protegidos.')
  } catch (error) {
    console.error('Group kill failed:', error)
    return ctx.reply('❌ No pude confirmar la expulsión. Revisa los miembros antes de volver a intentarlo.')
  }
}

export const groupCommands = {
  kill: removeNonAdmins,
  admins: async ctx => { if (needGroup(ctx)) return; const admins = ctx.participants.filter(p => p.admin).map(p => p.id); const text = admins.map((j, i) => `${i + 1}. @${jidToNumber(j)}`).join('\n') || 'Sin administradores.'; return ctx.sock.sendMessage(ctx.jid, { text: `👑 *Administradores*\n${text}`, mentions: admins }, { quoted: ctx.msg }) },
  tagall: async ctx => { if (guard(ctx)) return; const users = ctx.participants.map(p => p.id); const text = users.map(j => `@${jidToNumber(j)}`).join(' '); return ctx.sock.sendMessage(ctx.jid, { text: `📢 ${ctx.argText || 'Atención'}\n\n${text}`, mentions: users }, { quoted: ctx.msg }) },
  hidetag: async ctx => { if (guard(ctx)) return; const users = ctx.participants.map(p => p.id); return ctx.sock.sendMessage(ctx.jid, { text: ctx.argText || '📢 Atención', mentions: users }, { quoted: ctx.msg }) },
  kick: async ctx => { if (['@all', 'all'].includes(ctx.argText?.trim().toLowerCase())) return removeNonAdmins(ctx); if (guard(ctx, true)) return; return changeMember(ctx, 'remove', '✅ Usuario removido.') },
  add: async ctx => { if (guard(ctx, true)) return; const n = ctx.args[0]?.replace(/\D/g, ''); if (!n) return ctx.reply('Uso: .add 15551234567'); await ctx.sock.groupParticipantsUpdate(ctx.jid, [`${n}@s.whatsapp.net`], 'add'); return ctx.reply('✅ Solicitud enviada.') },
  promote: async ctx => { if (guard(ctx, true)) return; return changeMember(ctx, 'promote', '✅ Ahora es administrador.') },
  demote: async ctx => { if (guard(ctx, true)) return; return changeMember(ctx, 'demote', '✅ Administrador removido.') },
  link: async ctx => { if (guard(ctx, true)) return; const code = await ctx.sock.groupInviteCode(ctx.jid); return ctx.reply(`🔗 https://chat.whatsapp.com/${code}`) },
  revoke: async ctx => { if (guard(ctx, true)) return; await ctx.sock.groupRevokeInvite(ctx.jid); return ctx.reply('✅ Enlace del grupo restablecido.') },
  subject: async ctx => { if (guard(ctx, true)) return; if (!ctx.argText) return ctx.reply('Uso: .subject Nuevo nombre'); await ctx.sock.groupUpdateSubject(ctx.jid, ctx.argText); return ctx.reply('✅ Nombre actualizado.') },
  desc: async ctx => { if (guard(ctx, true)) return; if (!ctx.argText) return ctx.reply('Uso: .desc Nueva descripción'); await ctx.sock.groupUpdateDescription(ctx.jid, ctx.argText); return ctx.reply('✅ Descripción actualizada.') },
  open: async ctx => { if (guard(ctx, true)) return; await ctx.sock.groupSettingUpdate(ctx.jid, 'not_announcement'); return ctx.reply('🔓 Grupo abierto.') },
  close: async ctx => { if (guard(ctx, true)) return; await ctx.sock.groupSettingUpdate(ctx.jid, 'announcement'); return ctx.reply('🔒 Grupo cerrado.') },
  groupinfo: async ctx => { if (needGroup(ctx)) return; const m = ctx.groupMetadata; return ctx.reply(`👥 *${m?.subject || 'Grupo'}*\nMiembros: ${m?.participants?.length || 0}\nID: ${ctx.jid}\nDesc: ${m?.desc || 'Sin descripción'}`) },
  grupo: async ctx => ctx.reply(config.groupLink || 'No hay grupo configurado.')
}
