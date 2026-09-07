import { config } from '../config.js'
import { jidToNumber } from '../lib/utils.js'

const needGroup = ctx => ctx.isGroup ? null : ctx.reply('❌ Este comando solo funciona en grupos.')
const needAdmin = ctx => (ctx.isAdmin || ctx.isOwner) ? null : ctx.reply('❌ Solo administradores pueden usar este comando.')
const needBotAdmin = ctx => ctx.isBotAdmin ? null : ctx.reply('❌ Necesito ser administrador del grupo.')
function guard(ctx, botAdmin = false) { return needGroup(ctx) || needAdmin(ctx) || (botAdmin ? needBotAdmin(ctx) : null) }

export const groupCommands = {
  admins: async ctx => { if (needGroup(ctx)) return; const admins = ctx.participants.filter(p => p.admin).map(p => p.id); const text = admins.map((j, i) => `${i + 1}. @${jidToNumber(j)}`).join('\n') || 'Sin administradores.'; return ctx.sock.sendMessage(ctx.jid, { text: `👑 *Administradores*\n${text}`, mentions: admins }, { quoted: ctx.msg }) },
  tagall: async ctx => { if (guard(ctx)) return; const users = ctx.participants.map(p => p.id); const text = users.map(j => `@${jidToNumber(j)}`).join(' '); return ctx.sock.sendMessage(ctx.jid, { text: `📢 ${ctx.argText || 'Atención'}\n\n${text}`, mentions: users }, { quoted: ctx.msg }) },
  hidetag: async ctx => { if (guard(ctx)) return; const users = ctx.participants.map(p => p.id); return ctx.sock.sendMessage(ctx.jid, { text: ctx.argText || '📢 Atención', mentions: users }, { quoted: ctx.msg }) },
  kick: async ctx => { if (guard(ctx, true)) return; const target = ctx.getTargetJid(); if (!target) return ctx.reply('Etiqueta o responde al usuario: .kick @usuario'); await ctx.sock.groupParticipantsUpdate(ctx.jid, [target], 'remove'); return ctx.reply('✅ Usuario removido.') },
  add: async ctx => { if (guard(ctx, true)) return; const n = ctx.args[0]?.replace(/\D/g, ''); if (!n) return ctx.reply('Uso: .add 15551234567'); await ctx.sock.groupParticipantsUpdate(ctx.jid, [`${n}@s.whatsapp.net`], 'add'); return ctx.reply('✅ Solicitud enviada.') },
  promote: async ctx => { if (guard(ctx, true)) return; const target = ctx.getTargetJid(); if (!target) return ctx.reply('Etiqueta o responde al usuario.'); await ctx.sock.groupParticipantsUpdate(ctx.jid, [target], 'promote'); return ctx.reply('✅ Ahora es administrador.') },
  demote: async ctx => { if (guard(ctx, true)) return; const target = ctx.getTargetJid(); if (!target) return ctx.reply('Etiqueta o responde al usuario.'); await ctx.sock.groupParticipantsUpdate(ctx.jid, [target], 'demote'); return ctx.reply('✅ Administrador removido.') },
  link: async ctx => { if (guard(ctx, true)) return; const code = await ctx.sock.groupInviteCode(ctx.jid); return ctx.reply(`🔗 https://chat.whatsapp.com/${code}`) },
  revoke: async ctx => { if (guard(ctx, true)) return; await ctx.sock.groupRevokeInvite(ctx.jid); return ctx.reply('✅ Enlace del grupo restablecido.') },
  subject: async ctx => { if (guard(ctx, true)) return; if (!ctx.argText) return ctx.reply('Uso: .subject Nuevo nombre'); await ctx.sock.groupUpdateSubject(ctx.jid, ctx.argText); return ctx.reply('✅ Nombre actualizado.') },
  desc: async ctx => { if (guard(ctx, true)) return; if (!ctx.argText) return ctx.reply('Uso: .desc Nueva descripción'); await ctx.sock.groupUpdateDescription(ctx.jid, ctx.argText); return ctx.reply('✅ Descripción actualizada.') },
  open: async ctx => { if (guard(ctx, true)) return; await ctx.sock.groupSettingUpdate(ctx.jid, 'not_announcement'); return ctx.reply('🔓 Grupo abierto.') },
  close: async ctx => { if (guard(ctx, true)) return; await ctx.sock.groupSettingUpdate(ctx.jid, 'announcement'); return ctx.reply('🔒 Grupo cerrado.') },
  groupinfo: async ctx => { if (needGroup(ctx)) return; const m = ctx.groupMetadata; return ctx.reply(`👥 *${m?.subject || 'Grupo'}*\nMiembros: ${m?.participants?.length || 0}\nID: ${ctx.jid}\nDesc: ${m?.desc || 'Sin descripción'}`) },
  grupo: async ctx => ctx.reply(config.groupLink || 'No hay grupo configurado.')
}
