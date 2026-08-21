from pathlib import Path
import argparse
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FACTOR_DIR = ROOT / "factor_tests"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["london", "shanghai"], required=True)
    p.add_argument("--horizon", type=int, default=20)
    args = p.parse_args()

    failures = []
    for script in sorted(FACTOR_DIR.glob("[0-9][0-9]_*.py")):
        print("\n" + "=" * 100)
        print(script.name)
        print("=" * 100)
        r = subprocess.run([
            sys.executable,
            str(script),
            "--market", args.market,
            "--horizon", str(args.horizon),
        ])
        if r.returncode != 0:
            failures.append(script.name)

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(" -", f)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
