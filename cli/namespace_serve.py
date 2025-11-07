import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def cmd_serve(args):
    from web.app import create_app
    from web.config import Config

    app = create_app()

    print(f"\n🚀 Scanshelf Web starting on http://{args.host}:{args.port}")
    print(f"📁 Library: {Config.BOOK_STORAGE_ROOT}\n")
    print(f"✨ Open http://{args.host}:{args.port} in your browser\n")

    app.run(host=args.host, port=args.port, debug=args.debug)


def setup_serve_parser(subparsers):
    from web.config import Config
    serve_parser = subparsers.add_parser('serve', help='Start the web frontend server')
    serve_parser.add_argument('--port', type=int, default=Config.PORT, help=f'Port to run the server on (default: {Config.PORT})')
    serve_parser.add_argument('--host', default=Config.HOST, help=f'Host to bind to (default: {Config.HOST})')
    serve_parser.add_argument('--debug',action='store_true',default=Config.DEBUG,help='Enable Flask debug mode')
    serve_parser.set_defaults(func=cmd_serve)
