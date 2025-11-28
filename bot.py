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
from flask import Flask, jsonify, request

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
        4: {"tipo": "rutas_transitadas", "endpoint": "/vuelos/rutas", "descripcion": "Rutas más transitadas"},
        6: {"tipo": "aeropuertos_activos", "endpoint": "/vuelos/aeropuerto", "descripcion": "Aeropuertos más activos"},
        8: {"tipo": "destinos_internacionales", "endpoint": "/vuelos/paises", "descripcion": "Destinos internacionales"},
        10: {"tipo": "evolucion_historica", "endpoint": "/vuelos/mes", "descripcion": "Evolución histórica"},
        12: {"tipo": "ocupacion_promedio", "endpoint": "/vuelos/ocupacion", "descripcion": "Ocupación promedio"},
        14: {"tipo": "comparativa_aeropuertos", "endpoint": "/aeropuertos/evolucion-mensual", "descripcion": "Comparativa aeropuertos"},
        16: {"tipo": "records_curiosidades", "endpoint": "/vuelos/diario", "descripcion": "Día récords y curiosidades"},
        18: {"tipo": "aerolineas_inusuales", "endpoint": "/vuelos/detallados?es_inusual=true", "descripcion": "Aerolíneas inusuales"},
        20: {"tipo": "comparativa_mensual", "endpoint": "/vuelos/kpis", "descripcion": "Comparativa mensual con mes anterior"},
        22: {"tipo": "historial_vuelos_mes", "endpoint": "/vuelos/mes", "descripcion": "Historial de vuelos por mes"},
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
        
        # Log de muestra para diagnóstico (primeros 3 elementos)
        try:
            logger.info(f"🔎 Muestra API aerolinea: {json.dumps(data[:3])}")
        except Exception:
            pass
        
        # Normalizar campos posibles y filtrar resultados con 0 vuelos
        def parse_item(item: dict):
            nombre = (
                item.get("Aerolinea Nombre")
                or item.get("aerolinea")
                or item.get("nombre")
                or item.get("Aerolinea")
                or "Desconocida"
            )
            vuelos = (
                item.get("total_vuelos")
                or item.get("Cantidad")
                or item.get("vuelos")
                or 0
            )
            return nombre, vuelos

        parsed = [parse_item(x) for x in data]
        parsed = [(n, v) for (n, v) in parsed if isinstance(v, (int, float)) and v > 0]
        
        if not parsed:
            logger.warning("⚠️ API aerolinea devolvió todos ceros o formato desconocido")
            return None
        
        # Top 3 por cantidad
        top_3 = sorted(parsed, key=lambda x: x[1], reverse=True)[:3]
        
        tweet = f"🏆 Top Aerolíneas {mes_formateado}\n¿Cuál es tu favorita?\n\n"
        
        emojis = ["🥇", "🥈", "🥉"]
        for i, (nombre, vuelos) in enumerate(top_3):
            nombre = str(nombre)[:20]
            tweet += f"{emojis[i]} {nombre}: {int(vuelos):,} vuelos\n"
        
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
    def generar_historial_vuelos_mes(data: list, mes: str) -> Optional[str]:
        """Historial compacto de vuelos por mes usando /vuelos/mes"""
        if not data or len(data) == 0:
            return None
        # Ordenar y tomar los últimos 8 meses para caber en 280
        sorted_data = sorted(data, key=lambda x: x.get("Mes", ""))[-8:]
        lines = []
        for mes_data in sorted_data:
            mes_raw = mes_data.get("Mes", "")
            vuelos = mes_data.get("Cantidad", 0)
            try:
                año, mes_num = mes_raw.split('-')
                meses_cortos = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                                "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
                mes_corto = meses_cortos[int(mes_num) - 1]
                label = f"{mes_corto} {año[-2:]}"
            except:
                label = mes_raw
            lines.append(f"{label}: {vuelos:,}")

        tweet_head = "🗓️ Historial de vuelos por mes\n\n"
        tweet_body = "\n".join(lines)
        tweet_tail = "\n\naviadata.ar\n#Historial #Vuelos"
        tweet = tweet_head + tweet_body + tweet_tail
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

    @staticmethod
    def generar_rutas_transitadas(data: list, mes: str) -> Optional[str]:
        """Generar tweet de rutas más transitadas usando endpoint /vuelos/rutas-enriquecidas"""
        mes_formateado = TwitterContentGenerator.format_month_name(mes)
        if not data or len(data) == 0:
            return None
        
        # Log de muestra para diagnóstico
        try:
            logger.info(f"🔎 Muestra API rutas: {json.dumps(data[:3])}")
        except Exception:
            pass
        
        # Formato actual: { "Ruta": "SABE-SACO", "Cantidad": 34970 }
        rutas = []
        for item in data:
            ruta = item.get("Ruta") or item.get("ruta")
            vuelos = item.get("Cantidad") or item.get("total_vuelos") or item.get("vuelos") or 0
            if ruta and isinstance(vuelos, (int, float)) and vuelos > 0:
                try:
                    origen, destino = str(ruta).split("-")
                except ValueError:
                    # Si no se puede dividir, usar la ruta completa como etiqueta
                    origen, destino = str(ruta), ""
                rutas.append((origen, destino, int(vuelos)))
        
        if not rutas:
            return None
        
        top = sorted(rutas, key=lambda x: x[2], reverse=True)[:3]
        tweet = f"🛣️ Rutas más transitadas {mes_formateado}\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (o, d, v) in enumerate(top):
            tweet += f"{medals[i]} {o} → {d}: {v:,} vuelos\n"
        tweet += f"\naviadata.ar\n#Rutas #{mes_formateado.replace(' ', '')}"
        return tweet[:280]

    @staticmethod
    def generar_aeropuertos_activos(data: list, mes: str) -> Optional[str]:
        """Generar tweet de aeropuertos más activos usando /vuelos/aeropuerto"""
        mes_formateado = TwitterContentGenerator.format_month_name(mes)
        if not data or len(data) == 0:
            return None

        # Formato: { "Aeropuerto": "SABE", "Cantidad": 11314 }
        try:
            logger.info(f"🔎 Muestra API aeropuerto: {json.dumps(data[:3])}")
        except Exception:
            pass

        parsed = []
        for item in data:
            code = item.get("Aeropuerto") or item.get("Codigo") or item.get("code")
            count = item.get("Cantidad") or item.get("total_vuelos") or item.get("vuelos") or 0
            if code and isinstance(count, (int, float)) and count > 0:
                parsed.append((str(code), int(count)))

        if not parsed:
            return None

        top = sorted(parsed, key=lambda x: x[1], reverse=True)[:3]
        tweet = f"🛫 Aeropuertos más activos {mes_formateado}\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (code, cnt) in enumerate(top):
            tweet += f"{medals[i]} {code}: {cnt:,} vuelos\n"
        tweet += f"\naviadata.ar\n#Aeropuertos #{mes_formateado.replace(' ', '')}"
        return tweet[:280]

    @staticmethod
    def _get_prev_month(mes: str) -> Optional[str]:
        try:
            dt = datetime.strptime(mes + "-01", "%Y-%m-%d")
            prev = dt - timedelta(days=1)
            return prev.strftime("%Y-%m")
        except Exception:
            return None

    @staticmethod
    def generar_comparativa_aeropuertos(actual: list, anterior: list, mes: str) -> Optional[str]:
        """Comparar actividad de aeropuertos vs mes anterior usando /vuelos/aeropuerto"""
        mes_act = TwitterContentGenerator.format_month_name(mes)
        prev_mes = TwitterContentGenerator._get_prev_month(mes)
        if not actual or not anterior or not prev_mes:
            return None

        map_act = {str(x.get("Aeropuerto") or x.get("Codigo") or ""): int(x.get("Cantidad") or 0) for x in actual}
        map_prev = {str(x.get("Aeropuerto") or x.get("Codigo") or ""): int(x.get("Cantidad") or 0) for x in anterior}

        # Calcular variación para aeropuertos presentes en actual
        comps = []
        for code, cnt in map_act.items():
            prev = map_prev.get(code, 0)
            if prev > 0:
                change = ((cnt - prev) / prev) * 100.0
                comps.append((code, cnt, change))
        if not comps:
            return None

        top = sorted(comps, key=lambda x: x[2], reverse=True)[:3]
        tweet = f"🏟️ Aeropuertos: variación vs {TwitterContentGenerator.format_month_name(prev_mes)}\n{mes_act}\n\n"
        for code, cnt, ch in top:
            sign = "⬆️" if ch >= 0 else "⬇️"
            tweet += f"{sign} {code}: {cnt:,} vuelos ({ch:.1f}%)\n"
        tweet += f"\naviadata.ar\n#Comparativa #{mes_act.replace(' ', '')}"
        return tweet[:280]

    @staticmethod
    def generar_records_curiosidades(vuelos_diario: list, pax_diario: list, mes: str) -> Optional[str]:
        """Encontrar récord diario de vuelos y pasajeros"""
        mes_formateado = TwitterContentGenerator.format_month_name(mes)
        if not vuelos_diario and not pax_diario:
            return None

        def best_day(items, key_name):
            if not items:
                return None
            try:
                top = max(items, key=lambda x: int(x.get(key_name) or 0))
                fecha = top.get("Fecha") or top.get("fecha") or ""
                valor = int(top.get(key_name) or 0)
                return fecha, valor
            except Exception:
                return None

        vuelos_top = best_day(vuelos_diario, "Cantidad")
        pax_top = best_day(pax_diario, "Cantidad")

        if not vuelos_top and not pax_top:
            return None

        tweet = f"🧠 Récords y curiosidades {mes_formateado}\n\n"
        if vuelos_top:
            fecha, v = vuelos_top
            tweet += f"✈️ Día con más vuelos: {fecha} ({v:,})\n"
        if pax_top:
            fecha, p = pax_top
            tweet += f"👥 Día con más pasajeros: {fecha} ({p:,})\n"
        tweet += "\naviadata.ar\n#Curiosidades #Records"
        return tweet[:280]

    @staticmethod
    def generar_aerolineas_inusuales(aerolineas_mes: list, mes: str) -> Optional[str]:
        """Detectar aerolíneas con participación muy baja como 'inusuales'"""
        mes_formateado = TwitterContentGenerator.format_month_name(mes)
        if not aerolineas_mes:
            return None

        total = sum(int(x.get("Cantidad") or x.get("total_vuelos") or 0) for x in aerolineas_mes)
        if total <= 0:
            return None

        parts = []
        for x in aerolineas_mes:
            nombre = x.get("Aerolinea Nombre") or x.get("nombre") or x.get("Aerolinea") or "Desconocida"
            cnt = int(x.get("Cantidad") or x.get("total_vuelos") or 0)
            share = (cnt / total) * 100.0
            parts.append((str(nombre)[:20], cnt, share))

        # Ordenar por menor participación y tomar 3 con >0
        candidates = [p for p in parts if p[1] > 0]
        if not candidates:
            return None
        top = sorted(candidates, key=lambda x: x[2])[:3]

        tweet = f"🧐 Aerolíneas inusuales {mes_formateado}\n(Participación muy baja)\n\n"
        for nombre, cnt, share in top:
            tweet += f"• {nombre}: {cnt:,} vuelos ({share:.2f}%)\n"
        tweet += f"\naviadata.ar\n#Aerolíneas #Inusual"
        return tweet[:280]

    @staticmethod
    def generar_comparativa_mensual(kpis_actual: dict, kpis_anterior: dict, mes: str) -> Optional[str]:
        """Comparar KPIs vs mes anterior usando /vuelos/kpis"""
        mes_act = TwitterContentGenerator.format_month_name(mes)
        prev_mes = TwitterContentGenerator._get_prev_month(mes)
        if not kpis_actual or not kpis_anterior or not prev_mes:
            return None

        def fmt_change(a, b):
            try:
                return ((a - b) / b) * 100.0 if b else 0.0
            except Exception:
                return 0.0

        v_act = kpis_actual.get("total_vuelos", 0)
        v_prev = kpis_anterior.get("total_vuelos", 0)
        p_act = kpis_actual.get("total_pasajeros", 0)
        p_prev = kpis_anterior.get("total_pasajeros", 0)
        o_act = kpis_actual.get("ocupacion_promedio", 0.0)
        o_prev = kpis_anterior.get("ocupacion_promedio", 0.0)

        tweet = f"🔄 Comparativa mensual ({mes_act} vs {TwitterContentGenerator.format_month_name(prev_mes)})\n\n"
        tweet += f"✈️ Vuelos: {v_act:,} ({fmt_change(v_act, v_prev):.1f}%)\n"
        tweet += f"👥 Pasajeros: {p_act:,} ({fmt_change(p_act, p_prev):.1f}%)\n"
        tweet += f"📊 Ocupación: {o_act:.1f}% ({fmt_change(o_act, o_prev):.1f}%)\n"
        tweet += "\naviadata.ar\n#Comparativa #Mensual"
        return tweet[:280]

    @staticmethod
    def generar_rutas_internacionales(data: list, mes: str) -> Optional[str]:
        """Top rutas internacionales usando /vuelos/rutas"""
        mes_formateado = TwitterContentGenerator.format_month_name(mes)
        if not data:
            return None
        try:
            logger.info(f"🔎 Muestra API rutas internacionales: {json.dumps(data[:3])}")
        except Exception:
            pass

        rutas = []
        for item in data:
            ruta = item.get("Ruta") or item.get("ruta")
            vuelos = item.get("Cantidad") or item.get("total_vuelos") or item.get("vuelos") or 0
            if ruta and isinstance(vuelos, (int, float)) and vuelos > 0:
                try:
                    origen, destino = str(ruta).split("-")
                except ValueError:
                    origen, destino = str(ruta), ""
                rutas.append((origen, destino, int(vuelos)))

        if not rutas:
            return None

        top = sorted(rutas, key=lambda x: x[2], reverse=True)[:3]
        tweet = f"🌍 Rutas internacionales más transitadas {mes_formateado}\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (o, d, v) in enumerate(top):
            tweet += f"{medals[i]} {o} → {d}: {v:,} vuelos\n"
        tweet += f"\naviadata.ar\n#RutasInternacionales #{mes_formateado.replace(' ', '')}"
        return tweet[:280]

    @staticmethod
    def generar_promedios_clase(data: list, mes: str) -> Optional[str]:
        """Promedios por clase usando /vuelos/clase"""
        mes_formateado = TwitterContentGenerator.format_month_name(mes)
        if not data:
            return None
        try:
            logger.info(f"🔎 Muestra API clase: {json.dumps(data[:3])}")
        except Exception:
            pass

        parsed = []
        for x in data:
            nombre = x.get("Clase Nombre") or x.get("clase") or x.get("Clase") or "Desconocida"
            cnt = x.get("Cantidad") or x.get("total_vuelos") or 0
            if isinstance(cnt, (int, float)) and cnt > 0:
                parsed.append((str(nombre)[:18], int(cnt)))
        if not parsed:
            return None

        top = sorted(parsed, key=lambda x: x[1], reverse=True)[:3]
        tweet = f"🧭 Clases más usadas {mes_formateado}\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (n, c) in enumerate(top):
            tweet += f"{medals[i]} {n}: {c:,} vuelos\n"
        tweet += f"\naviadata.ar\n#Clases #{mes_formateado.replace(' ', '')}"
        return tweet[:280]

    @staticmethod
    def generar_recap_grafico(kpis: dict, aerolineas: list, aeropuertos: list, mes: str) -> Optional[str]:
        """Recap textual del mes: KPIs + top categorías"""
        mes_formateado = TwitterContentGenerator.format_month_name(mes)
        if not kpis:
            return None

        v = kpis.get("total_vuelos", 0)
        p = kpis.get("total_pasajeros", 0)
        o = kpis.get("ocupacion_promedio", 0.0)

        def top_names(items, key_name):
            if not items:
                return []
            parsed = []
            for x in items:
                nombre = x.get(key_name) or x.get("nombre") or "-"
                cnt = x.get("Cantidad") or x.get("total_vuelos") or 0
                if isinstance(cnt, (int, float)) and cnt > 0:
                    parsed.append((str(nombre)[:18], int(cnt)))
            return [n for n, _ in sorted(parsed, key=lambda y: y[1], reverse=True)[:3]]

        top_aero = top_names(aerolineas, "Aerolinea Nombre")
        top_airp = top_names(aeropuertos, "Aeropuerto")

        tweet = f"🧾 Recap {mes_formateado}\n✈️ {v:,} vuelos | 👥 {p:,} pax | 📊 {o:.1f}% ocupación\n"
        if top_aero:
            tweet += f"🏆 Aerolíneas top: {', '.join(top_aero)}\n"
        if top_airp:
            tweet += f"🛫 Aeropuertos top: {', '.join(top_airp)}\n"
        tweet += "\naviadata.ar\n#Resumen #Aviación"
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
        self.app = None
        
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
            
            # Mapa centralizado de endpoints y generadores
            generators = {
                "resumen_mensual": ("/vuelos/kpis", self.content_generator.generar_resumen_mensual, {"months": months_filter, "all_periods": False}),
                "top_aerolineas": ("/vuelos/aerolinea", self.content_generator.generar_top_aerolineas, {"months": months_filter, "all_periods": False, "limit": 10}),
                "rutas_transitadas": ("/vuelos/rutas", self.content_generator.generar_rutas_transitadas, {"months": months_filter, "all_periods": False, "limit": 25}),
                "aeropuertos_activos": ("/vuelos/aeropuerto", self.content_generator.generar_aeropuertos_activos, {"months": months_filter, "all_periods": False, "limit": 25}),
                "destinos_internacionales": ("/vuelos/paises", self.content_generator.generar_destinos_internacionales, {"months": months_filter, "all_periods": False, "tipo_pais": "destino"}),
                "ocupacion_promedio": ("/vuelos/ocupacion", self.content_generator.generar_ocupacion_promedio, {"months": months_filter, "all_periods": False}),
                "evolucion_historica": ("/vuelos/mes", self.content_generator.generar_evolucion_historica, {}),
                # comp. aeropuertos: necesitamos datos de mes actual y anterior
                "comparativa_aeropuertos": (None, None, {}),
                "records_curiosidades": (None, None, {}),
                "aerolineas_inusuales": (None, None, {}),
                "comparativa_mensual": (None, None, {}),
                "historial_vuelos_mes": ("/vuelos/mes", self.content_generator.generar_historial_vuelos_mes, {}),
                "promedios_clase": ("/vuelos/clase", self.content_generator.generar_promedios_clase, {"months": months_filter, "all_periods": False}),
                "recap_grafico": (None, None, {}),
            }

            if tipo_post not in generators:
                logger.warning(f"⚠️ Tipo de post no implementado: {tipo_post}")
                return None

            endpoint, generator_fn, params = generators[tipo_post]

            # Manejo especial para tipos que requieren múltiples endpoints
            if tipo_post == "comparativa_aeropuertos":
                prev_mes = self.content_generator._get_prev_month(mes)
                if not prev_mes:
                    return None
                actual = self.api_client.make_request("/vuelos/aeropuerto", {"months": [mes], "all_periods": False})
                anterior = self.api_client.make_request("/vuelos/aeropuerto", {"months": [prev_mes], "all_periods": False})
                return self.content_generator.generar_comparativa_aeropuertos(actual or [], anterior or [], mes)

            if tipo_post == "records_curiosidades":
                vuelos = self.api_client.make_request("/vuelos/diario", {"months": [mes], "all_periods": False})
                pax = self.api_client.make_request("/pasajeros/diario", {"months": [mes], "all_periods": False})
                return self.content_generator.generar_records_curiosidades(vuelos or [], pax or [], mes)

            if tipo_post == "aerolineas_inusuales":
                data = self.api_client.make_request("/vuelos/aerolinea", {"months": [mes], "all_periods": False})
                return self.content_generator.generar_aerolineas_inusuales(data or [], mes)

            if tipo_post == "comparativa_mensual":
                prev_mes = self.content_generator._get_prev_month(mes)
                if not prev_mes:
                    return None
                act = self.api_client.make_request("/vuelos/kpis", {"months": [mes], "all_periods": False})
                prev = self.api_client.make_request("/vuelos/kpis", {"months": [prev_mes], "all_periods": False})
                return self.content_generator.generar_comparativa_mensual(act or {}, prev or {}, mes)

            if tipo_post == "recap_grafico":
                kpis = self.api_client.make_request("/vuelos/kpis", {"months": [mes], "all_periods": False})
                aeros = self.api_client.make_request("/vuelos/aerolinea", {"months": [mes], "all_periods": False, "limit": 10})
                airp = self.api_client.make_request("/vuelos/aeropuerto", {"months": [mes], "all_periods": False, "limit": 10})
                return self.content_generator.generar_recap_grafico(kpis or {}, aeros or [], airp or [], mes)

            # Default: una sola llamada
            data = self.api_client.make_request(endpoint, params if params else None)
            return generator_fn(data, mes)
                
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
    # HTTP SERVER (STATUS + FORCE NEXT)
    # ================================
    def get_next_pending_post(self):
        try:
            mes_actual = self.logger.get_bot_state("current_publishing_month")
            if not mes_actual:
                return {"mes": None, "next": None, "pending": [], "message": "No hay mes de publicación activo"}

            dia_actual = datetime.now().day
            pending = []
            for dia_cronograma, post_config in sorted(self.config.CRONOGRAMA_POSTS.items()):
                if dia_cronograma <= dia_actual:
                    tipo_post = post_config["tipo"]
                    exists = self.logger.check_post_exists(tipo_post, mes_actual, dia_cronograma)
                    if not exists:
                        pending.append({"dia": dia_cronograma, "tipo": tipo_post})

            next_post = pending[0] if pending else None
            return {"mes": mes_actual, "next": next_post, "pending": pending}
        except Exception as e:
            logger.error(f"Error calculando próximo post: {e}")
            return {"error": str(e)}

    def start_http_server(self):
        try:
            app = Flask(__name__)

            @app.get("/status")
            def status():
                info = self.get_next_pending_post()
                return jsonify(info)

            @app.post("/force-next")
            def force_next():
                info = self.get_next_pending_post()
                if not info.get("next") or not info.get("mes"):
                    return jsonify({"ok": False, "message": "No hay próximo post pendiente"}), 400
                dia = info["next"]["dia"]
                mes = info["mes"]
                ok = self.execute_scheduled_post(dia, mes)
                return jsonify({"ok": bool(ok), "dia": dia, "mes": mes})

            # opcional: forzar por parámetros
            @app.post("/force")
            def force():
                body = request.get_json(force=True) if request.data else {}
                dia = int(body.get("dia"))
                mes = body.get("mes")
                if dia is None or mes is None:
                    return jsonify({"ok": False, "message": "Faltan parámetros dia y mes"}), 400
                ok = self.execute_scheduled_post(dia, mes)
                return jsonify({"ok": bool(ok), "dia": dia, "mes": mes})

            # Preview de texto para un día del cronograma en el mes actual
            @app.get("/preview")
            def preview():
                try:
                    dia_param = request.args.get("dia")
                    if dia_param is None:
                        return jsonify({"ok": False, "message": "Falta parámetro 'dia'"}), 400
                    dia = int(dia_param)

                    mes_actual = self.logger.get_bot_state("current_publishing_month")
                    if not mes_actual:
                        # Intentar detectar nuevo mes
                        self.verificar_nuevo_mes()
                        mes_actual = self.logger.get_bot_state("current_publishing_month")
                        if not mes_actual:
                            return jsonify({"ok": False, "message": "No hay mes actual de publicación"}), 400

                    post_config = self.config.CRONOGRAMA_POSTS.get(dia)
                    if not post_config:
                        return jsonify({"ok": False, "message": f"Día {dia} no existe en cronograma"}), 404

                    tipo_post = post_config["tipo"]
                    texto = self.generate_content_for_post_type(tipo_post, mes_actual)
                    if not texto:
                        return jsonify({"ok": False, "message": "No se pudo generar contenido"}), 500

                    return jsonify({
                        "ok": True,
                        "dia": dia,
                        "mes": mes_actual,
                        "tipo": tipo_post,
                        "texto": texto
                    })
                except Exception as e:
                    logger.error(f"Error en /preview: {e}")
                    return jsonify({"ok": False, "message": str(e)}), 500

            # Preview de todos los días del cronograma para el mes actual
            @app.get("/preview-all")
            def preview_all():
                try:
                    mes_actual = self.logger.get_bot_state("current_publishing_month")
                    if not mes_actual:
                        self.verificar_nuevo_mes()
                        mes_actual = self.logger.get_bot_state("current_publishing_month")
                        if not mes_actual:
                            return jsonify({"ok": False, "message": "No hay mes actual de publicación"}), 400

                    resultados = []
                    for dia, cfg in sorted(self.config.CRONOGRAMA_POSTS.items()):
                        tipo = cfg["tipo"]
                        try:
                            texto = self.generate_content_for_post_type(tipo, mes_actual)
                            if texto:
                                resultados.append({
                                    "dia": dia,
                                    "tipo": tipo,
                                    "ok": True,
                                    "texto": texto
                                })
                            else:
                                resultados.append({
                                    "dia": dia,
                                    "tipo": tipo,
                                    "ok": False,
                                    "error": "No se pudo generar contenido"
                                })
                        except Exception as e:
                            resultados.append({
                                "dia": dia,
                                "tipo": tipo,
                                "ok": False,
                                "error": str(e)
                            })

                    return jsonify({
                        "ok": True,
                        "mes": mes_actual,
                        "resultados": resultados
                    })
                except Exception as e:
                    logger.error(f"Error en /preview-all: {e}")
                    return jsonify({"ok": False, "message": str(e)}), 500

            # Debug: obtener JSON crudo de un endpoint permitido
            @app.get("/debug")
            def debug():
                try:
                    endpoint = request.args.get("endpoint")
                    mes = request.args.get("mes")
                    if not endpoint:
                        return jsonify({"ok": False, "message": "Falta parámetro 'endpoint'"}), 400

                    # Lista blanca de endpoints
                    allowed = [
                        "/vuelos/aerolinea",
                        "/vuelos/pasajeros",
                        "/vuelos/ocupacion",
                        "/vuelos/mes",
                        "/vuelos/clase",
                        "/vuelos/aeropuerto",
                        "/vuelos/rutas",
                        "/vuelos/diario",
                        "/pasajeros/diario",
                        "/vuelos/kpis",
                        "/aerolineas/lista",
                        "/vuelos/tipos",
                        "/vuelos/clases",
                        "/vuelos/provincias",
                        "/vuelos/paises",
                        "/vuelos/rutas-enriquecidas",
                        "/vuelos/detallados",
                        "/aeropuertos/evolucion-mensual",
                        "/aeropuertos/lista",
                        "/aeropuertos/rango-meses",
                        "/aeropuertos/aerolineas-cambios",
                        "/vuelos/mapa-rutas",
                        "/aeropuertos/mapa",
                        "/vuelos/mapa/rutas-optimizadas",
                        "/vuelos/mapa/aeropuertos",
                        "/vuelos/mapa/red-aerolinea/{aerolinea}",
                        "/vuelos/mapa/heatmap-trafico",
                    ]

                    if endpoint not in allowed:
                        return jsonify({"ok": False, "message": "Endpoint no permitido"}), 400

                    # Params
                    mes_actual = self.logger.get_bot_state("current_publishing_month")
                    months_filter = [mes or mes_actual] if (mes or mes_actual) else None
                    params = {"months": months_filter, "all_periods": False} if months_filter else {}
                    data = self.api_client.make_request(endpoint, params if params else None)
                    return jsonify({"ok": True, "endpoint": endpoint, "params": params, "data": data})
                except Exception as e:
                    logger.error(f"Error en /debug: {e}")
                    return jsonify({"ok": False, "message": str(e)}), 500

            self.app = app

            port = int(os.getenv("PORT", "8000"))
            thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True)
            thread.start()
            logger.info(f"🌐 HTTP server iniciado en puerto {port} (/status, /force-next, /force)")
        except Exception as e:
            logger.error(f"Error iniciando HTTP server: {e}")

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
        # Iniciar HTTP server para status/acciones
        bot.start_http_server()
        
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