# RANDY RESELLER SYSTEMS

Bot de Telegram para administrar revendedores y entregar automáticamente licencias o códigos digitales de inventario propio.

## Incluye

- Acceso restringido: solo el Admin puede aprobar revendedores.
- Panel Admin y panel Regular separados.
- Productos, precios, activación/desactivación y stock.
- Carga masiva de keys, una por línea, con bloqueo de duplicados.
- Recargas manuales con comprobante y aprobación/rechazo del Admin.
- Entrega automática de una sola key después de descontar el saldo.
- Historial contable, órdenes y estadísticas.
- Compra y aprobación transaccionales para evitar cobrar o entregar dos veces.
- Archivo `render.yaml` y disco persistente para funcionamiento 24/7.

> Usa el bot únicamente para productos digitales que tengas autorización de vender. Nunca cargues claves obtenidas sin permiso.

## Configuración rápida

1. Habla con `@BotFather`, crea tu bot y guarda el token de forma privada.
2. Obtén tu ID numérico de Telegram.
3. Copia `.env.example` como `.env` y completa:

```env
TELEGRAM_BOT_TOKEN=tu_token_privado
ADMIN_IDS=7883560984
STORE_NAME=RANDY RESELLER SYSTEMS
SUPPORT_USERNAME=@Randy_zt
DATABASE_PATH=data/reseller.db
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

- El Admin abre `/start` y administra desde los botones.
- Un usuario nuevo pulsa **Solicitar acceso**.
- El Admin recibe **Aprobar / Rechazar**.
- El revendedor solicita una recarga y manda comprobante.
- Tras la aprobación, compra un producto y recibe la key inmediatamente.

## Pruebas

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

## Render

Sube el proyecto a GitHub y crea un Blueprint usando `render.yaml`. Tu ID Admin (`7883560984`) ya está configurado; Render únicamente pedirá `TELEGRAM_BOT_TOKEN`. El disco conserva usuarios, saldo, órdenes e inventario entre reinicios. El servicio con disco funciona en una sola instancia, que es lo correcto para SQLite y el long polling de Telegram.

## Seguridad

- El token nunca está escrito en el código.
- Las acciones Admin validan tanto el rol guardado como `ADMIN_IDS`.
- La aprobación de recargas es idempotente: pulsar dos veces no duplica saldo.
- La compra usa una transacción exclusiva: una key solo puede venderse una vez.
