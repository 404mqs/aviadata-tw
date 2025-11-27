# bot.py - Bot de Twitter para Aviadata (Standalone)
import os
import time
import json
import hashlib
import sqlite3
import logging
import requests
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from apscheduler.schedulers.background import BackgroundScheduler
import tweepy
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("twitter_bot")

# ================================
# CONFIGURACIÓN DEL BOT
# ================================

class TwitterBotConfig:
    """Configuración centralizada del bot de Twitter"""
    
    # Credenciales de Twitter (requeridas)
    TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
    TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
    TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
    TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
    TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
    
    # API de Aviadata (URL del backend)
    API_BASE_URL = os.getenv("AVIADATA_API_URL")
    
    # Base de datos de logs
    # Auto-detectar Railway: usar volumen /data si existe, sino directorio actual
    DATA_DIR = os.getenv("DATA_DIR")
    if DATA_DIR is None:
        # Si estamos en Railway con volumen montado en /data
        if os.path.exists("/data") and os.path.isdir("/data"):
            DATA_DIR = "/data"
            logger.info("🚂 Railway volume detectado: usando /data para persistencia")
        else:
            DATA_DIR = "."
    
    LOG_DB_PATH = os.path.join(DATA_DIR, "twitter_bot_logs.db")
    
    # Configuración del cronograma (días del mes)
    CRONOGRAMA_POSTS = {
        0: {"tipo": "resumen_mensual", "endpoint": "/vuelos/kpis", "descripcion": "Resumen mensual del mes nuevo"},
        2: {"tipo": "top_aerolineas", "endpoint": "/vuelos/aerolinea", "descripcion": "Top aerolíneas"},
        4: {"tipo": "rutas_transitadas", "endpoint": "/vuelos/rutas-enriquecidas", "descripcion": "Rutas más transitadas"},
        6: {"tipo": "aeropuertos_activos", "endpoint": "/vuelos/aeropuerto", "descripcion": "Aeropuertos más activos"},
        8: {"tipo": "destinos_internacionales", "endpoint": "/vuelos/paises", "descripcion": "Destinos internacionales"},
        10: {"tipo": "evolucion_historica", "endpoint": "/vuelos/mes", "descripcion": "Evolución histórica"},
        12: {"tipo": "ocupacion_promedio", "endpoint": "/vuelos/ocupacion", "descripcion": "Ocupación promedio"},
        14: {"tipo": "comparativa_aeropuertos", "endpoint": "/aeropuertos/evolucion-mensual", "descripcion": "Comparativa aeropuertos"},
        16: {"tipo": "records_curiosidades", "endpoint": "/vuelos/diario", "descripcion": "Día récords y curiosidades"},
        18: {"tipo": "aerolineas_inusuales", "endpoint": "/vuelos/detallados?es_inusual=true", "descripcion": "Aerolíneas inusuales"},
        20: {"tipo": "comparativa_mensual", "endpoint": "/vuelos/kpis", "descripcion": "Comparativa mensual con mes anterior"},
        22: {"tipo": "rutas_internacionales", "endpoint": "/vuelos/paises?flight_types=Internacional", "descripcion": "Top rutas internacionales"},
        24: {"tipo": "promedios_clase", "endpoint": "/vuelos/clase", "descripcion": "Promedios por clase de vuelo"},
        26: {"tipo": "recap_grafico", "endpoint": "multiple", "descripcion": "Recap gráfico mensual"}
    }
    
    @classmethod
    def validate_credentials(cls) -> bool:
        """Validar que todas las credenciales de Twitter están configuradas"""
        required_vars = [
            cls.TWITTER_API_KEY,
            cls.TWITTER_API_SECRET,
            cls.TWITTER_ACCESS_TOKEN,
            cls.TWITTER_ACCESS_SECRET,
            cls.TWITTER_BEARER_TOKEN
        ]
        return all(var is not None and var.strip() != "" for var in required_vars)

# ================================
# SISTEMA DE LOGS EN SQLITE
# ================================

