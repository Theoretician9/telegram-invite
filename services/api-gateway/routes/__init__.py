from .invite import invite_bp
from .parser import parser_bp
from .autopost import autopost_bp

def register_routes(app):
    app.register_blueprint(invite_bp, url_prefix="/api/invite")
    app.register_blueprint(parser_bp, url_prefix="/api/parser")
    app.register_blueprint(autopost_bp, url_prefix="/api/autopost") 