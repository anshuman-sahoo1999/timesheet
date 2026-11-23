import os
import sys
import traceback

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from app import app as application
    app = application
    handler = application
except Exception as e:
    err_msg = traceback.format_exc()
    print(f"[CRITICAL STARTUP ERROR] {err_msg}")
    
    def error_handler(environ, start_response):
        start_response('500 Internal Server Error', [('Content-Type', 'text/html; charset=utf-8')])
        return [f"<h2>Application Startup Error</h2><pre>{err_msg}</pre>".encode('utf-8')]
    
    app = error_handler
    handler = error_handler
