import os
from quart import Quart
from routes.invite import invite_bp
from routes.parser import parser_bp
from routes.autopost import autopost_bp
from config import Config

def create_app(config_class=Config):
    # Создаем приложение
    app = Quart(__name__)
    
    # Загружаем конфигурацию
    app.config.from_object(config_class)
    
    # Устанавливаем дополнительные настройки
    app.config.update(
        PROVIDE_AUTOMATIC_OPTIONS=False,
        JSON_AS_ASCII=False,
        JSONIFY_PRETTYPRINT_REGULAR=True,
        JSONIFY_MIMETYPE='application/json'
    )
    
    # Регистрируем blueprints
    app.register_blueprint(invite_bp, url_prefix='/api/invite')
    app.register_blueprint(parser_bp, url_prefix='/api/parser')
    app.register_blueprint(autopost_bp, url_prefix='/api/autopost')
    
    return app

# Создаем экземпляр приложения
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000) 