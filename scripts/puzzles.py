"""Fill the puzzle library ahead of time (the background task builds one every few minutes on its own).

    python scripts/puzzles.py --redis redis://localhost:6379/0 --count 30
    python scripts/puzzles.py --redis redis://... --stock          # just show what's stored

Each puzzle is checked with the team simulator (about 10 s each). Daily puzzles are topped up first
(puzzle.DAILY_BUFFER ahead), then the personal library. There's no default Redis on purpose: pass --redis.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis", required=True, help="the Redis to store them in")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--stock", action="store_true", help="only print how many are stored")
    args = parser.parse_args()
    import os
    os.environ["REDIS_URL"] = args.redis
    from app import create_app
    from app.game import puzzle
    app = create_app()
    with app.app_context():
        print("stored:", puzzle.stock())
        if args.stock:
            return
        for n in range(args.count):
            t = time.time()
            went = puzzle.generate_one()
            if not went:
                print("the library is full")
                break
            print(f"{n + 1}/{args.count} -> {went} ({time.time() - t:.1f}s)", flush=True)
        print("stored:", puzzle.stock())


if __name__ == "__main__":
    main()
