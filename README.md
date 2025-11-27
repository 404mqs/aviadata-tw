# Bot de Twitter para Aviadata - Standalone

Bot automático de Twitter que publica estadísticas de aviación argentina usando datos de la API de Aviadata.

## 🚀 Características

- **Cronograma automático**: 14 tipos de tweets distribuidos a lo largo del mes
- **Recuperación automática**: Detecta y publica tweets perdidos
- **Logs persistentes**: SQLite para tracking de tweets enviados
- **Detección de nuevos meses**: Se actualiza automáticamente cuando hay datos nuevos
- **Rate limit handling**: Manejo inteligente de límites de Twitter
- **Contenido variado**: Tweets humanizados con múltiples variaciones

## 📋 Cronograma de Posts

| Día | Tipo de Post | Descripción |
|-----|--------------|-------------|
| 0 | Resumen mensual | KPIs generales del mes nuevo |
| 2 | Top aerolíneas | Ranking de aerolíneas por vuelos |
| 4 | Rutas transitadas | Rutas más populares |
| 6 | Aeropuertos activos | Aeropuertos con más movimiento |
| 8 | Destinos internacionales | Top países de destino |
| 10 | Evolución histórica | Comparativa últimos 4 meses |
| 12 | Ocupación promedio | Porcentaje de ocupación por aerolínea |
| 14 | Comparativa aeropuertos | Análisis de aeropuertos principales |
| 16 | Récords y curiosidades | Datos curiosos del mes |
| 18 | Aerolíneas inusuales | Vuelos poco comunes |
| 20 | Comparativa mensual | Vs mes anterior |
| 22 | Rutas internacionales | Top rutas internacionales |
| 24 | Promedios por clase | Análisis por clase de vuelo |
| 26 | Recap gráfico | Resumen visual del mes |

## 🛠️ Instalación

### 1. Clonar/Descargar archivos
```bash
# Si tienes git
git clone <tu-repo>
cd twitter-bot-standalone

# O simplemente descarga los archivos:
# - bot.py
# - requirements.txt
# - README.md
# - .env.example
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar credenciales

Copia el archivo de ejemplo y completa con tus credenciales:

```bash
cp .env.example .env
```

Edita `.env` y completa:

```env
TWITTER_API_KEY=tu_api_key_real
TWITTER_API_SECRET=tu_api_secret_real
TWITTER_ACCESS_TOKEN=tu_access_token_real
TWITTER_ACCESS_SECRET=tu_access_secret_real
TWITTER_BEARER_TOKEN=tu_bearer_token_real
AVIADATA_API_URL=https://tu-backend-aviadata.com
```

#### Obtener credenciales de Twitter

1. Ve a [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard)
2. Crea una nueva App o selecciona una existente
3. Ve a "Keys and tokens"
4. Genera y copia:
   - **API Key** → `TWITTER_API_KEY`
   - **API Secret** → `TWITTER_API_SECRET`
   - **Bearer Token** → `TWITTER_BEARER_TOKEN`
   - **Access Token** → `TWITTER_ACCESS_TOKEN`
   - **Access Secret** → `TWITTER_ACCESS_SECRET`

**Nota**: Este bot usa Twitter API v2. Necesitas al menos acceso "Elevated" (gratuito) o "Basic" ($100/mes) para publicar tweets.

### 4. Ejecutar el bot
```bash
python bot.py
```

## ⚙️ Configuración

### Variables de entorno

| Variable | Descripción | Requerida | Default |
|----------|-------------|-----------|---------|
| `TWITTER_API_KEY` | API Key de Twitter | ✅ Sí | - |
| `TWITTER_API_SECRET` | API Secret de Twitter | ✅ Sí | - |
| `TWITTER_ACCESS_TOKEN` | Access Token de Twitter | ✅ Sí | - |
| `TWITTER_ACCESS_SECRET` | Access Secret de Twitter | ✅ Sí | - |
| `TWITTER_BEARER_TOKEN` | Bearer Token de Twitter (API v2) | ✅ Sí | - |
| `AVIADATA_API_URL` | URL de la API de Aviadata | ✅ Sí | - |
| `DATA_DIR` | Directorio para logs SQLite | ❌ No | `.` (directorio actual) |

### Obtener credenciales de Twitter

1. Ve a [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard)
2. Crea una nueva App
3. Ve a "Keys and Tokens"
4. Genera:
   - API Key (TWITTER_API_KEY)
   - API Secret (TWITTER_API_SECRET)
   - Bearer Token (TWITTER_BEARER_TOKEN)
   - Access Token (TWITTER_ACCESS_TOKEN)
   - Access Secret (TWITTER_ACCESS_SECRET)

## 🏃 Ejecución

### Modo Desarrollo (una sola vez)
```bash
python bot.py
```
El bot se ejecutará hasta que lo detengas con `Ctrl+C`.

### Modo Producción (servicio)

#### En Linux/macOS con systemd:
```bash
# Crear archivo de servicio
sudo nano /etc/systemd/system/aviadata-twitter-bot.service

