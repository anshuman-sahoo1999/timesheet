import os
import sys
import traceback

# Ensure project root is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from app import app as application

    class SafeWSGI:
        def __init__(self, wsgi):
            self.wsgi = wsgi

        def __call__(self, environ, start_response):
            path = environ.get('PATH_INFO', '')
            if path.startswith('/api/index'):
                clean_path = path[len('/api/index'):]
                environ['PATH_INFO'] = clean_path if clean_path else '/'
            try:
                return self.wsgi(environ, start_response)
            except BaseException as e:
                err = traceback.format_exc()
                print(f"[RUNTIME EXCEPTION] {err}", flush=True)
                start_response('500 Internal Server Error', [('Content-Type', 'text/html; charset=utf-8')])
                return [f'<html><head><title>App Error</title></head><body style="font-family:monospace;padding:20px;background:#1a1a1a;color:#ff6b6b;"><h2>Application Runtime Error (500)</h2><pre style="white-space:pre-wrap;background:#2d2d2d;padding:15px;border-radius:6px;color:#f8f8f2;">{err}</pre></body></html>'.encode('utf-8')]

    app = SafeWSGI(application)
    handler = app

except BaseException as e:
    err_msg = traceback.format_exc()
    print(f"[CRITICAL STARTUP ERROR] {err_msg}", flush=True)
    
    def error_handler(environ, start_response):
        start_response('500 Internal Server Error', [('Content-Type', 'text/html; charset=utf-8')])
        return [f'<html><head><title>Startup Error</title></head><body style="font-family:monospace;padding:20px;background:#1a1a1a;color:#ff6b6b;"><h2>Application Startup Error (500)</h2><pre style="white-space:pre-wrap;background:#2d2d2d;padding:15px;border-radius:6px;color:#f8f8f2;">{err_msg}</pre></body></html>'.encode('utf-8')]
    
    app = error_handler
    handler = error_handler