class TwitterBotLogger:
    """Manejo de logs del bot en SQLite para persistencia"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Crear tabla de logs si no existe"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tweets_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date_posted TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        tweet_text TEXT NOT NULL,
                        status VARCHAR(20) NOT NULL,
                        tipo_post VARCHAR(50) NOT NULL,
                        mes_relacionado VARCHAR(7),
                        dia_cronograma INTEGER,
                        tweet_id VARCHAR(50),
                        error_message TEXT,
                        api_data TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS bot_state (
                        key VARCHAR(50) PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                conn.commit()
                logger.info("✅ Base de datos de logs inicializada")
                
        except Exception as e:
            logger.error(f"❌ Error inicializando base de datos de logs: {e}")
    
    def log_tweet(self, tweet_text: str, status: str, tipo_post: str, 
                   mes_relacionado: str = None, dia_cronograma: int = None,
                   tweet_id: str = None, error_message: str = None, 
                   api_data: str = None) -> bool:
        """Registrar un tweet en los logs"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO tweets_log 
                    (tweet_text, status, tipo_post, mes_relacionado, dia_cronograma, 
                     tweet_id, error_message, api_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (tweet_text, status, tipo_post, mes_relacionado, dia_cronograma,
                      tweet_id, error_message, api_data))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error guardando log de tweet: {e}")
            return False
    
    def check_post_exists(self, tipo_post: str, mes_relacionado: str, dia_cronograma: int) -> bool:
        """Verificar si un post ya existe"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM tweets_log 
                    WHERE tipo_post = ? AND mes_relacionado = ? AND dia_cronograma = ?
                    AND status = 'success'
                """, (tipo_post, mes_relacionado, dia_cronograma))
                
                count = cursor.fetchone()[0]
                return count > 0
        except Exception as e:
            logger.error(f"Error verificando existencia de post: {e}")
            return False
    
    def get_bot_state(self, key: str) -> Optional[str]:
        """Obtener valor del estado del bot"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM bot_state WHERE key = ?", (key,))
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Error obteniendo estado del bot: {e}")
            return None
    
    def set_bot_state(self, key: str, value: str) -> bool:
        """Establecer valor del estado del bot"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO bot_state (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, (key, value))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error estableciendo estado del bot: {e}")
            return False

# ================================
# CLIENTE API AVIADATA
# ================================

class AviationAPIClient:
    """Cliente para interactuar con la API de Aviadata"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
    
    def make_request(self, endpoint: str, params: dict = None) -> Optional[Dict[Any, Any]]:
        """Hacer request a la API con manejo de errores"""
        try:
            url = f"{self.base_url}{endpoint}"
            logger.info(f"🌐 Consultando API: {url}")
            
            # Convertir listas a parámetros múltiples para FastAPI
            if params:
                processed_params = []
                for key, value in params.items():
                    if isinstance(value, list):
                        # Para listas, agregar múltiples pares clave-valor
                        for item in value:
                            processed_params.append((key, item))
                    else:
                        processed_params.append((key, value))
                logger.info(f"📋 Parámetros: {processed_params}")
            else:
                processed_params = None
            
            response = requests.get(url, params=processed_params, timeout=120)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error en API request: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error decodificando JSON: {e}")
            return None
    
    def get_latest_month(self) -> Optional[str]:
        """Obtener el mes más reciente disponible en la API"""
        try:
            data = self.make_request("/aeropuertos/rango-meses")
            if data and "mes_maximo" in data:
                return data["mes_maximo"]
            return None
        except Exception as e:
            logger.error(f"Error obteniendo mes más reciente: {e}")
            return None

# ================================
# GENERADOR DE CONTENIDO PARA TWEETS
# ================================

class TwitterContentGenerator:
    """Clase para generar contenido específico de cada tipo de tweet"""
    
    @staticmethod
    def format_month_name(mes_str: str) -> str:
        """Convertir '2025-09' a 'Septiembre 2025'"""
        try:
            año, mes_num = mes_str.split('-')
            meses = [
                "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
            ]
            mes_nombre = meses[int(mes_num) - 1]
            return f"{mes_nombre} {año}"
        except:
            return mes_str
    
    @staticmethod
    def generar_resumen_mensual(data: dict, mes: str) -> Optional[str]:
        """Generar tweet de resumen mensual usando endpoint /vuelos/kpis"""
        if not data:
            return None
        
        mes_formateado = TwitterContentGenerator.format_month_name(mes)
        
        # Usar hashlib para generar variación basada en el mes
        seed = int(hashlib.md5(mes.encode()).hexdigest()[:8], 16) % 4
        
        intros = [
            f"📊 ¡{mes_formateado} cerró con estos números!",
            f"🚀 Resumen de {mes_formateado} - ¡Qué mes!",
            f"✈️ Los números de {mes_formateado} que tienes que conocer:",
            f"📈 {mes_formateado}: Un mes lleno de vuelos"
        ]
        
        intro = intros[seed]
        
        vuelos_total = data.get("total_vuelos", 0)
        pax_total = data.get("total_pasajeros", 0)
        ocupacion = data.get("ocupacion_promedio", 0)
        
        tweet = f"""{intro}

