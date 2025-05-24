import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Базовые настройки
    SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")
    STATIC_FOLDER = 'static'
    TEMPLATE_FOLDER = 'templates'
    
    # Настройки базы данных
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "mysql+pymysql://user:password@mysql:3306/telegram_invite")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Настройки Redis и Celery
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/0")
    
    # Настройки Telegram
    TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
    
    # Настройки приложения
    PROVIDE_AUTOMATIC_OPTIONS = False
    JSON_AS_ASCII = False
    JSONIFY_PRETTYPRINT_REGULAR = True
    JSONIFY_MIMETYPE = 'application/json' 