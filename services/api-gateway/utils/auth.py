from functools import wraps
from quart import request, jsonify
from jose import jwt
import os

def require_auth(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"error": "No authorization header"}), 401

        try:
            # Get token from header
            token = auth_header.split(" ")[1]
            
            # Verify token
            payload = jwt.decode(
                token,
                os.getenv("JWT_SECRET", "your-secret-key"),
                algorithms=["HS256"]
            )
            
            # Add user info to request context
            request.user = payload
            
            return await f(*args, **kwargs)
        except Exception as e:
            return jsonify({"error": "Invalid token"}), 401

    return decorated 