✈️ Vuelos: {vuelos_total:,}
👥 Pasajeros: {pax_total:,}
📊 Ocupación: {ocupacion:.1f}%

aviadata.ar
#AviacionArgentina #{mes_formateado.replace(' ', '')}"""
        
        return tweet[:280]
    
    @staticmethod
    def generar_top_aerolineas(data: list, mes: str) -> Optional[str]:
        """Generar tweet de top aerolíneas"""
        mes_formateado = TwitterContentGenerator.format_month_name(mes)
        
        if not data or len(data) == 0:
            return None
        
        # Tomar las top 3 aerolíneas
        top_3 = data[:3]
        
        tweet = f"🏆 Top Aerolíneas {mes_formateado}\n¿Cuál es tu favorita?\n\n"
        
        emojis = ["🥇", "🥈", "🥉"]
        for i, airline in enumerate(top_3):
            nombre = airline.get("Aerolinea Nombre", "Desconocida")[:15]
            vuelos = airline.get("total_vuelos", 0)
            
            tweet += f"{emojis[i]} {nombre}: {vuelos:,} vuelos\n"
        
        tweet += f"\naviadata.ar\n#Aerolineas #{mes_formateado.replace(' ', '')}"
        
        return tweet[:280]
    
    @staticmethod
    def generar_ocupacion_promedio(data: list, mes: str) -> Optional[str]:
        """Generar tweet de ocupación promedio usando endpoint /vuelos/ocupacion"""
        mes_formateado = TwitterContentGenerator.format_month_name(mes)

        if not data or len(data) == 0:
            return None

        # Tomar las top 3 aerolíneas por ocupación
        top_3 = sorted(data, key=lambda x: x.get("ocupacion_porcentaje", 0), reverse=True)[:3]

        tweet = f"📈 Ocupación Promedio {mes_formateado}\nTop aerolíneas:\n\n"

        for i, airline_data in enumerate(top_3, 1):
            nombre = airline_data.get("Aerolinea Nombre", "Desconocida")[:20]
            ocupacion = airline_data.get("ocupacion_porcentaje", 0)

            emoji = ["🥇", "🥈", "🥉"][i-1]
            tweet += f"{emoji} {nombre}: {ocupacion:.1f}%\n"

        tweet += f"\naviadata.ar\n#Ocupacion #{mes_formateado.replace(' ', '')}"

        return tweet[:280]
    
    @staticmethod
    def generar_evolucion_historica(data: list, mes: str) -> Optional[str]:
        """Generar tweet de evolución histórica"""
        if not data or len(data) < 2:
            return None
        
        # Ordenar por fecha y tomar los últimos 4 meses
        sorted_data = sorted(data, key=lambda x: x.get("Mes", ""))[-4:]
        
        tweet = "📈 Evolución histórica de vuelos:\n\n"
        
        for mes_data in sorted_data:
            mes_raw = mes_data.get("Mes", "")
            vuelos = mes_data.get("Cantidad", 0)
            
            # Convertir 2025-09 a Sep 25
            try:
                año, mes_num = mes_raw.split('-')
                meses_cortos = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                               "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
                mes_corto = meses_cortos[int(mes_num) - 1]
                fecha_legible = f"{mes_corto} {año[-2:]}"
            except:
                fecha_legible = mes_raw
                
            tweet += f"{fecha_legible}: {vuelos:,} vuelos\n"
        
        # Calcular tendencia
        if len(sorted_data) >= 2:
            ultimo = sorted_data[-1].get("Cantidad", 0)
            anterior = sorted_data[-2].get("Cantidad", 0)
            
            if anterior > 0:
                cambio = ((ultimo - anterior) / anterior) * 100
                if cambio > 0:
                    tweet += f"\n📊 Crecimiento del {cambio:.1f}%"
                else:
                    tweet += f"\n📊 Variación del {cambio:.1f}%"
        
        tweet += "\n\naviadata.ar\n#Aviación #Estadísticas"
        
        return tweet[:280]
    
    @staticmethod
    def generar_destinos_internacionales(data: list, mes: str) -> Optional[str]:
        """Generar tweet de destinos internacionales"""
        mes_formateado = TwitterContentGenerator.format_month_name(mes)
        
        if not data or len(data) == 0:
            return None
        
        # Tomar los top 3 países
        top_3 = data[:3]
        
        tweet = f"🌍 ¿A dónde volamos en {mes_formateado}?\nTop destinos internacionales:\n\n"
        
        flags = ["🥇", "🥈", "🥉"]
        for i, destino in enumerate(top_3):
            pais = destino.get("Pais Destino Nombre", "Desconocido")[:15]
            vuelos = destino.get("total_vuelos", 0)
            
            tweet += f"{flags[i]} {pais}: {vuelos:,} vuelos\n"
        
        tweet += f"\naviadata.ar\n#DestinosInternacionales #{mes_formateado.replace(' ', '')}"
        
        return tweet[:280]

