"""Private, read-only customer and certificate records for the owner bot."""
from __future__ import annotations

import html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

PAGE_SIZE = 6
STATUS = {'completed': 'Firmado', 'pending': 'Pendiente', 'processing': 'Procesando',
          'submitting': 'Enviando', 'review': 'En revisión', 'failed': 'Fallido',
          'cancelled': 'Cancelado', 'revoked': 'Revocado'}
MENU = {'👤 Clientes': 'clients', '👤 Customers': 'clients',
        '🍎 Certificados': 'certificates', '🍎 Certificates': 'certificates',
        '📚 Compras': 'purchases', '📚 Purchases': 'purchases'}


def esc(value):
    return html.escape(str(value if value is not None else '—'))


def money(value):
    return f'${int(value or 0) / 100:.2f}'


def date(value):
    return esc(str(value or '—')[:16].replace('T', ' '))


def client_text(row):
    return (
        '👤 <b>CLIENTE // RANDY MOD</b>\n\n'
        f'<b>{esc(row["full_name"])}</b>\n'
        f'Usuario: {esc("@" + row["username"] if row["username"] else "Sin usuario público")}\n'
        f'ID Telegram: <code>{row["telegram_id"]}</code>\n'
        f'Acceso: <b>{esc(row["role"])}</b> · {esc(row["tier"])}\n'
        f'Catálogo: {esc({"all":"Todo", "certificates":"Certificados", "products":"Productos"}.get(row["access_scope"], row["access_scope"]))}\n'
        f'Saldo: <b>{money(row["balance_cents"])}</b>\n'
        f'Registro: {date(row["created_at"])} UTC\n\n'
        f'Compras de productos: <b>{row["product_count"]}</b>\n'
        f'Keys de certificado compradas: <b>{row["certificate_key_count"]}</b>\n'
        f'Certificados registrados: <b>{row["certificate_count"]}</b>\n'
        f'Keys externas vinculadas: <b>{row["external_key_count"]}</b>\n'
        f'Total comprado: <b>{money(row["spent_cents"])}</b>'
    )


def certificate_text(row):
    return (
        '🍎 <b>CERTIFICADO // ADMIN</b>\n\n'
        f'Cliente: <b>{esc(row["display_name"])}</b>\n'
        f'Estado: <b>{esc(STATUS.get(row["status"], row["status"]))}</b>\n'
        f'Equipo: <b>{"iPhone" if row["device"] == "iphone" else "iPad"}</b>\n'
        f'UDID: <code>{esc(row["udid"])}</code>\n'
        f'Plan: <b>#{row["plan_id"]}</b>\n'
        f'Pedido: <code>{esc(row["provider_order_code"] or "Pendiente")}</code> · #{row["id"]}\n\n'
        f'Cuenta: {esc("@" + row["username"] if row["username"] else row["full_name"])}\n'
        f'ID Telegram: <code>{row["user_id"]}</code>\n'
        f'Pagado: <b>{money(row["price_cents"])}</b>\n'
        f'Compra: {date(row["purchased_at"])} UTC\n'
        f'Registro: {date(row["created_at"])} UTC\n'
        f'Completado: {date(row["completed_at"])} UTC\n'
        f'Entrega: {date(row["delivered_at"])} UTC\n'
        f'Última actualización: {date(row["updated_at"])} UTC'
        + ('\n\n⚠️ El pedido tiene un error registrado; revisa el proveedor.' if row['last_error'] else '')
    )


