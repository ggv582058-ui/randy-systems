"""Private admin management of unsold product inventory."""
import html
from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup

class StockKeys:
    def __init__(self, db):
        self.db = db

    async def callback(self, update, context):
        query = update.callback_query
        data = query.data or ''
        if not data.startswith('stockkeys:'):
            return False
        user = self.db.user(update.effective_user.id)
        if context.application.bot_data.get('panel') != 'admin' or not user or user['role'] != 'admin':
            await query.answer('Solo Admin en el bot privado', show_alert=True)
            return True
        parts = data.split(':')
        try:
            action, product_id = parts[1], int(parts[2])
            key_id = int(parts[3]) if len(parts) > 3 else None
            page = max(0, int(parts[4])) if len(parts) > 4 else 0
        except (ValueError, IndexError):
            await query.answer('Opción inválida', show_alert=True)
            return True
        product = self.db.product(product_id)
        if not product:
            await query.answer('Producto no encontrado', show_alert=True)
            return True
        await query.answer()
        if action == 'remove':
            with self.db.transaction() as con:
                removed = con.execute("DELETE FROM inventory_keys WHERE id=? AND product_id=? AND status='available' AND NOT EXISTS (SELECT 1 FROM orders WHERE inventory_key_id=inventory_keys.id)", (key_id, product_id)).rowcount
            await query.message.reply_text('Key retirada del stock.' if removed else 'No se retiró: ya fue vendida o retirada.')
        elif action == 'confirm':
            with self.db.connect() as con:
                key = con.execute("SELECT * FROM inventory_keys WHERE id=? AND product_id=? AND status='available'", (key_id, product_id)).fetchone()
            if not key:
                await query.message.reply_text('La key ya no está disponible.')
                return True
            await query.message.reply_text(f"¿Quitar esta key de {html.escape(product['name'])}?\n<code>{html.escape(key['secret_value'])}</code>\nSe retira del stock del bot; no se revoca en el proveedor.", parse_mode='HTML', reply_markup=Markup([
                [Button('Confirmar quitar', callback_data=f'stockkeys:remove:{product_id}:{key_id}:{page}')],
                [Button('Cancelar', callback_data=f'stockkeys:list:{product_id}:0:{page}')]]))
            return True
        elif action != 'list':
            return True
        with self.db.connect() as con:
            count = con.execute("SELECT COUNT(*) FROM inventory_keys WHERE product_id=? AND status='available'", (product_id,)).fetchone()[0]
            page = min(page, max(0, (count - 1) // 8))
            keys = con.execute("SELECT id,secret_value FROM inventory_keys WHERE product_id=? AND status='available' ORDER BY id LIMIT 8 OFFSET ?", (product_id, page * 8)).fetchall()
        lines = [f"<b>Keys disponibles · {html.escape(product['name'])}</b>", f'Stock: {count}']
        rows = []
        for key in keys:
            lines.append(f"#{key['id']} · <code>{html.escape(key['secret_value'])}</code>")
            rows.append([Button(f"Quitar key #{key['id']}", callback_data=f"stockkeys:confirm:{product_id}:{key['id']}:{page}")])
        nav = []
        if page:
            nav.append(Button('Anterior', callback_data=f'stockkeys:list:{product_id}:0:{page-1}'))
        if (page+1)*8 < count:
            nav.append(Button('Siguiente', callback_data=f'stockkeys:list:{product_id}:0:{page+1}'))
        if nav:
            rows.append(nav)
        rows.append([Button('Añadir keys', callback_data=f'addkeys:{product_id}')])
        await query.message.reply_text('\n'.join(lines), parse_mode='HTML', reply_markup=Markup(rows))
        return True
