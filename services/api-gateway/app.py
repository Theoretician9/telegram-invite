import os
from quart import Quart
from routes.invite import invite_bp
from routes.parser import parser_bp
from routes.autopost import autopost_bp
from config import Config
import aioredis
from flask_session import Session

# Создаем базовую конфигурацию
default_config = {
    'PROVIDE_AUTOMATIC_OPTIONS': False,
    'SESSION_TYPE': 'redis',
    'SESSION_REDIS': aioredis.from_url(os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')),
    'MAX_CONTENT_LENGTH': 100 * 1024 * 1024,  # 100 МБ
    'static_folder': 'static',
    'template_folder': 'templates'
}

def create_app(config_class=Config):
    # Создаем приложение
    app = Quart(__name__)
    
    # Устанавливаем конфигурацию
    for key, value in default_config.items():
        app.config[key] = value
    
    # Загружаем остальную конфигурацию
    app.config.from_object(config_class)
    config_class.init_app(app)
    
    # Инициализируем сессии
    Session(app)
    
    # Регистрируем blueprints
    app.register_blueprint(invite_bp, url_prefix='/api/invite')
    app.register_blueprint(parser_bp, url_prefix='/api/parser')
    app.register_blueprint(autopost_bp, url_prefix='/api/autopost')
    
    return app

# Создаем экземпляр приложения
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000) 