class AdminRecords:
    def __init__(self, db):
        self.db = db

    def allowed(self, update, context):
        user = self.db.user(update.effective_user.id)
        return bool(context.application.bot_data.get('panel') == 'admin' and user and user['role'] == 'admin')

    def client(self, uid):
        with self.db.connect() as con:
            return con.execute('''SELECT u.*,
                (SELECT COUNT(*) FROM orders WHERE user_id=u.telegram_id) product_count,
                (SELECT COUNT(*) FROM certificate_keys WHERE user_id=u.telegram_id) certificate_key_count,
                (SELECT COUNT(*) FROM certificate_orders WHERE user_id=u.telegram_id) certificate_count,
                (SELECT COUNT(*) FROM external_client_keys WHERE user_id=u.telegram_id) external_key_count,
                COALESCE((SELECT -SUM(amount_cents) FROM ledger WHERE user_id=u.telegram_id AND kind='purchase'),0) spent_cents
                FROM users u WHERE telegram_id=?''', (uid,)).fetchone()

    def certificate(self, order_id):
        with self.db.connect() as con:
            return con.execute('''SELECT o.*,u.username,u.full_name,k.price_cents,k.created_at purchased_at
                FROM certificate_orders o JOIN users u ON u.telegram_id=o.user_id
                JOIN certificate_keys k ON k.id=o.certificate_key_id WHERE o.id=?''', (order_id,)).fetchone()

    def rows(self, section, page=0, uid=None, search=''):
        page = max(0, min(int(page), 100000))
        # Parameter binding and literal substring matching keep user search safe.
        needle = search.casefold()[:120].lstrip('@')
        with self.db.connect() as con:
            if section == 'clients':
                return con.execute('''SELECT u.* FROM users u WHERE ?='' OR
                    instr(lower(u.full_name),?)>0 OR instr(lower(COALESCE(u.username,'')),?)>0 OR
                    CAST(u.telegram_id AS TEXT)=? OR EXISTS (
                    SELECT 1 FROM certificate_orders c WHERE c.user_id=u.telegram_id AND
                    (instr(lower(c.display_name),?)>0 OR instr(lower(c.udid),?)>0))
                    ORDER BY u.created_at DESC,u.telegram_id DESC LIMIT ? OFFSET ?''',
                    (needle,needle,needle,needle,needle,needle,PAGE_SIZE+1,page*PAGE_SIZE)).fetchall()
            if section == 'certificates':
                return con.execute('''SELECT o.id,o.display_name,o.status,o.device,o.udid,o.user_id,u.username,u.full_name
                    FROM certificate_orders o JOIN users u ON u.telegram_id=o.user_id
                    WHERE (? IS NULL OR o.user_id=?) AND (?='' OR
                    instr(lower(o.display_name),?)>0 OR instr(lower(o.udid),?)>0 OR
                    instr(lower(COALESCE(u.username,'')),?)>0 OR instr(lower(u.full_name),?)>0 OR
                    CAST(o.user_id AS TEXT)=? OR lower(COALESCE(o.provider_order_code,''))=?)
                    ORDER BY o.id DESC LIMIT ? OFFSET ?''',
                    (uid,uid,needle,needle,needle,needle,needle,needle,needle,PAGE_SIZE+1,page*PAGE_SIZE)).fetchall()
            if section == 'purchases':
                return con.execute('''SELECT l.*,u.username,u.full_name,p.name product_name,o.duration_days,
                    CASE WHEN k.id IS NOT NULL THEN 'certificate' ELSE 'product' END kind,
                    k.status key_status,c.id certificate_id,c.display_name,c.status certificate_status
                    FROM ledger l JOIN users u ON u.telegram_id=l.user_id
                    LEFT JOIN orders o ON l.reference='order:'||o.id
                    LEFT JOIN products p ON p.id=o.product_id
                    LEFT JOIN certificate_keys k ON l.reference='certificate-key:'||k.id
                    LEFT JOIN certificate_orders c ON c.certificate_key_id=k.id
                    WHERE l.kind='purchase' AND (? IS NULL OR l.user_id=?)
                    ORDER BY l.id DESC LIMIT ? OFFSET ?''', (uid,uid,PAGE_SIZE+1,page*PAGE_SIZE)).fetchall()
        return []

    async def send(self, message, text, buttons):
        await message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)

    async def show(self, message, context, section, page=0, uid=None):
        search = context.user_data.get('records_search', {}).get(section, '') if uid is None else ''
        rows = self.rows(section, page, uid, search)
        titles = {'clients':'CLIENTES', 'certificates':'CERTIFICADOS', 'purchases':'COMPRAS'}
        text = f'📚 <b>{titles[section]} // ADMIN</b>\n'
        text += f'Página {page + 1}' + (f' · Cuenta <code>{uid}</code>' if uid is not None else '')
        if search:
            text += f'\nBúsqueda: <b>{esc(search)}</b>'
        buttons = []
        for row in rows[:PAGE_SIZE]:
            if section == 'clients':
                tag = '@'+row['username'] if row['username'] else row['full_name']
                text += f'\n\n<b>{esc(tag)}</b>\n<code>{row["telegram_id"]}</code> · {money(row["balance_cents"])}'
                buttons.append([InlineKeyboardButton(f'Ver {tag[:38]}',callback_data=f'records:client:{row["telegram_id"]}')])
            elif section == 'certificates':
                text += f'\n\n<b>#{row["id"]} · {esc(row["display_name"])}</b>\n{esc(STATUS.get(row["status"],row["status"]))} · {"iPhone" if row["device"]=="iphone" else "iPad"}'
                buttons.append([InlineKeyboardButton(f'#{row["id"]} · {row["display_name"][:35]}',callback_data=f'records:certificate:{row["id"]}')])
            else:
                name = row['product_name'] or 'Certificado iOS'
                tag = '@'+row['username'] if row['username'] else row['full_name']
                text += f'\n\n<b>{esc(name)}</b> · {money(-row["amount_cents"])}\n{esc(tag)} · {date(row["created_at"])} UTC\nReferencia: <code>{esc(row["reference"])}</code>'
                if row['kind']=='certificate':
                    text += f'\n{esc(row["display_name"] or "Sin registrar")} · {esc(STATUS.get(row["certificate_status"], row["key_status"]))}'
                buttons.append([InlineKeyboardButton(f'Cuenta · {tag[:35]}',callback_data=f'records:client:{row["user_id"]}')])
                if row['certificate_id']:
                    buttons.append([InlineKeyboardButton('Ver certificado',callback_data=f'records:certificate:{row["certificate_id"]}')])
        if not rows:
            text += '\n\nNo hay registros para esta consulta.'
        nav = []
        target = str(uid) if uid is not None else 'all'
        if page:
            nav.append(InlineKeyboardButton('← Anterior',callback_data=f'records:list:{section}:{page-1}:{target}'))
        if len(rows)>PAGE_SIZE:
            nav.append(InlineKeyboardButton('Siguiente →',callback_data=f'records:list:{section}:{page+1}:{target}'))
        if nav:
            buttons.append(nav)
        if section != 'purchases' and uid is None:
            buttons.append([InlineKeyboardButton('Buscar',callback_data=f'records:search:{section}'),InlineKeyboardButton('Ver todos',callback_data=f'records:clear:{section}')])
        buttons.append([InlineKeyboardButton('Clientes',callback_data='records:list:clients:0:all'),InlineKeyboardButton('Certificados',callback_data='records:list:certificates:0:all')])
        await self.send(message,text,buttons)

    async def menu(self, update, context, text):
        section = MENU.get(text)
        searching = context.user_data.get('records_searching')
        if not section and not searching:
            return False
        if not self.allowed(update,context):
            await update.effective_message.reply_text('⛔ Estos datos solo están disponibles para Admin en el bot privado.')
            return True
        context.user_data.pop('flow',None)
        if section:
            context.user_data.pop('records_searching',None)
            context.user_data.setdefault('records_search',{}).pop(section,None)
        else:
            section = context.user_data.pop('records_searching')
            context.user_data.setdefault('records_search',{})[section]=text[:120]
        await self.show(update.effective_message,context,section)
        return True

    async def callback(self, update, context):
        query = update.callback_query
        if not str(query.data or '').startswith('records:'):
            return False
        if not self.allowed(update,context):
            await query.answer('Solo Admin en el bot privado',show_alert=True)
            return True
        parts = query.data.split(':')
        try:
            action = parts[1]
            if action=='list' and parts[2] in ('clients','certificates','purchases'):
                page=max(0,min(int(parts[3]),100000))
                uid=None if parts[4]=='all' else int(parts[4])
                await query.answer()
                context.user_data.pop('records_searching',None)
                await self.show(query.message,context,parts[2],page,uid)
            elif action in ('search','clear') and parts[2] in ('clients','certificates'):
                await query.answer()
                if action=='search':
                    context.user_data['records_searching']=parts[2]
                    context.user_data.pop('flow',None)
                    await query.message.reply_text('Escribe nombre, @usuario, ID Telegram o UDID. Usa /cancel para salir.')
                else:
                    context.user_data.setdefault('records_search',{}).pop(parts[2],None)
                    context.user_data.pop('records_searching',None)
                    await self.show(query.message,context,parts[2])
            elif action=='client':
                row=self.client(int(parts[2]))
                await query.answer()
                if row is None:
                    await query.message.reply_text('Cliente no encontrado.')
                else:
                    uid=row['telegram_id']
                    await self.send(query.message,client_text(row),[
                        [InlineKeyboardButton('🔑 Vincular key externa',callback_data=f'extkey:add:{uid}')],
                        [InlineKeyboardButton('Keys externas del cliente',callback_data=f'extkey:list:{uid}')],
                        [InlineKeyboardButton('Certificados del cliente',callback_data=f'records:list:certificates:0:{uid}')],
                        [InlineKeyboardButton('Historial de compras',callback_data=f'records:list:purchases:0:{uid}')],
                        [InlineKeyboardButton('Volver a clientes',callback_data='records:list:clients:0:all')]])
            elif action=='certificate':
                row=self.certificate(int(parts[2]))
                await query.answer()
                if row is None:
                    await query.message.reply_text('Certificado no encontrado.')
                else:
                    await self.send(query.message,certificate_text(row),[
                        [InlineKeyboardButton('Ver cuenta del cliente',callback_data=f'records:client:{row["user_id"]}')],
                        [InlineKeyboardButton('Historial de compras',callback_data=f'records:list:purchases:0:{row["user_id"]}')],
                        [InlineKeyboardButton('Volver a certificados',callback_data='records:list:certificates:0:all')]])
            else:
                await query.answer('Opción no disponible',show_alert=True)
        except (ValueError,IndexError):
            await query.answer('Opción inválida',show_alert=True)
        return True
