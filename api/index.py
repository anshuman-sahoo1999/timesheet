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

# Ensure project root is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app import app
