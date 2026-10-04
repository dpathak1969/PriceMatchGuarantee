"""Production entry point for the ML endpoint: waitress is a pure-Python WSGI server that runs on
Windows and Linux (Flask's built-in server is for development only)."""
import os

from waitress import serve

from app import create_app   # same folder, so a plain import works when launched as `python ml_service/serve.py`

if __name__ == "__main__":
    host = os.environ.get("ML_HOST", "127.0.0.1")        # bind to loopback: only the backend should reach us
    port = int(os.environ.get("ML_PORT", "5001"))
    print(f"PMG ML endpoint listening on http://{host}:{port}")
    serve(create_app(), host=host, port=port, threads=4)  # 4 worker threads; model object is read-only so safe to share
