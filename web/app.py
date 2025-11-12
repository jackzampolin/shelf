"""
Scanshelf Web Frontend

Minimalist Flask application for visualizing book processing pipeline.
Follows ADR 000 (Information Hygiene), ADR 001 (Think Data First),
and ADR 002 (Stage Independence).

Usage:
    python web/app.py
    python web/app.py --port 1337 --host 127.0.0.1
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask
from web.config import Config


def create_app():
    """Create and configure Flask app."""
    app = Flask(__name__)
    app.config.from_object(Config)

    # Register route blueprints
    from web.routes.library_routes import library_bp
    from web.routes.stage_routes import stage_bp

    app.register_blueprint(library_bp)
    app.register_blueprint(stage_bp)

    return app


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scanshelf Web Frontend")
    parser.add_argument("--port", type=int, default=Config.PORT)
    parser.add_argument("--host", default=Config.HOST)
    parser.add_argument("--debug", action="store_true", default=Config.DEBUG)
    args = parser.parse_args()

    app = create_app()

    print(f"\n🚀 Scanshelf Web starting on http://{args.host}:{args.port}")
    print(f"📁 Library: {Config.BOOK_STORAGE_ROOT}\n")
    print(f"✨ Open http://{args.host}:{args.port} in your browser\n")

    app.run(host=args.host, port=args.port, debug=args.debug)
