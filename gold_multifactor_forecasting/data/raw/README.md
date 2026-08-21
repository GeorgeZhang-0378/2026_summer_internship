# Local raw data / 本地原始数据

These files are supplied by the user and appear to be exported from Wind.  
这些文件由用户提供，看起来来自 Wind 导出。

They are included in the downloadable local project package for convenience but are excluded by `.gitignore` by default.  
为了方便，它们包含在当前下载包中，但 `.gitignore` 默认排除这些文件。

This is intentional because licensed market data may not be redistributable in a public GitHub repository.  
这是刻意设计，因为受许可约束的市场数据未必允许上传到公开 GitHub 仓库。

## Shanghai
- file: `shanghai_gold_AU_SHF.xlsx`
- code: `AU.SHF`
- observations: 4518
- range: 2008-01-09 to 2026-08-12
- useful native fields: OHLC, settlement, turnover, volume, open interest
- interpretation: SHFE gold futures, RMB/g

## London
- file: `london_gold_spot.xlsx`
- code: `SPTAUUSDOZ.IDC`
- observations: 13902
- range: 1920-01-30 to 2026-08-03
- useful native fields: OHLC
- raw turnover and volume columns are zero throughout
- interpretation: London spot gold, USD/oz despite the raw header containing `元`
