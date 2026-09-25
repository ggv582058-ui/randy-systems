# RANDY RESELLER SYSTEMS

Dos bots de Telegram conectados al mismo inventario: uno privado para el Admin y otro para los revendedores, con entrega automática de licencias o códigos digitales de inventario propio.

## Incluye

- Acceso restringido: solo el Admin puede aprobar revendedores.
- Bot Admin privado y bot de revendedores completamente separados.
- Productos con emojis y emoticones; edición de nombre, precio, duración, descripción e instrucciones sin borrar keys ni precios especiales.
- Carga masiva de keys, una por línea, con bloqueo de duplicados.
- Recargas manuales con comprobante y aprobación/rechazo del Admin.
- Entrega automática de una sola key después de descontar el saldo.
- Duración configurable por producto y cuenta regresiva en **Mis keys**.
- Foto, sticker animado y archivo descargable por producto.
- Precios y permisos de compra individuales para cada socio.
- Creación de cuentas con rol de socio o administrador y saldo inicial.
- Anuncios manuales de texto, foto, video, animación, sticker o documento; anuncio diario de texto con hora de Nueva York y opción de pausa.
- Webhook opcional para conectar compras con un API externo.
- Integración Seller API de ZentryAuth para generar hasta 100 keys por lote, consultar, resetear HWID y bloquear/desbloquear licencias desde el bot Admin.
- Venta automática de certificados iOS mediante ChungChi: key interna de un uso, captura de UDID, iPhone/iPad, contraseña P12 y nombre personalizado.
- Webhook ChungChi firmado con HMAC y consulta de respaldo cada 15 segundos en lotes; si el proveedor rechaza el webhook, el bot sigue consultando pedidos y entrega el ZIP cuando aparece. El comprador recibe un enlace privado de estado de inmediato.
- Página privada y temporal para descargar o compartir el `.p12` y `.mobileprovision` con Feather, GBox, Scarlet o Archivos.
- Historial contable, órdenes y estadísticas.
- Compra y aprobación transaccionales para evitar cobrar o entregar dos veces.
- Archivo `render.yaml` y disco persistente para funcionamiento 24/7.
- Endpoint `/health` para que Render supervise el servicio.
- Webhooks HTTPS separados para evitar conflictos durante los despliegues de Render.

> Usa el bot únicamente para productos digitales que tengas autorización de vender. Nunca cargues claves obtenidas sin permiso.

## Configuración rápida

1. Habla con `@BotFather`, crea dos bots y guarda ambos tokens de forma privada.
2. Obtén tu ID numérico de Telegram.
3. Copia `.env.example` como `.env` y completa:

```env
TELEGRAM_BOT_TOKEN=tu_token_privado
ADMIN_BOT_TOKEN=token_privado_del_bot_admin
ADMIN_IDS=7883560984
STORE_NAME=RANDY RESELLER SYSTEMS
SUPPORT_USERNAME=@Randy_zt
DATABASE_PATH=data/reseller.db
KEY_API_URL=https://tu-api.example.com/eventos
KEY_API_TOKEN=token_opcional_del_api
ZENTRY_SELLER_KEY=credencial_seller_privada
ZENTRY_SELLER_SECRET=secreto_seller_privado
ZENTRY_KEY_PREFIX=RANDY
CHUNGCHI_API_KEY=api_key_privada
CHUNGCHI_BASE_URL=https://chungchi.store
CHUNGCHI_PLAN_ID=23
CHUNGCHI_SELL_PRICE_CENTS=350
CERTIFICATE_LINK_TTL_HOURS=24
```

4. Instala y ejecuta:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a; source .env; set +a
python bot.py
```

## Uso

- El Admin abre `/start` en su bot privado y administra desde los botones.
- En **Productos → Editar → 📷 Foto**, puede reemplazar la portada de un producto sin recrearlo. En **Multimedia → 🍎 Portada del certificado**, puede subir la imagen de la oferta de certificados. Se aceptan fotos y archivos JPG/PNG.
- La imagen Randy Mod incluida con el proyecto aparece automáticamente en productos Randy Mod sin foto propia y en la oferta de certificado hasta que el Admin suba otra.
- Los nombres guardan el identificador de emojis personalizados para mostrarlos en el catálogo cuando Telegram permite al bot usarlos; el emoji normal de respaldo sigue visible en los demás clientes.
- En **API Zentry**, el Admin elige producto y cantidad; las licencias toman la duración del producto y pasan al inventario automáticamente.
- En **Control keys**, el Admin puede consultar, resetear HWID, bloquear o desbloquear una licencia.
- Un usuario nuevo pulsa **Solicitar acceso**.
- El Admin recibe **Aprobar / Rechazar**.
- El revendedor solicita una recarga y manda comprobante.
- Tras la aprobación, compra un producto y recibe la key inmediatamente.
- En **Certificado iOS**, una compra de $3.50 genera una key interna y comienza el pedido automático del plan ChungChi configurado.
- **Use Key** permite retomar una key no usada y **Check UDID** consulta solamente los pedidos del usuario actual.

## Pruebas

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

## Render

Sube el proyecto a GitHub y crea un Blueprint usando `render.yaml`. Tu ID Admin (`7883560984`) ya está configurado; Render pedirá `TELEGRAM_BOT_TOKEN` y `ADMIN_BOT_TOKEN`. El disco conserva usuarios, saldo, órdenes e inventario entre reinicios. El servicio con disco funciona en una sola instancia, que es lo correcto para SQLite y el long polling de Telegram.

## Seguridad

- El token nunca está escrito en el código.
- Las acciones Admin validan el rol guardado; el administrador principal nace de `ADMIN_IDS` y puede crear otros administradores.
- La aprobación de recargas es idempotente: pulsar dos veces no duplica saldo.
- La compra usa una transacción exclusiva: una key solo puede venderse una vez.
