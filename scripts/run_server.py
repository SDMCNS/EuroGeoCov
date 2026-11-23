"""Server runner for EuroGeoCov FastAPI Application and Web Visualizer."""

import sys
import argparse
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="EuroGeoCov API and Web Visualizer Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args = parser.parse_args()

    print(f"\n=======================================================")
    print(f"🛰️  EuroGeoCov Web Visualizer & API Server Starting")
    print(f"   URL: http://{args.host}:{args.port}")
    print(f"   API Docs: http://{args.host}:{args.port}/docs")
    print(f"=======================================================\n")

    try:
        uvicorn.run("eurogeocov.api.app:app", host=args.host, port=args.port, reload=args.reload)
    except KeyboardInterrupt:
        print("\n[EuroGeoCov] Server stopped by user.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
