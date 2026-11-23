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
