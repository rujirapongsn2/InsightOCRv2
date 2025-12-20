#!/usr/bin/env python3
"""
API Integration Webhook Receiver
Usage: python api-test.py [options]

This script creates a simple webhook receiver to test API-type integrations.
It receives POST/PUT requests from InsightOCR and displays the received data.
"""

import argparse
import json
import sys
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging

app = Flask(__name__)

# Enable CORS for all routes
CORS(app, resources={
    r"/*": {
        "origins": ["http://localhost:3000", "http://127.0.0.1:3000"],
        "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-API-Key", "X-Custom-Header"]
    }
})

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Store received requests for review
received_requests = []


@app.route('/webhook', methods=['POST', 'PUT', 'PATCH', 'GET'])
def webhook_receiver():
    """Webhook endpoint that receives and logs integration data"""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "="*80)
    print(f"📨 Received {request.method} request at {timestamp}")
    print("="*80)

    # Log request headers
    print("\n📋 Headers:")
    for key, value in request.headers.items():
        # Mask sensitive headers
        if any(sensitive in key.lower() for sensitive in ['authorization', 'token', 'key', 'secret']):
            masked_value = value[:20] + '...' if len(value) > 20 else '***'
            print(f"  {key}: {masked_value}")
        else:
            print(f"  {key}: {value}")

    # Log request body
    try:
        if request.is_json:
            payload = request.get_json()
            print("\n📦 Payload (JSON):")
            print(json.dumps(payload, indent=2, ensure_ascii=False))

            # Display specific fields if present
            if isinstance(payload, dict):
                if 'job_id' in payload:
                    print(f"\n✅ Job ID: {payload['job_id']}")
                if 'job_name' in payload:
                    print(f"✅ Job Name: {payload['job_name']}")
                if 'documents' in payload and isinstance(payload['documents'], list):
                    print(f"✅ Documents Count: {len(payload['documents'])}")
                    for idx, doc in enumerate(payload['documents'], 1):
                        print(f"\n  Document {idx}:")
                        print(f"    - ID: {doc.get('id', 'N/A')}")
                        print(f"    - Filename: {doc.get('filename', 'N/A')}")
                        print(f"    - Schema ID: {doc.get('schema_id', 'N/A')}")
                        print(f"    - Status: {doc.get('status', 'N/A')}")
                        if 'data' in doc:
                            print(f"    - Data: {json.dumps(doc['data'], indent=6, ensure_ascii=False)}")
        else:
            body_text = request.get_data(as_text=True)
            print("\n📄 Payload (Text):")
            print(body_text[:1000])  # Show first 1000 chars
            payload = {"raw": body_text}
    except Exception as e:
        print(f"\n⚠️  Error parsing payload: {e}")
        payload = None

    # Log query parameters
    if request.args:
        print("\n🔗 Query Parameters:")
        for key, value in request.args.items():
            print(f"  {key}: {value}")

    print("\n" + "="*80 + "\n")

    # Store request for later review
    request_data = {
        "timestamp": timestamp,
        "method": request.method,
        "headers": dict(request.headers),
        "payload": payload,
        "query_params": dict(request.args)
    }
    received_requests.append(request_data)

    # Return success response
    response = {
        "status": "success",
        "message": "Data received successfully",
        "timestamp": timestamp,
        "received_documents": len(payload.get('documents', [])) if isinstance(payload, dict) else 0
    }

    return jsonify(response), 200


@app.route('/webhook/test', methods=['GET'])
def test_endpoint():
    """Test endpoint to verify server is running"""
    return jsonify({
        "status": "ok",
        "message": "Webhook receiver is running",
        "endpoint": "/webhook",
        "supported_methods": ["POST", "PUT", "PATCH", "GET"]
    }), 200


@app.route('/webhook/history', methods=['GET'])
def view_history():
    """View history of received requests"""
    return jsonify({
        "total_requests": len(received_requests),
        "requests": received_requests
    }), 200


@app.route('/webhook/clear', methods=['POST'])
def clear_history():
    """Clear request history"""
    global received_requests
    count = len(received_requests)
    received_requests = []
    return jsonify({
        "status": "success",
        "message": f"Cleared {count} requests"
    }), 200


def main():
    parser = argparse.ArgumentParser(
        description="API Integration Webhook Receiver for Testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start server on default port 5000
  python api-test.py

  # Start server on custom port
  python api-test.py --port 8080

  # Start server accessible from network
  python api-test.py --host 0.0.0.0 --port 8080

Integration Setup in InsightOCR:
  1. Go to Integration page
  2. Create new integration (Type: API)
  3. Set Endpoint URL: http://localhost:5000/webhook
  4. Set HTTP Method: POST
  5. (Optional) Add headers for testing
  6. Save and test by sending data from a reviewed job

Available Endpoints:
  POST/PUT /webhook       - Main webhook receiver
  GET      /webhook/test  - Test endpoint
  GET      /webhook/history - View received requests history
  POST     /webhook/clear  - Clear history
        """
    )

    parser.add_argument(
        '--host', '-H',
        default='127.0.0.1',
        help='Host to bind to (default: 127.0.0.1, use 0.0.0.0 for all interfaces)'
    )

    parser.add_argument(
        '--port', '-p',
        type=int,
        default=5000,
        help='Port to listen on (default: 5000)'
    )

    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Enable debug mode'
    )

    args = parser.parse_args()

    print("\n" + "="*80)
    print("🚀 API Integration Webhook Receiver")
    print("="*80)
    print(f"\n📡 Server starting on http://{args.host}:{args.port}")
    print(f"\n📍 Endpoints:")
    print(f"   POST/PUT  http://{args.host}:{args.port}/webhook")
    print(f"   GET       http://{args.host}:{args.port}/webhook/test")
    print(f"   GET       http://{args.host}:{args.port}/webhook/history")
    print(f"   POST      http://{args.host}:{args.port}/webhook/clear")

    print(f"\n⚙️  Integration Setup:")
    print(f"   1. Go to InsightOCR → Integration → Add Integration")
    print(f"   2. Type: API")
    print(f"   3. Endpoint URL: http://{args.host}:{args.port}/webhook")
    print(f"   4. HTTP Method: POST")
    print(f"   5. Save and test!")

    print("\n💡 Tips:")
    print("   - Press Ctrl+C to stop the server")
    print("   - Check terminal for received requests")
    print("   - View history at /webhook/history")

    print("\n" + "="*80 + "\n")

    try:
        app.run(
            host=args.host,
            port=args.port,
            debug=args.debug
        )
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
