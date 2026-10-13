"""
Fren web server (FastAPI).

Step 2 only has two pages:
  /      - a placeholder home page (the real screens come in later steps)
  /help  - the "Get help now" page, showing the fixed crisis message

Start the server with:  python run.py
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import config
from app import database
from app.safety import crisis_check

app = FastAPI(title="Fren")

# Serve the files in static/ (CSS, JS, HTML) under /static/...
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


# Make sure the database tables exist before any request arrives.
database.init_db()


@app.get("/")
def home():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/help", response_class=HTMLResponse)
def help_page():
    """
    The "Get help now" page. It wraps the editable crisis_message.html in
    a simple page. It deliberately has no AI and no database calls, so it
    works even if everything else is broken.
    """
    message = crisis_check.crisis_message_html()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fren - Get help now</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <main class="help-page">
    {message}
    <p><a href="/">Back to Fren</a></p>
  </main>
</body>
</html>"""
