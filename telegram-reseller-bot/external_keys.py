"""Owner-assigned external licenses with absolute expiration, no wallet charge."""
import asyncio
import html
import re
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import StoreError
from zentry_api import ZentryError


def parse_expiry(value):
    if not isinstance(value,str):
        raise ValueError('Falta fecha de vencimiento')
    value=value.strip()
    if not re.search(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',value):
        raise ValueError('Falta fecha y hora exactas')
    if value.endswith(' UTC'):value=value[:-4]+'+00:00'
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds')


def api_expiry(payload,key):
    returned_key=None
    if isinstance(payload,dict):
        from zentry_api import ZentryClient
        returned_key=ZentryClient._find_license_key(payload)
    if returned_key and returned_key.casefold()!=key.casefold():
        raise ValueError('La API respondió con otra key')
    dates=[]
    def visit(data):
        if not isinstance(data,dict):return
        for field in ('expires_at','expiresAt','expiration_date','expiry_date','expiry','expires'):
            if field in data and data[field] not in (None,''):
                dates.append(parse_expiry(data[field]))
        for field in ('data','result','license'):
            visit(data.get(field))
    visit(payload)
    if not dates or len(set(dates))!=1:
        raise ValueError('La API no confirmó una fecha exacta de vencimiento')
    return dates[0]


def status_text(row,language='es',now=None):
    now=now or datetime.now(timezone.utc)
    expires=datetime.fromisoformat(row['expires_at'])
    seconds=max(0,int((expires-now).total_seconds()))
    days,left=divmod(seconds,86400);hours,left=divmod(left,3600);minutes=left//60
    remaining=f'{days} d · {hours} h · {minutes} min' if seconds else ('Expired' if language=='en' else 'Vencida')
    en=language=='en';esc=lambda x:html.escape(str(x))
    source=('ZentryAuth' if row['source']=='api' else ('Expiration recorded by Admin' if en else 'Vencimiento registrado por Admin'))
    return ('🔐 <b>EXTERNAL LICENSE</b>\n\n' if en else '🔐 <b>KEY EXTERNA // RANDY MOD</b>\n\n')+(
        f'📦 {"Product" if en else "Producto"}: <b>{esc(row["name"])}</b>\n'
        f'🔑 Key: <code>{esc(row["secret_value"])}</code>\n'
        f'⏳ {"Time remaining" if en else "Tiempo restante"}: <b>{remaining}</b>\n'
        f'📅 {"Expires" if en else "Vence"}: <b>{expires:%Y-%m-%d %H:%M} UTC</b>\n'
        f'🧾 {"Source" if en else "Fuente"}: {source}\n'
        f'🔄 {"Last update" if en else "Última actualización"}: {esc(row["checked_at"][:16].replace("T"," "))} UTC\n\n'
        + ('Linked by Admin. No new purchase or balance charge.' if en else 'Vinculada por Admin. No se generó otra compra ni se cobró saldo.'))


class ExternalKeys:
    def __init__(self,db,client):self.db=db;self.client=client
    def admin(self,update,context):
        user=self.db.user(update.effective_user.id)
        return bool(context.application.bot_data.get('panel')=='admin' and user and user['role']=='admin')
    async def send_status(self,message,row,language='es'):
        await message.reply_text(status_text(row,language),parse_mode='HTML',reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('Refresh expiration' if language=='en' else 'Actualizar vencimiento',callback_data=f'extkey:refresh:{row["id"]}:{row["user_id"]}')]]))
    async def save(self,message,context,flow,expires,source,admin_id):
        row=self.db.link_external_key(flow['target'],flow['key'],flow['product'],expires,source,admin_id)
        context.user_data.pop('flow',None)
        await message.reply_text('✅ Key vinculada al cliente. Ya aparece en sus Mis keys; no se cobró saldo.')
        await self.send_status(message,row)
    async def handle_text(self,update,context):
        flow=context.user_data.get('flow',{})
        if flow.get('name') not in ('external_key','external_expiry'):return False
        message=update.effective_message
        if not self.admin(update,context):
            context.user_data.pop('flow',None)
            await message.reply_text('⛔ Solo Admin en el bot privado puede vincular keys.');return True
        text=(message.text or '').strip()
        if flow['name']=='external_key':
            key,sep,product=text.partition('|');key=key.strip().replace('–','-').replace('—','-')
            if not re.fullmatch(r'[A-Za-z0-9_-]{4,200}',key):
                await message.reply_text('Escribe la key como texto. Ejemplo: RANDY-Q44E | Randy Mod');return True
            flow.update(key=key,product=(product.strip() if sep else 'Randy Mod')[:100] or 'Randy Mod')
            await message.reply_text('Consultando el vencimiento en ZentryAuth…')
            try:
                info=await asyncio.to_thread(self.client.license_info,key)
                expires=api_expiry(info,key)
                await self.save(message,context,flow,expires,'api',update.effective_user.id)
            except (ZentryError,ValueError):
                flow['name']='external_expiry'
                await message.reply_text('La API no confirmó el vencimiento. Puedes registrar la fecha exacta que muestra tu panel.\n'
                    'Escríbela en UTC: 2026-10-21 05:03 UTC\nNo envíes solo el número de días. Usa /cancel para salir.')
            except StoreError as exc:
                context.user_data.pop('flow',None);await message.reply_text(f'❌ {exc}')
        else:
            try:
                await self.save(message,context,flow,parse_expiry(text),'admin',update.effective_user.id)
            except ValueError:
                await message.reply_text('Fecha inválida. Usa YYYY-MM-DD HH:MM UTC, con la fecha real del panel.')
            except StoreError as exc:
                context.user_data.pop('flow',None);await message.reply_text(f'❌ {exc}')
        return True
    async def callback(self,update,context):
        query=update.callback_query;data=query.data or ''
        if not data.startswith('extkey:'):return False
        parts=data.split(':')
        try:
            action=parts[1]
            if action in ('add','list'):
                if not self.admin(update,context):
                    await query.answer('Solo Admin en el bot privado',show_alert=True);return True
                uid=int(parts[2])
                if not self.db.user(uid):
                    await query.answer('Cliente no encontrado',show_alert=True);return True
                await query.answer()
                if action=='add':
                    context.user_data.pop('records_searching',None)
                    context.user_data['flow']={'name':'external_key','target':uid}
                    await query.message.reply_text('🔑 Envía la key que este cliente te compró por otro medio.\n'
                        'Puedes indicar el producto: RANDY-Q44E | Randy Mod\nIntentaré consultar su fecha real; no se reiniciarán los días ni se cobrará saldo.')
                else:
                    rows=self.db.external_keys_for_user(uid)
                    if not rows:await query.message.reply_text('Este cliente todavía no tiene keys externas vinculadas.')
                    for row in rows:await self.send_status(query.message,row)
            elif action=='refresh':
                kid,uid=int(parts[2]),int(parts[3])
                user=self.db.user(update.effective_user.id)
                if not self.admin(update,context) and (update.effective_user.id!=uid or not user or user['role'] not in ('admin','reseller')):
                    await query.answer('Esta key no pertenece a tu cuenta',show_alert=True);return True
                row=self.db.external_key(kid,uid)
                if not row:
                    await query.answer('Key no encontrada',show_alert=True);return True
                await query.answer('Consultando…')
                try:
                    info=await asyncio.to_thread(self.client.license_info,row['secret_value'])
                    expires=api_expiry(info,row['secret_value'])
                    row=self.db.refresh_external_key(kid,uid,expires) or row
                except (ZentryError,ValueError):
                    await query.message.reply_text('No se pudo actualizar con ZentryAuth. Se conserva el último vencimiento registrado.')
                language=user['language'] if user else 'es'
                await self.send_status(query.message,row,language)
            else:await query.answer('Opción inválida',show_alert=True)
        except (ValueError,IndexError):await query.answer('Opción inválida',show_alert=True)
        return True
