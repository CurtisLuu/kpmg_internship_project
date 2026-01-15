
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import AzureOpenAI
from jwt import PyJWKClient, decode
import os
from functools import wraps

load_dotenv()

# Development mode - disable token validation for local testing
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

print("AZURE_OPENAI_API_KEY:", os.getenv("AZURE_OPENAI_API_KEY"))
print("AZURE_OPENAI_ENDPOINT:", os.getenv("AZURE_OPENAI_ENDPOINT"))
print("AZURE_OPENAI_API_VERSION:", os.getenv("AZURE_OPENAI_API_VERSION"))
print("DEV_MODE:", DEV_MODE)

app = Flask(__name__)
CORS(app)

client = AzureOpenAI(
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)

# Azure AD Configuration
TENANT_ID = "9f58333b-9cca-4bd9-a7d8-e151e43b79f3"
CLIENT_ID = "a9bda2e7-4cd0-4203-9ae0-62635c58d984"
JWKS_URL = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

# Initialize JWKS client for token validation
jwks_client = PyJWKClient(JWKS_URL)

def verify_token(token):
    """Verify and decode Azure AD token"""
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        decoded = decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=CLIENT_ID,
            issuer=f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
        )
        return decoded
    except Exception as e:
        print(f"Token verification failed: {e}")
        return None

def token_required(f):
    """Decorator to require valid token for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Skip token validation in dev mode
        if DEV_MODE:
            request.user = {"sub": "dev-user", "name": "Dev User", "email": "dev@example.com"}
            return f(*args, **kwargs)
        
        token = None
        
        # Check for token in Authorization header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({"error": "Invalid authorization header"}), 401
        
        if not token:
            return jsonify({"error": "Token is missing"}), 401
        
        # Verify token
        decoded = verify_token(token)
        if not decoded:
            return jsonify({"error": "Invalid or expired token"}), 401
        
        # Store decoded token in request context for later use
        request.user = decoded
        return f(*args, **kwargs)
    
    return decorated_function

@app.route("/api/auth/verify", methods=["POST"])
def verify_auth():
    """Endpoint to verify token validity"""
    data = request.get_json()
    token = data.get("token")
    
    if not token:
        return jsonify({"error": "Token is required"}), 400
    
    decoded = verify_token(token)
    if decoded:
        return jsonify({
            "valid": True,
            "user": {
                "name": decoded.get("name"),
                "email": decoded.get("email"),
                "oid": decoded.get("oid")
            }
        }), 200
    else:
        return jsonify({"valid": False, "error": "Token verification failed"}), 401

@app.route("/api/chat", methods=["POST"])
@token_required
def chat():
    """Chat endpoint - requires valid Azure AD token"""
    data = request.get_json()
    message = data.get("message")
    history = data.get("conversationHistory", [])

    if not message:
        return jsonify({"error": "Message is required"}), 400

    messages = [{"role": "system", "content": "You are a helpful assistant."}] + history + [{"role": "user", "content": message}]

    try:
        completion = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=messages,
            max_completion_tokens=512,
            temperature=0.7
        )

        return jsonify({"message": completion.choices[0].message.content})
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        return jsonify({"error": "Failed to process chat message"}), 500

if __name__ == "__main__":
    app.run(port=5000)
