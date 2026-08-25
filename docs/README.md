# 黄金大周期研究框架 · Gold Supercycle Research

一条 300 年的真实金价曲线（1717 牛顿金平价 — 2026），三轮大周期，九个定价因子。
以「历史周期 — 定价机制 — 供需变化 — 资产配置 — 交易信号」重构黄金研究叙事。

> 本仓库为定制版：白色主题；大事记起点为 1717 年（原版为公元前 550 年）；已移除原站水印脚本。

## 数据来源与可信度说明（重要）

本站的"数据"分三层，可信度各不相同，已逐行代码核实：

### 1. 实时数据（浏览器端真实拉取）✅
- **XAU/USD 现货价**：页面每 60 秒从免费公开 API `https://api.gold-api.com/price/XAU` 真实拉取（8 秒超时，失败静默回退到 localStorage 缓存 / 「2026-08-21 收盘快照」，卡片角标区分"实时/快照"）。
- 相关代码在 `assets/index-Dq0O19sk.js` 中搜索 `gold-live-cache-v1` 可见。

### 2. 内嵌快照数据（生成时从公开数据源抓取，硬编码进 bundle）📦
- **1,250 个日线日期**（2024-08-20 ~ 2026-08-21）的 COMEX 期金 / GLD / GVZ 等序列，来自 Yahoo Finance / FRED，图表（K线、量价、波动率）由这些内嵌数据渲染。
- 相关性矩阵、历史年化收益/波动等统计量由这些日线在生成时计算。
- 每个图表下方都标注了来源链接（LBMA、世界黄金协会、FRED、Yahoo Finance、Cboe）。

### 3. 预计算结果（生成时算好，非浏览器端实时模拟）🧮
- **蒙特卡洛 4,000 组有效前沿**：经核实，bundle 内应用层**没有** `Math.random` 调用——散点是生成时预先算好嵌入的，页面加载后不会重新模拟。
- 「固收+黄金」配置测算器的滑块联动（年化收益/波动/夏普）是浏览器端用内嵌统计量实时插值计算的，这部分是活的。

### 结论
页面不是"瞎画的"：实时价是真的，历史图表基于真实行情快照，分析文字是生成时的研究综述。但 2026 年的"最新"数据停留在生成日（2026-08-21 收盘），不会自动更新（除现货价外）。

## 文件结构

```
├── index.html                      # 入口（Vite SPA 壳）
├── assets/
│   ├── index-Dq0O19sk.js           # 完整应用（React 18 + ECharts，含全部数据与绘图逻辑）
│   └── index-w44_WfrZ.css          # 全部样式
├── reference/
│   └── app.pretty.js               # 美化后的可读版 bundle（查阅绘图代码用，不参与运行）
└── .nojekyll                       # 告诉 GitHub Pages 不要用 Jekyll 处理
```

原始项目为 React + TypeScript + Vite + ECharts，源文件结构（从 bundle 的 code-path 调试信息还原）：

```
src/main.tsx · src/App.tsx · src/pages/Home.tsx
src/components/Chart.tsx · src/components/SectionHead.tsx
src/sections/Hero.tsx · History.tsx · Mechanism.tsx · Market.tsx
             Allocation.tsx · Signal.tsx · News.tsx · Footer.tsx
```

⚠️ 原始 `.tsx` 源码从未公开发布，无法恢复；`reference/app.pretty.js` 是编译产物的可读版，包含全部 ECharts 绘图配置，可用于参考或二次开发。

## 本地运行

```bash
cd gold-supercycle
python3 -m http.server 8765
# 打开 http://127.0.0.1:8765 （macOS Safari 请用 127.0.0.1 而非 localhost）
#https://georgezhang-0378.github.io/2026_summer_internship/
```


## GitHub Pages 部署

Settings → Pages → Source 选 `main` 分支根目录，访问：
`https://<username>.github.io/gold-supercycle/`

页面使用 hash 路由（`#history` `#market` `#news` 等），天然兼容 GitHub Pages，无需 404 重定向配置。

## 免责声明

本站内容仅供研究演示，不构成投资建议。
