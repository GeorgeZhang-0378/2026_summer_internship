# Factor Library / 因子库

This file is the research registry.  
本文件是因子研究注册表。

| # | Factor family | London | Shanghai | Data | Initial rationale |
|---:|---|:---:|:---:|---|---|
| 01 | Momentum | ✓ | ✓ | local price | trend persistence |
| 02 | Trend strength / breakout | ✓ | ✓ | local price | persistent directional regime |
| 03 | Mean reversion | ✓ | ✓ | local price | over-extension correction |
| 04 | Realised volatility | ✓ | ✓ | local price | regime/risk dependence |
| 05 | Skew / kurtosis | ✓ | ✓ | local price | asymmetric return distribution |
| 06 | Intraday range / gap | ✓ | ✓ | local OHLC | stress and price-discovery information |
| 07 | Volume | — | ✓ | SHFE | participation confirmation |
| 08 | Open interest | — | ✓ | SHFE | position accumulation / liquidation |
| 09 | Turnover / liquidity | — | ✓ | SHFE | market activity / liquidity |
| 10 | Settlement-close basis | — | ✓ | SHFE | futures settlement information |
| 11 | Seasonality | experimental | ✓ | calendar | calendar / local demand timing |
| 12 | Real yield | ✓ | ✓ | FRED DFII10 | gold opportunity cost |
| 13 | Nominal yield curve | ✓ | ✓ | FRED DGS2/DGS10 | rates / macro regime |
| 14 | Broad USD | ✓ | ✓ | FRED DTWEXBGS | FX opportunity cost |
| 15 | VIX risk sentiment | ✓ | ✓ | FRED VIXCLS | risk & uncertainty |
| 16 | Breakeven inflation | ✓ | ✓ | FRED T10YIE | inflation expectations |
| 17 | Credit spread | ✓ | ✓ | FRED BAMLH0A0HYM2 | systemic risk |
| 18 | CFTC managed money | ✓ | ✓ | CFTC | positioning / crowding |
| 19 | USD/CNY | optional | ✓ | FRED DEXCHUS | RMB translation / local gold |
| 20 | Shanghai-London premium | — | ✓ | both markets + FX | local vs global relative value |
| 21 | Cross-market lead/lag | ✓ | ✓ | both markets | timezone / price discovery |
| 22 | Gold ETF flows | ✓ | ✓ | WGC/user file | investor flow confirmation |

## Research rule

A family can contain multiple raw features, but it should not receive multiple votes simply because we created many similar transformations.  
一个因子家族可以包含多个原始特征，但不能因为我们制造了很多相似指标就获得不合理的重复权重。

The final model should eventually work with approximately 8–12 family scores rather than dozens of highly correlated raw variables.  
最终模型应该尽量压缩为约 8–12 个因子家族评分，而不是直接塞入几十个高度相关原始变量。
