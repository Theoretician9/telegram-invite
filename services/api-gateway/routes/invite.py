from quart import Blueprint, request, jsonify
from ..tasks.invite import process_invite

invite_bp = Blueprint('invite', __name__)

@invite_bp.route('/start', methods=['POST'])
async def start_invite():
    data = await request.get_json()
    target = data.get('target')
    message = data.get('message')
    
    if not target:
        return jsonify({"error": "Target is required"}), 400
        
    task = process_invite.delay(target, message)
    return jsonify({"task_id": task.id, "status": "started"})

@invite_bp.route('/status/<task_id>', methods=['GET'])
async def get_status(task_id):
    task = process_invite.AsyncResult(task_id)
    return jsonify({
        "task_id": task_id,
        "status": task.status,
        "result": task.result if task.ready() else None
    }) 