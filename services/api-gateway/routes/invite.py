from quart import Blueprint, request, jsonify
from models.invite import InviteLog
from services.invite import InviteService
from utils.auth import require_auth

invite_bp = Blueprint("invite", __name__)
invite_service = InviteService()

@invite_bp.route("/start", methods=["POST"])
@require_auth
async def start_invite():
    data = await request.get_json()
    try:
        result = await invite_service.start_invite(
            target=data["target"],
            message=data["message"],
            delay=data.get("delay", 0)
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@invite_bp.route("/status/<task_id>", methods=["GET"])
@require_auth
async def get_status(task_id):
    try:
        status = await invite_service.get_status(task_id)
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 404

@invite_bp.route("/stop/<task_id>", methods=["POST"])
@require_auth
async def stop_invite(task_id):
    try:
        result = await invite_service.stop_invite(task_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400 