# Contenido del archivo:
[Unit]
Description=Aviadata Twitter Bot
After=network.target

[Service]
Type=simple
User=tu-usuario
WorkingDirectory=/ruta/al/bot
EnvironmentFile=/ruta/al/bot/.env
ExecStart=/usr/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target

# Activar servicio
sudo systemctl enable aviadata-twitter-bot
sudo systemctl start aviadata-twitter-bot
sudo systemctl status aviadata-twitter-bot
```

#### En Windows (Task Scheduler):
1. Abre Task Scheduler
2. Create Basic Task
3. Trigger: "When the computer starts"
4. Action: "Start a program"
5. Program: `python`
6. Arguments: `C:\\ruta\\al\\bot.py`
7. Start in: `C:\\ruta\\al\\directorio\\del\\bot`

#### Con Docker:
```bash
# Crear Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY bot.py .
CMD ["python", "bot.py"]

# Build y run
docker build -t aviadata-twitter-bot .
docker run -d --name bot \
  --env-file .env \
  aviadata-twitter-bot
```

#### En Railway (Recomendado para producción):

**Setup inicial:**

1. **Crear proyecto en Railway**:
   - Ve a [railway.app](https://railway.app)
   - Create New Project → Deploy from GitHub repo
   - Selecciona tu repo `aviadata-tw`

2. **Agregar volumen persistente**:
   - En tu servicio → Settings → Volumes
   - Click "New Volume"
   - Mount path: `/data`
   - Esto permite que la base de datos SQLite persista entre redeploys

3. **Configurar variables de entorno**:
   - En Variables, agregar:
     ```
     TWITTER_API_KEY=tu_key
     TWITTER_API_SECRET=tu_secret
     TWITTER_ACCESS_TOKEN=tu_token
     TWITTER_ACCESS_SECRET=tu_access_secret
     TWITTER_BEARER_TOKEN=tu_bearer
     AVIADATA_API_URL=https://aviadata-backend-production-8fa2.up.railway.app
     ```

4. **Deploy**:
   - Railway auto-detecta Python y ejecuta `bot.py`
   - El bot usará automáticamente `/data` para la DB SQLite
   - Cada redeploy mantiene el estado (tweets enviados, mes actual, etc.)

**Ventajas de Railway:**
- ✅ Persistencia automática con volumen `/data`
- ✅ No se pierde el cronograma en redeploys
- ✅ Logs centralizados en Railway dashboard
- ✅ Auto-restart si el bot crashea
- ✅ Deploy automático en cada push a GitHub

## 📊 Monitoring y Logs

### Ver logs en tiempo real
```bash
# El bot imprime logs en stdout
python bot.py

# Para guardar logs en archivo
python bot.py > bot.log 2>&1
```

### Base de datos de logs
El bot crea `twitter_bot_logs.db` (SQLite) con:

- **tweets_log**: Todos los tweets enviados con timestamps, IDs, errores
- **bot_state**: Estado interno del bot (mes actual, etc.)

### Consultar logs
```bash
# Instalar sqlite3 si no lo tienes
sqlite3 twitter_bot_logs.db

