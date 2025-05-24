from quart import Quart
from routes.invite import invite_bp
from routes.parser import parser_bp
from routes.autopost import autopost_bp

app = Quart(__name__)
app.config['PROVIDE_AUTOMATIC_OPTIONS'] = True

# Регистрируем blueprints
app.register_blueprint(invite_bp, url_prefix='/api/invite')
app.register_blueprint(parser_bp, url_prefix='/api/parser')
app.register_blueprint(autopost_bp, url_prefix='/api/autopost')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000) 