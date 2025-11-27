import os
import sqlite3

DB_DEFAULT_DIR = "/data" if os.path.isdir("/data") else "."
DB_PATH = os.path.join(DB_DEFAULT_DIR, "twitter_bot_logs.db")

def main():
    if not os.path.exists(DB_PATH):
        print(f"DB no encontrada: {DB_PATH}")
        print("Si estás en Railway, monta el volumen en /data y espera a que el bot cree la DB.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        # Estado actual del bot
        cur.execute("SELECT value FROM bot_state WHERE key='current_publishing_month'")
        row = cur.fetchone()
        mes_actual = row[0] if row else None
        print(f"Mes de publicación actual: {mes_actual}")

        # Tweets enviados por tipo y día
        cur.execute(
            """
            SELECT tipo_post, dia_cronograma, COUNT(*) as enviados
            FROM tweets_log
            WHERE status='success'
            GROUP BY tipo_post, dia_cronograma
            ORDER BY dia_cronograma
            """
        )
        enviados = cur.fetchall()
        print("Tweets enviados (tipo, día, count):")
        for t in enviados:
            print(f" - {t[0]} (día {t[1]}): {t[2]}")

        # Últimos 10 logs
        cur.execute(
            """
            SELECT date_posted, tipo_post, status, mes_relacionado, dia_cronograma
            FROM tweets_log
            ORDER BY date_posted DESC
            LIMIT 10
            """
        )
        print("\nÚltimos 10 logs:")
        for row in cur.fetchall():
            print(f" {row[0]} | {row[1]} | {row[2]} | {row[3]} | día {row[4]}")

if __name__ == "__main__":
    main()
