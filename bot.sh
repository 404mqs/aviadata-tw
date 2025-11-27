#!/bin/bash

# Script de utilidades para el Bot de Twitter

set -e

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BOT_DIR"

case "${1}" in
    "install")
        echo "📦 Instalando dependencias..."
        pip install -r requirements.txt
        echo "✅ Instalación completa"
        ;;
    
    "test")
        echo "🧪 Ejecutando tests..."
        python test_bot.py
        ;;
    
    "run")
        echo "🚀 Iniciando bot..."
        python bot.py
        ;;
    
    "logs")
        echo "📋 Últimos logs de tweets..."
        if [ -f "twitter_bot_logs.db" ]; then
            sqlite3 twitter_bot_logs.db "SELECT date_posted, tipo_post, status, mes_relacionado FROM tweets_log ORDER BY date_posted DESC LIMIT 10;"
        else
            echo "❌ No se encontró base de datos de logs"
        fi
        ;;
    
    "status")
        echo "📊 Estado del bot..."
        if [ -f "twitter_bot_logs.db" ]; then
            echo "🗓️  Mes actual:"
            sqlite3 twitter_bot_logs.db "SELECT value FROM bot_state WHERE key='current_publishing_month';"
            echo "📈 Total tweets enviados:"
            sqlite3 twitter_bot_logs.db "SELECT COUNT(*) FROM tweets_log WHERE status='success';"
            echo "❌ Tweets con error:"
            sqlite3 twitter_bot_logs.db "SELECT COUNT(*) FROM tweets_log WHERE status='error';"
        else
            echo "❌ No se encontró base de datos de logs"
        fi
        ;;
    
    "reset")
        echo "🗑️  Eliminando logs para reset completo..."
        rm -f twitter_bot_logs.db
        echo "✅ Reset completado"
        ;;
    
    "force-tweet")
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo "❌ Uso: ./bot.sh force-tweet <dia> <mes>"
            echo "   Ejemplo: ./bot.sh force-tweet 0 2025-09"
            exit 1
        fi
        
        echo "🚀 Forzando tweet día $2 para mes $3..."
        python -c "
from bot import TwitterBot
bot = TwitterBot()
success = bot.execute_scheduled_post($2, '$3')
print('✅ Tweet enviado' if success else '❌ Error enviando tweet')
"
        ;;
    
    "docker-build")
        echo "🐳 Building Docker image..."
        docker build -t aviadata-twitter-bot .
        echo "✅ Docker image built"
        ;;
    
    "docker-run")
        echo "🐳 Running Docker container..."
        if [ ! -f ".env" ]; then
            echo "❌ Archivo .env no encontrado. Copia env.example como .env y configura las credenciales."
            exit 1
        fi
        
        docker run -d --name aviadata-twitter-bot \
            --env-file .env \
            -v "$(pwd)/data:/app/data" \
            aviadata-twitter-bot
        
        echo "✅ Bot running in Docker container"
        echo "📋 Ver logs: docker logs -f aviadata-twitter-bot"
        ;;
    
    "help"|*)
        echo "🤖 Bot de Twitter de Aviadata - Utilidades"
        echo ""
        echo "Uso: ./bot.sh <comando>"
        echo ""
        echo "Comandos disponibles:"
        echo "  install          - Instalar dependencias"
        echo "  test            - Ejecutar tests del bot"
        echo "  run             - Iniciar bot"
        echo "  logs            - Ver últimos tweets enviados"
        echo "  status          - Ver estado del bot"
        echo "  reset           - Borrar logs (reset completo)"
        echo "  force-tweet <dia> <mes> - Forzar tweet específico"
        echo "  docker-build    - Construir imagen Docker"
        echo "  docker-run      - Ejecutar en Docker"
        echo "  help            - Mostrar esta ayuda"
        echo ""
        echo "Ejemplos:"
        echo "  ./bot.sh install"
        echo "  ./bot.sh test"
        echo "  ./bot.sh run"
        echo "  ./bot.sh force-tweet 0 2025-09"
        ;;
esac