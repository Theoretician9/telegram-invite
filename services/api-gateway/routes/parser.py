from quart import Blueprint, jsonify

parser_bp = Blueprint('parser', __name__)

@parser_bp.route('/status', methods=['GET'])
async def get_status():
    return jsonify({"status": "not implemented yet"}) 