from quart import Blueprint, jsonify

autopost_bp = Blueprint('autopost', __name__)

@autopost_bp.route('/status', methods=['GET'])
async def get_status():
    return jsonify({"status": "not implemented yet"}) 