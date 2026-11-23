"""Run the unified FastAPI workbench and its built SPA on port 8503."""

import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8503)
    args = parser.parse_args()
    uvicorn.run("cecep_console.api:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
