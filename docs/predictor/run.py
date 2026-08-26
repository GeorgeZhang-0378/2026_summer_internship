#!/usr/bin/env python3
"""
run.py — 一键跑通整条管线。
- 若检测到 TD_KEY 或 data/gold_history.csv：用真实金价。
- 否则自动生成 demo 金价并继续，同时打印警告。
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD_CSV = os.path.join(HERE, "data", "gold_history.csv")
has_gold = os.path.exists(GOLD_CSV) or os.getenv("TD_KEY")

if not has_gold:
    print("[WARN] 未检测到真实金价来源，将生成 DEMO 金价用于演示。")
    print("       真实运行：填写 .env 中的 TD_KEY，或提供 data/gold_history.csv\n")
    subprocess.run([sys.executable, "make_demo_gold.py"], cwd=HERE, check=True)

subprocess.run([sys.executable, "fetch_factors.py"], cwd=HERE, check=True)
subprocess.run([sys.executable, "train_rf.py"], cwd=HERE, check=True)

print("\n[SUCCESS] site/data/signals.json + backtest.json 已生成。")
print("查看仪表盘：cd site && python -m http.server 8771 --bind 127.0.0.1")
