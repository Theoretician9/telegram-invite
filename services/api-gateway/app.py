from quart import Quart, request, jsonify
from quart_cors import cors
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Create Quart application
app = Quart(__name__)
app = cors(app, allow_origin="*")

# Basic health check endpoint
@app.route("/api/health")
async def health_check():
    return jsonify({"status": "healthy"})

# Import and register blueprints
from routes.invite import invite_bp
from routes.parser import parser_bp
from routes.autopost import autopost_bp

app.register_blueprint(invite_bp, url_prefix="/api/invite")
app.register_blueprint(parser_bp, url_prefix="/api/parser")
app.register_blueprint(autopost_bp, url_prefix="/api/autopost")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000) 