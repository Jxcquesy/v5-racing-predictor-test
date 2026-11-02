"""Frozen V4 inference, adapted from the owner's Colab notebook. No training."""
import io
import joblib
import numpy as np
import pandas as pd

REQUIRED = ['Horse','Course','Time','Final_Race_Type','Final_Going','RFB_Age','RFB_WeightLBS','RFB_OR','Final_Class']

def predict(history_bytes, runner_df, model_bytes, race_date):
    r = runner_df.copy()
    missing = set(REQUIRED)-set(r.columns)
    if missing: raise ValueError(f'Missing runner columns: {sorted(missing)}')
    if r[['Horse','Course','Time']].isna().any().any(): raise ValueError('Missing horse/course/time')
    if r.duplicated(['Course','Time','Horse']).any(): raise ValueError('Duplicate runner keys: course, time, horse')
    RACE_DATE = pd.Timestamp(race_date)
    r['race_date'] = RACE_DATE
    r['class_num'] = pd.to_numeric(r['Final_Class'].astype('string').str.extract(r'([1-7])')[0], errors='coerce')
    for c in ['RFB_Age','RFB_WeightLBS','RFB_OR']: r[c]=pd.to_numeric(r[c],errors='coerce')
    h0=pd.read_csv(io.BytesIO(history_bytes),low_memory=False)
    h=pd.DataFrame({
      'race_date':pd.to_datetime(h0['RaceDate'],dayfirst=True,errors='coerce'),
      'Horse':h0['HorseName'],'Course':h0['Course'],'Time':h0['RaceTime'],
      'Final_Race_Type':h0['Type'].astype('string').str.lower().map({'f':'Flat','a':'Flat','h':'Hurdle','c':'Chase','b':'NH Flat','n':'NH Flat'}).fillna(h0['Type']),
      'Final_Going':h0['Going'],'RFB_Age':pd.to_numeric(h0['Age'],errors='coerce'),
      'RFB_WeightLBS':pd.to_numeric(h0['WeightLBS'],errors='coerce'),
      'RFB_OR':pd.to_numeric(h0['OR'],errors='coerce'),
      'class_num':pd.to_numeric(h0['Class'],errors='coerce'),
      'position_num':pd.to_numeric(h0['FPos'],errors='coerce'),
      'past_field_size':pd.to_numeric(h0['Ran'],errors='coerce')})
    h=h[h.race_date.notna() & (h.race_date<RACE_DATE)].copy()
    h['past_finish_fraction']=np.where((h.past_field_size>1)&h.position_num.between(1,h.past_field_size),(h.past_field_size-h.position_num)/(h.past_field_size-1),np.nan)
    r['position_num']=np.nan;r['past_field_size']=np.nan;r['past_finish_fraction']=np.nan
    cols=['race_date','Horse','Course','Time','Final_Race_Type','Final_Going','RFB_Age','RFB_WeightLBS','RFB_OR','class_num','position_num','past_field_size','past_finish_fraction']
    d=pd.concat([h[cols],r[cols]],ignore_index=True)
    d['horse_key']=d['Horse'].astype('string').str.strip().str.lower().str.replace(r'\s*\((?:ire|gb|fr|usa|ger|aus|nz)\)\s*$','',regex=True)
    d=d.sort_values(['horse_key','race_date','Course','Time'],kind='stable').reset_index(drop=True)
    base=['position_num','past_finish_fraction','class_num','RFB_WeightLBS','RFB_OR','past_field_size']
    hist=d.groupby(['horse_key','race_date'],sort=False,dropna=True)[base].first().reset_index().sort_values(['horse_key','race_date'])
    g=hist.groupby('horse_key',sort=False)
    for c in base:hist['prior_'+c]=g[c].shift(1)
    for k in (3,5,10):
      for c in ('past_finish_fraction','position_num'):
        lag=hist.groupby('horse_key',sort=False)[c].shift(1)
        hist[f'last{k}_{c}_avg']=lag.groupby(hist['horse_key'],sort=False).rolling(k,min_periods=1).mean().reset_index(level=0,drop=True)
      lag=hist['position_num'].le(3).where(hist['position_num'].notna()).groupby(hist['horse_key'],sort=False).shift(1).astype(float)
      hist[f'last{k}_top3_rate']=lag.groupby(hist['horse_key'],sort=False).rolling(k,min_periods=1).mean().reset_index(level=0,drop=True)
    hist['prior_race_count']=hist.groupby('horse_key').cumcount()
    lag_class=hist.groupby('horse_key')['class_num'].shift(1)
    hist['prior3_best_class_num']=lag_class.groupby(hist['horse_key']).rolling(3,min_periods=3).min().reset_index(level=0,drop=True)
    feature_cols=[c for c in hist if c.startswith(('prior_', 'prior3_', 'last'))]
    d=d.merge(hist[['horse_key','race_date']+feature_cols],on=['horse_key','race_date'],how='left',validate='many_to_one')
    d['class_drop_vs_last']=d['prior_class_num']-d['class_num']
    d['weight_change_lbs']=d['RFB_WeightLBS']-d['prior_RFB_WeightLBS']
    d['or_change']=d['RFB_OR']-d['prior_RFB_OR']
    today=d[d.race_date.eq(RACE_DATE)].copy()
    assert len(today)==len(r)
    pack=joblib.load(io.BytesIO(model_bytes))  # only load the owner's trusted model file
    features=pack['numeric']+pack['categorical']
    if not set(features).issubset(today.columns):raise ValueError(f'Missing frozen features: {set(features)-set(today.columns)}')
    for c in pack['numeric']:today[c]=pd.to_numeric(today[c],errors='coerce')
    raw=np.column_stack([pack['models'][k].predict_proba(today[features])[:,1] for k in (2,3,4)])
    prob=np.maximum.accumulate(raw,axis=1)
    out=today[['race_date','Course','Time','Horse','Final_Race_Type','Final_Going','class_num','prior_race_count']].copy()
    for i,k in enumerate((2,3,4)):out[f'prob_top{k}']=prob[:,i]
    out['rank_in_race']=out.groupby(['Course','Time'])['prob_top3'].rank(ascending=False,method='first').astype(int)
    return out.sort_values(['Course','Time','rank_in_race']).reset_index(drop=True)
