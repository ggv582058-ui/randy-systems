export const ownerCommands = {
  setppbot: async ctx => {
    if (!ctx.isOwner) return ctx.reply('❌ Este comando es solo para el owner.')
    try {
      const { buffer, type } = await ctx.downloadQuotedOrCurrent()
      if (!type.includes('imageMessage')) return ctx.reply('📸 Envía una imagen con *.setppbot* o responde a una imagen con *.setppbot*.')
      await ctx.sock.updateProfilePicture(ctx.sock.user.id, buffer)
      return ctx.reply('✅ Foto de perfil de RANDY SYSTEMS actualizada.')
    } catch (error) {
      console.error('setppbot error:', error)
      return ctx.reply('❌ No pude cambiar la foto. Intenta con una imagen JPG/PNG cuadrada.')
    }
  }
}
