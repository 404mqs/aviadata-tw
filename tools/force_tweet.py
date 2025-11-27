import sys
from bot import TwitterBot

def main():
    if len(sys.argv) != 3:
        print("Uso: python tools/force_tweet.py <dia_cronograma> <mes>")
        print("Ejemplo: python tools/force_tweet.py 0 2025-09")
        sys.exit(1)

    dia = int(sys.argv[1])
    mes = sys.argv[2]

    bot = TwitterBot()
    ok = bot.execute_scheduled_post(dia, mes)
    print("Tweet enviado" if ok else "Error enviando tweet")

if __name__ == "__main__":
    main()
