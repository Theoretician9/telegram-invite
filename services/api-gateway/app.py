import os
from quart import Quart
from routes.invite import invite_bp
from routes.parser import parser_bp
from routes.autopost import autopost_bp
from config import Config

def create_app():
    # Создаем приложение с минимальной конфигурацией
    app = Quart(__name__)
    
    # Устанавливаем базовые настройки
    app.config['PROVIDE_AUTOMATIC_OPTIONS'] = False
    
    # Устанавливаем остальную конфигурацию
    app.config.update(
        SECRET_KEY=Config.SECRET_KEY,
        SQLALCHEMY_DATABASE_URI=Config.SQLALCHEMY_DATABASE_URI,
        SQLALCHEMY_TRACK_MODIFICATIONS=Config.SQLALCHEMY_TRACK_MODIFICATIONS,
        REDIS_URL=Config.REDIS_URL,
        CELERY_BROKER_URL=Config.CELERY_BROKER_URL,
        CELERY_RESULT_BACKEND=Config.CELERY_RESULT_BACKEND,
        TELEGRAM_API_ID=Config.TELEGRAM_API_ID,
        TELEGRAM_API_HASH=Config.TELEGRAM_API_HASH,
        STATIC_FOLDER='static',
        TEMPLATE_FOLDER='templates'
    )
    
    # Регистрируем blueprints
    app.register_blueprint(invite_bp, url_prefix='/api/invite')
    app.register_blueprint(parser_bp, url_prefix='/api/parser')
    app.register_blueprint(autopost_bp, url_prefix='/api/autopost')
    
    return app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000) 