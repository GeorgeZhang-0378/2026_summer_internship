from pathlib import Path
import argparse
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "results" / "factor_tests"
OUT = ROOT / "results" / "audit"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["london", "shanghai"], required=True)
    p.add_argument("--horizon", type=int, default=20)
    args = p.parse_args()

    rows = []
    for path in IN.glob(f"{args.market}__*__{args.horizon}d.json"):
        rows.append(json.loads(path.read_text(encoding="utf-8")))

    if not rows:
        raise SystemExit("No factor summaries found. Run factor tests first.")

    df = pd.DataFrame(rows)
    df["research_flag"] = (
        (df["n_folds"] >= 5)
        & (
            (df["auc"].fillna(0) >= 0.52)
            | (df["ic"].abs().fillna(0) >= 0.03)
        )
        & (df["sign_consistency"].fillna(0) >= 0.60)
    )

    df = df.sort_values(
        ["research_flag", "auc", "ic"],
        ascending=[False, False, False],
    )
    csv_path = OUT / f"{args.market}_factor_audit_{args.horizon}d.csv"
    md_path = OUT / f"{args.market}_factor_audit_{args.horizon}d.md"
    df.to_csv(csv_path, index=False)
    md_path.write_text(df.to_markdown(index=False), encoding="utf-8")
    print(df.to_string(index=False))
    print("\nSaved:", csv_path)
    print("Saved:", md_path)


if __name__ == "__main__":
    main()
