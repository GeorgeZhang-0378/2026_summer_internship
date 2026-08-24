
from pathlib import Path
import argparse, json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, balanced_accuracy_score, brier_score_loss

ROOT=Path(__file__).resolve().parent
DATA=ROOT/"data/processed"
OUT=ROOT/"results/latest_forecast"
HORIZONS=(5,20,60)

def load(m):
    return pd.read_csv(DATA/f"{m}_base.csv",parse_dates=["date"]).sort_values("date").reset_index(drop=True)

def features(df, market):
    x=df.copy()
    c=pd.to_numeric(x["close"],errors="coerce")
    o=pd.to_numeric(x["open"],errors="coerce")
    h=pd.to_numeric(x["high"],errors="coerce")
    l=pd.to_numeric(x["low"],errors="coerce")
    r=np.log(c/c.shift(1))
    feats=[]
    for w in [1,5,10,20,60,126,252]:
        k=f"ret_{w}"; x[k]=np.log(c/c.shift(w)); feats.append(k)
    for w in [20,60,252]:
        ma=c.rolling(w,min_periods=max(10,w//3)).mean()
        k=f"ma_gap_{w}"; x[k]=c/ma-1; feats.append(k)
        rv=r.rolling(w,min_periods=max(10,w//3)).std(ddof=0)*np.sqrt(252)
        k=f"rv_{w}"; x[k]=rv; feats.append(k)
        hi=c.rolling(w,min_periods=max(10,w//3)).max()
        lo=c.rolling(w,min_periods=max(10,w//3)).min()
        k=f"breakout_{w}"; x[k]=(c-lo)/(hi-lo).replace(0,np.nan)-0.5; feats.append(k)
        mu=c.rolling(w,min_periods=max(10,w//3)).mean()
        sd=c.rolling(w,min_periods=max(10,w//3)).std(ddof=0)
        k=f"z_{w}"; x[k]=(c-mu)/sd.replace(0,np.nan); feats.append(k)
    x["skew60"]=r.rolling(60,min_periods=30).skew(); feats.append("skew60")
    x["kurt60"]=r.rolling(60,min_periods=30).kurt(); feats.append("kurt60")
    x["range"]=(h-l)/c.replace(0,np.nan); feats.append("range")
    x["close_open"]=c/o.replace(0,np.nan)-1; feats.append("close_open")
    x["overnight"]=o/c.shift(1).replace(0,np.nan)-1; feats.append("overnight")

    if market=="shanghai":
        if "volume" in x:
            v=pd.to_numeric(x["volume"],errors="coerce")
            x["volume_z60"]=(np.log1p(v)-np.log1p(v).rolling(60,min_periods=20).mean())/np.log1p(v).rolling(60,min_periods=20).std(ddof=0)
            feats.append("volume_z60")
        if "open_interest" in x:
            oi=pd.to_numeric(x["open_interest"],errors="coerce")
            x["oi_chg20"]=oi/oi.shift(20)-1; feats.append("oi_chg20")
        if "settlement" in x:
            s=pd.to_numeric(x["settlement"],errors="coerce")
            x["settle_basis"]=s/c.replace(0,np.nan)-1; feats.append("settle_basis")

        lo=load("london")
        lo2,_=features(lo,"london")
        keep=["date","ret_1","ret_5","ret_20","ret_60","rv_20","ma_gap_20","breakout_60"]
        lo2=lo2[keep].copy()
        lo2["date"]=lo2["date"]+pd.Timedelta(days=1)
        ren={k:f"london_{k}" for k in keep if k!="date"}
        lo2=lo2.rename(columns=ren)
        x=pd.merge_asof(x.sort_values("date"),lo2.sort_values("date"),on="date",direction="backward")
        feats+=list(ren.values())
    return x,feats

def add_y(df,h):
    z=df.copy(); c=pd.to_numeric(z["close"],errors="coerce")
    z["fret"]=np.log(c.shift(-h)/c); z["up"]=(z["fret"]>0).astype(float)
    z.loc[z["fret"].isna(),"up"]=np.nan
    return z

def clf():
    return Pipeline([("s",StandardScaler()),("m",LogisticRegression(C=.5,solver="lbfgs",class_weight="balanced",max_iter=2000))])
def reg():
    return Pipeline([("s",StandardScaler()),("m",Ridge(alpha=10.0))])

def walkforward(df,feats,h,min_train=756,test=126,embargo=5):
    z=add_y(df,h); rows=[]; start=min_train+h+embargo
    while start<len(z)-h:
        end=min(start+test,len(z)-h); train_end=start-h-embargo
        tr=z.iloc[:train_end].dropna(subset=feats+["up","fret"])
        te=z.iloc[start:end].dropna(subset=feats+["up","fret"])
        if len(tr)>=400 and len(te)>=10 and tr["up"].nunique()==2:
            m=clf(); m.fit(tr[feats],tr["up"].astype(int))
            t=te[["date","up","fret"]].copy(); t["p"]=m.predict_proba(te[feats])[:,1]; rows.append(t)
        start+=test
    if not rows:return pd.DataFrame(),{}
    oos=pd.concat(rows,ignore_index=True); y=oos["up"].astype(int); p=oos["p"]
    return oos,{
        "n_oos":len(oos),
        "auc":float(roc_auc_score(y,p)),
        "balanced_accuracy":float(balanced_accuracy_score(y,(p>=.5).astype(int))),
        "brier":float(brier_score_loss(y,p))
    }

def latest(df,feats,h):
    z=add_y(df,h); tr=z.dropna(subset=feats+["up","fret"]); row=z.dropna(subset=feats).iloc[-1]
    mc=clf(); mr=reg(); mc.fit(tr[feats],tr["up"].astype(int)); mr.fit(tr[feats],tr["fret"])
    X=row[feats].to_frame().T; p=float(mc.predict_proba(X)[0,1]); er=float(mr.predict(X)[0])
    zs=mc.named_steps["s"].transform(X)[0]; cf=mc.named_steps["m"].coef_[0]
    contrib=pd.Series(zs*cf,index=feats).sort_values()
    sig="BULLISH" if p>=.58 else ("BEARISH" if p<=.42 else "NEUTRAL")
    return row,p,er,sig,contrib

def analogues(df,lookback=60,forward=60,top=20):
    c=pd.to_numeric(df["close"],errors="coerce").reset_index(drop=True)
    r=np.log(c/c.shift(1)).to_numpy()
    latest=r[-lookback:]; latest=(latest-np.mean(latest))/np.std(latest); target=np.cumsum(latest)
    cand=[]
    for end in range(lookback,len(df)-forward-2):
        w=r[end-lookback+1:end+1]
        if len(w)!=lookback or not np.all(np.isfinite(w)) or np.std(w)==0: continue
        q=np.cumsum((w-np.mean(w))/np.std(w))
        cand.append((float(np.sqrt(np.mean((q-target)**2))),end))
    cand.sort(); sel=[]
    for item in cand:
        if all(abs(item[1]-e)>=90 for _,e in sel): sel.append(item)
        if len(sel)>=top: break
    paths=[]; rows=[]
    for d,e in sel:
        base=c.iloc[e]; fut=c.iloc[e:e+forward+1].to_numpy(float); path=fut/base-1
        paths.append(path); rows.append([df.iloc[e]["date"],d,path[5],path[20],path[60]])
    arr=np.array(paths)
    return arr,pd.DataFrame(rows,columns=["match_end_date","distance","future_5d","future_20d","future_60d"])

def run(market):
    df,feats=features(load(market),market)
    OUT.mkdir(parents=True,exist_ok=True)
    fcs={}; vals={}
    for h in HORIZONS:
        oos,metric=walkforward(df,feats,h); vals[h]=metric
        if not oos.empty:oos.to_csv(OUT/f"{market}_oos_{h}d.csv",index=False)
        fcs[h]=latest(df,feats,h)

    arr,matches=analogues(df); matches.to_csv(OUT/f"{market}_historical_analogues.csv",index=False)
    p_ana=float(np.mean(arr[:,20]>0))
    rows=[]
    for h in HORIZONS:
        row,p,er,sig,contrib=fcs[h]
        rows.append([market,row["date"].date(),row["close"],h,p,er,sig,vals[h].get("auc"),vals[h].get("balanced_accuracy"),vals[h].get("brier")])
    summary=pd.DataFrame(rows,columns=["market","latest_date","latest_close","horizon","p_up_model","expected_log_return","signal","oos_auc","oos_balanced_accuracy","oos_brier"])
    summary.to_csv(OUT/f"{market}_forecast_summary.csv",index=False)

    row,p20,er20,sig20,contrib=fcs[20]
    same=(p20-.5)*(p_ana-.5)>=0
    conf="HIGH" if same and abs(p20-.5)+abs(p_ana-.5)>=.30 and vals[20].get("auc",0)>=.53 else ("MEDIUM" if same and abs(p20-.5)+abs(p_ana-.5)>=.16 else "LOW")

    # charts
    recent=df.tail(504)
    plt.figure(figsize=(12,7)); plt.plot(recent["date"],recent["close"]); plt.grid(alpha=.2)
    plt.title(f"{market.title()} Gold - Recent History"); plt.tight_layout(); plt.savefig(OUT/f"{market}_history.png",dpi=180); plt.close()

    probs=[fcs[5][1],fcs[20][1],fcs[60][1],p_ana]; labs=["5D model","20D model","60D model","20D analogue"]
    plt.figure(figsize=(10,6)); b=plt.bar(labs,probs); plt.axhline(.5,ls="--"); plt.axhline(.58,ls=":"); plt.axhline(.42,ls=":"); plt.ylim(0,1)
    for bb,v in zip(b,probs): plt.text(bb.get_x()+bb.get_width()/2,v+.02,f"{v:.1%}",ha="center")
    plt.title(f"{market.title()} Gold - Forecast Probabilities"); plt.tight_layout(); plt.savefig(OUT/f"{market}_probabilities.png",dpi=180); plt.close()

    x=np.arange(arr.shape[1]); last=float(row["close"])
    med=np.median(arr,axis=0); q10=np.quantile(arr,.1,axis=0); q25=np.quantile(arr,.25,axis=0); q75=np.quantile(arr,.75,axis=0); q90=np.quantile(arr,.9,axis=0)
    plt.figure(figsize=(12,7))
    for path in arr: plt.plot(x,last*(1+path),alpha=.15,lw=.8)
    plt.fill_between(x,last*(1+q10),last*(1+q90),alpha=.12,label="10-90% range")
    plt.fill_between(x,last*(1+q25),last*(1+q75),alpha=.20,label="25-75% range")
    plt.plot(x,last*(1+med),lw=2.5,label="Median analogue path"); plt.axhline(last,ls="--")
    plt.xlabel("Trading days ahead"); plt.ylabel("Analogue-implied price"); plt.legend(); plt.grid(alpha=.2)
    plt.title(f"{market.title()} Gold - Historical Analogue Forward Paths"); plt.tight_layout(); plt.savefig(OUT/f"{market}_analogue_paths.png",dpi=180); plt.close()

    sel=pd.concat([contrib.head(6),contrib.tail(6)]).sort_values()
    plt.figure(figsize=(10,7)); plt.barh(sel.index,sel.values); plt.title(f"{market.title()} Gold - 20D Feature Contributions"); plt.tight_layout()
    plt.savefig(OUT/f"{market}_feature_contributions.png",dpi=180); plt.close()

    report=f"""\
{market.upper()} GOLD FORECAST
Latest date: {row['date'].date()}
Latest close: {float(row['close']):.4f}

5D  P(up): {fcs[5][1]:.2%} | {fcs[5][3]}
20D P(up): {p20:.2%} | E[log return]: {er20:.2%} | {sig20}
60D P(up): {fcs[60][1]:.2%} | {fcs[60][3]}

Historical analogue 20D P(up): {p_ana:.2%}
Confidence: {conf}

20D OOS AUC: {vals[20].get('auc')}
20D OOS Balanced Accuracy: {vals[20].get('balanced_accuracy')}
20D OOS Brier: {vals[20].get('brier')}

The analogue fan chart is a historical distribution, not a deterministic future path.
"""
    (OUT/f"{market}_forecast_report.txt").write_text(report,encoding="utf-8")
    return {"market":market,"date":str(row["date"].date()),"p20":p20,"e20":er20,"signal":sig20,"analogue20":p_ana,"confidence":conf,"validation20":vals[20]}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--market",choices=["london","shanghai","all"],default="all"); a=ap.parse_args()
    ms=["london","shanghai"] if a.market=="all" else [a.market]
    out=[]
    for m in ms:
        r=run(m); out.append(r)
        print(f"{m.upper()} | {r['date']} | 20D P(up)={r['p20']:.2%} | analogue={r['analogue20']:.2%} | {r['signal']} | confidence={r['confidence']}")
    (OUT/"combined_latest.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
    print("Saved to",OUT)

if __name__=="__main__":
    main()
