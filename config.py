import os
from dotenv import load_dotenv

load_dotenv()

# Настройки Telegram бота
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '5354843188:AAGw7HfazJXuxlruAMTYesFCHljTBahfHgk')

# Настройки MySQL
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'sport_surgut'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'port': int(os.getenv('DB_PORT', 3306))
}

# Mistral API
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY', 'QHbFv083lIZ2UcrQUcjNNqE9tYA80edU')
MISTRAL_API_URL = 'https://api.mistral.ai/v1/chat/completions'