# Ver últimos tweets
.headers on
.mode table
SELECT date_posted, tipo_post, status, mes_relacionado FROM tweets_log ORDER BY date_posted DESC LIMIT 10;

# Ver estado del bot
SELECT * FROM bot_state;
```

## 🔧 Comandos útiles

### Test de conexión
```python
# Crear test.py
from bot import TwitterBot

bot = TwitterBot()

# Test 1: API de Aviadata
data = bot.api_client.make_request("/vuelos/kpis", {"months": ["2025-09"], "all_periods": False})
print("API OK:" if data else "API ERROR")

# Test 2: Twitter
success = bot.send_tweet("🤖 Test del bot", "test", "test")
print("Twitter OK" if success else "Twitter ERROR")
```

### Forzar un tweet específico
```python
# Crear force_tweet.py
from bot import TwitterBot

bot = TwitterBot()

# Forzar resumen de septiembre 2025
success = bot.execute_scheduled_post(0, "2025-09")  # día 0 = resumen mensual
print("Tweet enviado:" if success else "Error")
```

### Reset completo
```bash
# Borrar logs para empezar de cero
rm twitter_bot_logs.db
python bot.py
```

## 🐛 Troubleshooting

### Error: "Twitter credentials not configured"
- Verifica que todas las 4 variables de entorno estén configuradas
- Revisa que no tengan espacios extra o caracteres especiales
- Verifica que las credenciales sean válidas en Twitter Developer Portal

### Error: "API request timeout"
- Verifica que `AVIADATA_API_URL` sea correcta
- Test manual: `curl https://aviadata-backend-production-8fa2.up.railway.app/vuelos/kpis`
- El bot tiene timeout de 120 segundos, si falla es problema del servidor

### Error: "Rate limit exceeded"
- Normal, el bot espera automáticamente
- Twitter permite ~300 tweets cada 15 minutos
- Con el cronograma (1 tweet cada 2-3 días) nunca debería pasar

### Bot no detecta nuevos meses
- Verifica que `/aeropuertos/rango-meses` retorne `mes_maximo`
- Check logs: "🆕 Nuevo mes detectado"
- Manualmente: `UPDATE bot_state SET value='2025-10' WHERE key='current_publishing_month';`

### Tweets duplicados
- El bot verifica automáticamente tweets existentes
- Si hay duplicados, verifica la BD: `SELECT * FROM tweets_log WHERE tipo_post='resumen_mensual';`

## 📈 Monitoreo de funcionamiento

### Logs importantes a monitorear:
```
✅ Bot de Twitter inicializado
✅ Scheduler del bot iniciado  
🆕 Nuevo mes detectado: 2025-10
📝 Ejecutando post: resumen_mensual para mes 2025-10
✅ Post resumen_mensual enviado exitosamente
```

### Logs de error a investigar:
```
❌ Error en API request: [timeout/connection]
❌ Error de Twitter: [rate limit/credentials]
❌ No se pudo generar contenido para [tipo_post]
```

## 🔄 Ciclo de funcionamiento

1. **Inicio**: Bot verifica credenciales y se conecta a APIs
2. **Scheduler**: Cada 3 horas verifica posts pendientes
3. **Nuevo mes**: Cada 6 horas verifica si hay datos nuevos
4. **Posts**: Ejecuta tweets según cronograma (día 0, 2, 4, etc.)
5. **Recovery**: Si falla un tweet, lo reintenta en la siguiente verificación
6. **Logs**: Todo se registra en SQLite para auditoría

## ⚡ Quick Start para desarrollo

```bash
# 1. Setup rápido
git clone <repo>
cd twitter-bot-standalone
pip install -r requirements.txt

# 2. Configurar credenciales
cp .env.example .env
# Edita .env con tus credenciales reales

# 3. Test rápido
python -c "from bot import TwitterBot; bot = TwitterBot(); print('Bot OK')"

# 4. Ejecutar
python bot.py
```

¡El bot está listo para usar! 🚀