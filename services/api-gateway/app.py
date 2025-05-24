from quart import Quart
from quart_cors import cors
from config import Config

# Create Quart application
app = Quart(__name__)
app.config.from_object(Config)
app = cors(app, allow_origin=["*"])

# Import and register blueprints
from routes import register_routes
register_routes(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000) 