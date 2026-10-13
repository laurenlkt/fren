"""
Start the Fren server.

    python run.py

It listens on config.HOST (127.0.0.1 = this computer only) and config.PORT.
"""

import uvicorn

import config

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=True)