# ================================
# BOT DE TWITTER PRINCIPAL
# ================================

class TwitterBot:
    """Bot principal de Twitter para Aviadata"""
    
    def __init__(self):
        self.config = TwitterBotConfig()
        self.logger = TwitterBotLogger(self.config.LOG_DB_PATH)
        self.api_client = AviationAPIClient(self.config.API_BASE_URL)
        self.content_generator = TwitterContentGenerator()
        self.scheduler = BackgroundScheduler()
        self.twitter_api = self._setup_twitter_api()
        
        logger.info("🤖 Bot de Twitter inicializado")
    
    def _setup_twitter_api(self) -> Optional[tweepy.Client]:
        """Configurar la API de Twitter v2"""
        try:
            # Usar API v2 con Client
            client = tweepy.Client(
                bearer_token=self.config.TWITTER_BEARER_TOKEN,
                consumer_key=self.config.TWITTER_API_KEY,
                consumer_secret=self.config.TWITTER_API_SECRET,
                access_token=self.config.TWITTER_ACCESS_TOKEN,
                access_token_secret=self.config.TWITTER_ACCESS_SECRET,
                wait_on_rate_limit=True
            )
            
            # Verificar credenciales obteniendo información del usuario autenticado
            me = client.get_me()
            if me and me.data:
                logger.info(f"✅ API de Twitter v2 configurada correctamente - Usuario: @{me.data.username}")
            else:
                logger.info("✅ API de Twitter v2 configurada correctamente")
            return client
            
        except Exception as e:
            logger.error(f"❌ Error configurando API de Twitter v2: {e}")
            return None
    
    def send_tweet(self, text: str, tipo_post: str, mes_relacionado: str = None, 
                   dia_cronograma: int = None) -> bool:
        """Enviar un tweet usando API v2"""
        try:
            if not self.twitter_api:
                logger.error("❌ API de Twitter no configurada")
                return False
            
            # Truncar si es muy largo
            if len(text) > 280:
                text = text[:277] + "..."
            
            logger.info(f"🐦 Enviando tweet: {text[:50]}...")
            
            # Enviar tweet usando API v2
            response = self.twitter_api.create_tweet(text=text)
            
            if response and response.data:
                tweet_id = str(response.data['id'])
                
                # Log exitoso
                self.logger.log_tweet(
                    tweet_text=text,
                    status="success",
                    tipo_post=tipo_post,
                    mes_relacionado=mes_relacionado,
                    dia_cronograma=dia_cronograma,
                    tweet_id=tweet_id
                )
                
                logger.info(f"✅ Tweet enviado exitosamente: ID {tweet_id}")
                return True
            else:
                logger.error("❌ No se recibió respuesta válida de Twitter")
                return False
            
        except tweepy.TweepyException as e:
            error_msg = str(e)
            logger.error(f"❌ Error de Twitter: {error_msg}")
            
            # Log del error
            self.logger.log_tweet(
                tweet_text=text,
                status="error",
                tipo_post=tipo_post,
                mes_relacionado=mes_relacionado,
                dia_cronograma=dia_cronograma,
                error_message=error_msg
            )
            
            return False
        except Exception as e:
            logger.error(f"❌ Error enviando tweet: {e}")
            return False
    
    def generate_content_for_post_type(self, tipo_post: str, mes: str) -> Optional[str]:
        """Generar contenido específico para cada tipo de post"""
        try:
            months_filter = [mes]  # Filtrar por el mes específico
            
            if tipo_post == "resumen_mensual":
                data = self.api_client.make_request("/vuelos/kpis", 
                                                  {"months": months_filter, "all_periods": False})
                return self.content_generator.generar_resumen_mensual(data, mes)
            
            elif tipo_post == "top_aerolineas":
                data = self.api_client.make_request("/vuelos/aerolinea", 
                                                  {"months": months_filter, "all_periods": False, "limit": 10})
                return self.content_generator.generar_top_aerolineas(data, mes)
            
            elif tipo_post == "destinos_internacionales":
                data = self.api_client.make_request("/vuelos/paises", 
                                                  {"months": months_filter, "all_periods": False, "tipo_pais": "destino"})
                return self.content_generator.generar_destinos_internacionales(data, mes)
            
            elif tipo_post == "ocupacion_promedio":
                data = self.api_client.make_request("/vuelos/ocupacion",
                                                  {"months": months_filter, "all_periods": False})
                return self.content_generator.generar_ocupacion_promedio(data, mes)
            
            elif tipo_post == "evolucion_historica":
                data = self.api_client.make_request("/vuelos/mes")
                return self.content_generator.generar_evolucion_historica(data, mes)
            
            else:
                logger.warning(f"⚠️ Tipo de post no implementado: {tipo_post}")
                return None
                
        except Exception as e:
            logger.error(f"Error generando contenido para {tipo_post}: {e}")
            return None
    
    def execute_scheduled_post(self, dia_cronograma: int, mes: str) -> bool:
        """Ejecutar un post programado específico"""
        try:
            # Obtener configuración del post
            post_config = self.config.CRONOGRAMA_POSTS.get(dia_cronograma)
            if not post_config:
                logger.error(f"❌ No hay configuración para día {dia_cronograma}")
                return False
            
            tipo_post = post_config["tipo"]
            
            # Verificar si ya existe
            if self.logger.check_post_exists(tipo_post, mes, dia_cronograma):
                logger.info(f"⏭️ Post {tipo_post} para {mes} día {dia_cronograma} ya existe")
                return True
            
            logger.info(f"📝 Ejecutando post: {tipo_post} para mes {mes}")
            
            # Generar contenido
            tweet_text = self.generate_content_for_post_type(tipo_post, mes)
            
            if tweet_text:
                # Enviar tweet
                success = self.send_tweet(
                    text=tweet_text,
                    tipo_post=tipo_post,
                    mes_relacionado=mes,
                    dia_cronograma=dia_cronograma
                )

                if success:
                    logger.info(f"✅ Post {tipo_post} enviado exitosamente")
                    return True
                else:
                    logger.error(f"❌ Error enviando post {tipo_post}")
                    return False
            else:
                logger.error(f"❌ No se pudo generar contenido para {tipo_post}")
                return False

        except Exception as e:
            logger.error(f"Error ejecutando post programado: {e}")
            return False
    
    def verificar_posts_pendientes(self):
        """Verificar y enviar posts pendientes según el cronograma"""
        try:
            # Obtener mes actual de publicación
            mes_actual = self.logger.get_bot_state("current_publishing_month")
            if not mes_actual:
                logger.info("📅 No hay mes de publicación activo")
                return
            
            # Obtener día actual del mes
            dia_actual = datetime.now().day
            logger.info(f"🗓️ Verificando posts para {mes_actual}, día {dia_actual}")
            
            posts_enviados = 0
            posts_ya_publicados = 0
            
            # Revisar todos los días del cronograma hasta el día actual
            for dia_cronograma, post_config in self.config.CRONOGRAMA_POSTS.items():
                if dia_cronograma <= dia_actual:
                    tipo_post = post_config["tipo"]
                    
                    # Verificar si ya existe
                    if not self.logger.check_post_exists(tipo_post, mes_actual, dia_cronograma):
                        # Ejecutar post pendiente
                        success = self.execute_scheduled_post(dia_cronograma, mes_actual)
                        if success:
                            posts_enviados += 1
                    else:
                        posts_ya_publicados += 1
            
            logger.info(f"✅ Verificación completa: {posts_enviados} tweets enviados, {posts_ya_publicados} ya publicados")
            
        except Exception as e:
            logger.error(f"Error verificando posts pendientes: {e}")
    
    def verificar_nuevo_mes(self):
        """Verificar si hay un nuevo mes disponible en la API"""
        try:
            # Obtener mes más reciente de la API
            mes_mas_reciente = self.api_client.get_latest_month()
            if not mes_mas_reciente:
                logger.warning("No se pudo obtener el mes más reciente de la API")
                return
            
            # Obtener mes actual de publicación del bot
            mes_actual = self.logger.get_bot_state("current_publishing_month")
            
            if mes_actual != mes_mas_reciente:
                logger.info(f"🆕 Nuevo mes detectado: {mes_mas_reciente} (anterior: {mes_actual})")
                
                # Actualizar mes de publicación
                self.logger.set_bot_state("current_publishing_month", mes_mas_reciente)
                
                # Ejecutar inmediatamente el post del día 0 (resumen mensual)
                self.execute_scheduled_post(0, mes_mas_reciente)
            
        except Exception as e:
            logger.error(f"Error verificando nuevo mes: {e}")
    
    def start_scheduler(self):
        """Iniciar el scheduler del bot"""
        try:
            # Verificar posts pendientes cada 3 horas
            self.scheduler.add_job(
                self.verificar_posts_pendientes,
                'interval',
                hours=3,
                id='verificar_posts'
            )
            
            # Verificar nuevo mes cada 6 horas
            self.scheduler.add_job(
                self.verificar_nuevo_mes,
                'interval',
                hours=6,
                id='verificar_nuevo_mes'
            )
            
            self.scheduler.start()
            logger.info("✅ Scheduler del bot iniciado")
            logger.info("📅 Verificación de posts pendientes: Cada 3 horas")
            logger.info("🆕 Verificación de nuevo mes: Cada 6 horas")
            
            # Ejecutar verificación inicial
            self.verificar_nuevo_mes()
            
        except Exception as e:
            logger.error(f"Error iniciando scheduler: {e}")
    
    def stop_scheduler(self):
        """Detener el scheduler del bot"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown()
                logger.info("🛑 Scheduler detenido")
        except Exception as e:
            logger.error(f"Error deteniendo scheduler: {e}")

# ================================
# FUNCIÓN PRINCIPAL
# ================================

def main():
    """Función principal para ejecutar el bot standalone"""
    logger.info("🚀 Iniciando Bot de Twitter de Aviadata...")
    
    # Validar credenciales
    if not TwitterBotConfig.validate_credentials():
        logger.error("❌ Credenciales de Twitter no configuradas")
        logger.info("Configura las siguientes variables de entorno:")
        logger.info("- TWITTER_API_KEY")
        logger.info("- TWITTER_API_SECRET")
        logger.info("- TWITTER_ACCESS_TOKEN")
        logger.info("- TWITTER_ACCESS_SECRET")
        logger.info("- TWITTER_BEARER_TOKEN")
        logger.info("- AVIADATA_API_URL")
        return
    
    # Crear instancia del bot
    bot = TwitterBot()
    
    try:
        # Iniciar scheduler
        bot.start_scheduler()
        
        logger.info("✅ Bot iniciado exitosamente. Presiona Ctrl+C para detener.")
        
        # Mantener el programa en ejecución
        while True:
            time.sleep(60)
            
    except KeyboardInterrupt:
        logger.info("⚠️ Interrupción detectada. Deteniendo bot...")
        bot.stop_scheduler()
        logger.info("👋 Bot detenido exitosamente")
    except Exception as e:
        logger.error(f"❌ Error en ejecución del bot: {e}")
        bot.stop_scheduler()

if __name__ == "__main__":
    main()