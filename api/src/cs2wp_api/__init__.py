"""cs2wp-api: FastAPI service (REST + live WebSocket gateway)."""

import argparse

__version__ = "0.1.0"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cs2wp-api")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    a = ap.parse_args(argv)
    import uvicorn
    uvicorn.run("cs2wp_api.app:app", host=a.host, port=a.port, reload=a.reload)
