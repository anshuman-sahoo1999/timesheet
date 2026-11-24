import os
import sys

# Ensure markupsafe and werkzeug compatibility for Flask-WTF and extensions
try:
    import markupsafe
    import flask
    flask.Markup = markupsafe.Markup
    flask.escape = markupsafe.escape
except Exception:
    pass

try:
    import urllib.parse
    import werkzeug.urls
    if not hasattr(werkzeug.urls, 'url_encode'):
        werkzeug.urls.url_encode = urllib.parse.urlencode
    if not hasattr(werkzeug.urls, 'url_quote'):
        werkzeug.urls.url_quote = urllib.parse.quote
    if not hasattr(werkzeug.urls, 'url_unquote'):
        werkzeug.urls.url_unquote = urllib.parse.unquote
except Exception:
    pass

try:
    import psycopg2
    sys.modules['psycopg'] = psycopg2
except Exception:
    pass

# Ensure project root is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from app import app
    
    class VercelPathMiddleware:
        def __init__(self, wsgi_app):
            self.wsgi_app = wsgi_app

        def __call__(self, environ, start_response):
            import urllib.parse
            query_string = environ.get('QUERY_STRING', '')
            params = urllib.parse.parse_qs(query_string) if query_string else {}
            resolved_path = None
            if 'path' in params and params['path'] and params['path'][0]:
                p = params['path'][0]
                if not p.startswith('/'):
                    p = '/' + p
                if p not in ('/api/index', '/api/index.py', '/api'):
                    resolved_path = p

            if not resolved_path:
                candidate = (
                    environ.get('HTTP_X_MATCHED_PATH') or 
                    environ.get('HTTP_X_FORWARDED_PATH') or 
                    environ.get('HTTP_X_FORWARDED_URI') or 
                    environ.get('HTTP_X_ORIGINAL_URI') or 
                    environ.get('HTTP_X_REAL_PATH') or 
                    environ.get('REQUEST_URI') or 
                    environ.get('RAW_URI')
                )
                if candidate:
                    clean = candidate.split('?')[0].strip()
                    if clean and clean not in ('/api/index', '/api/index.py', '/api'):
                        if not clean.startswith('/'):
                            clean = '/' + clean
                        resolved_path = clean

            current_path = environ.get('PATH_INFO', '')
            if resolved_path:
                environ['PATH_INFO'] = resolved_path
            elif current_path in ('/api/index', '/api/index.py', '/api', '', None):
                environ['PATH_INFO'] = '/'

            def custom_start_response(status, headers, exc_info=None):
                headers.append(('X-Resolved-Path', str(environ.get('PATH_INFO', ''))))
                headers.append(('X-Environ-Keys', ','.join(k for k in environ.keys() if 'HTTP' in k or 'PATH' in k or 'URI' in k or 'ROUT' in k or 'VERCEL' in k)))
                for k in environ:
                    if 'PATH' in k or 'URI' in k or 'URL' in k:
                        headers.append((f'X-Val-{k}', str(environ[k])[:100]))
                return start_response(status, headers, exc_info)

            return self.wsgi_app(environ, custom_start_response)
            
    app.wsgi_app = VercelPathMiddleware(app.wsgi_app)
except Exception as e:
    import traceback
    tb = traceback.format_exc()
    print(f"[IMPORT_ERROR] Failed to import app: {tb}", file=sys.stderr)
    from flask import Flask, Response
    app = Flask(__name__)
    @app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'HEAD'])
    @app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'HEAD'])
    def catch_all(path):
        return Response(
            f"<h2>Application Startup Error</h2><p>Could not import app.py:</p><pre>{tb}</pre>",
            status=500,
            mimetype='text/html'
        )
