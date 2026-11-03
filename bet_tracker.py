"""Persistent V5 bet builder. Supabase REST credentials stay in Streamlit secrets."""
import json
from datetime import datetime, timezone
from decimal import Decimal
import pandas as pd
import requests
import streamlit as st

TABLE = 'v5_bets'

def config():
    try:
        url = str(st.secrets['SUPABASE_URL']).rstrip('/')
        key = str(st.secrets['SUPABASE_SERVICE_ROLE_KEY'])
        if not url.startswith('https://') or not key or not password:
            return None
        return url, key, password
    except (KeyError, FileNotFoundError):
        return None

def request(method, path='', payload=None, params=None):
    cfg=config()
    if not cfg: raise ValueError('Supabase secrets are not configured')
    url,key,_=cfg
    headers={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json','Prefer':'return=representation'}
    resp=requests.request(method,f'{url}/rest/v1/{TABLE}{path}',headers=headers,json=payload,params=params,timeout=20)
    resp.raise_for_status()
    return resp.json() if resp.content else []

def login():
    cfg=config()
    if not cfg:
        st.warning('Permanent tracking is not configured yet. Follow SETUP_SUPABASE.md in the update ZIP.')
        return False
    if not st.session_state.get('tracker_authorized'):
        with st.form('tracker_login'):
            pw=st.text_input('Private tracker password',type='password')
            if st.form_submit_button('Unlock betting history'):
                import hmac
                if hmac.compare_digest(pw,cfg[2]):
                    st.session_state['tracker_authorized']=True
                    st.rerun()
                else: st.error('Incorrect password')
        return False
    if st.button('Lock betting history',key='lock_tracker'):
        st.session_state['tracker_authorized']=False
        st.rerun()
    return True

def show(picks, day):
    st.subheader('Top 10 — odds & accumulator builder')
    st.caption('Minimum recommended odds = 1.05 ÷ model Top 3 probability (5% theoretical expected ROI). Estimates depend on probability calibration.')
    if not login():
        # Still show probabilities and fair odds without exposing private data.
        df=picks[['Horse','Course','Time','Top 3 Probability']].copy()
        df['Top 3 %']=(df.pop('Top 3 Probability')*100).round(1)
        df['Minimum recommended odds']=(1.05/(df['Top 3 %']/100)).round(2)
        st.dataframe(df,hide_index=True,use_container_width=True)
        return
    df=picks[['Horse','Course','Time','Top 3 Probability']].copy().reset_index(drop=True)
    df['Top 3 %']=(df.pop('Top 3 Probability')*100).round(1)
    df['Minimum recommended odds']=(1.05/(df['Top 3 %']/100)).round(2)
    df['Bet365 Top 3 odds']=[None]*len(df)
    df['Add to bet']=[False]*len(df)
    editor_key='bet_editor_'+str(day)
    edited=st.data_editor(df,hide_index=True,use_container_width=True,key=editor_key,
        disabled=['Horse','Course','Time','Top 3 %','Minimum recommended odds'],
        column_config={
            'Bet365 Top 3 odds':st.column_config.NumberColumn(min_value=1.01,step=0.01,format='%.2f'),
            'Add to bet':st.column_config.CheckboxColumn(),
            'Minimum recommended odds':st.column_config.NumberColumn(format='%.2f'),
        })
    chosen=edited[edited['Add to bet']==True].copy()
    valid=True
    for _,r in chosen.iterrows():
        o=r['Bet365 Top 3 odds']
        if pd.isna(o) or float(o)<=1:
            valid=False
            break
    combined=1.0
    if valid:
        for o in chosen['Bet365 Top 3 odds']: combined*=float(o)
    st.subheader('Your accumulator')
    if chosen.empty: st.info('Tick horses in the table to build a bet.')
    else:
        for _,r in chosen.iterrows():
            price='Enter odds' if pd.isna(r['Bet365 Top 3 odds']) else f"{float(r['Bet365 Top 3 odds']):.2f}"
            status='Value ✓' if not pd.isna(r['Bet365 Top 3 odds']) and float(r['Bet365 Top 3 odds'])>=float(r['Minimum recommended odds']) else 'Below target / no odds'
            st.write(f"**{r['Horse']}** — {price} · {status}")
        if valid: st.metric('Combined decimal odds',f'{combined:.2f}')
        else: st.warning('Enter valid decimal odds for every selected horse before saving.')
    units=st.number_input('Stake (units)',min_value=0.01,value=1.0,step=0.25,key='stake_units')
    if st.button('Save this bet permanently',disabled=chosen.empty or not valid,type='primary'):
        legs=[{'horse':str(r['Horse']),'course':str(r['Course']),'time':str(r['Time']),
               'probability':float(r['Top 3 %'])/100,'min_odds':float(r['Minimum recommended odds']),
               'odds':float(r['Bet365 Top 3 odds'])} for _,r in chosen.iterrows()]
        payload={'race_date':str(day),'legs':legs,'combined_odds':round(combined,6),'stake_units':float(units),'result':'Pending'}
        try:
            request('POST',payload=payload)
            st.success('Bet saved to permanent history.')
        except Exception as exc:st.error(f'Could not save bet: {exc}')
    st.divider()
    st.subheader('Permanent bet history & units')
    try:
        rows=request('GET',params={'select':'*','order':'created_at.desc','limit':'1000'})
    except Exception as exc:
        st.error(f'Could not load history: {exc}')
        return
    won=sum(1 for r in rows if r['result']=='Won')
    lost=sum(1 for r in rows if r['result']=='Lost')
    pending=sum(1 for r in rows if r['result']=='Pending')
    pnl=sum((float(r['combined_odds'])-1)*float(r['stake_units']) if r['result']=='Won' else -float(r['stake_units']) if r['result']=='Lost' else 0 for r in rows)
    a,b,c,d=st.columns(4)
    a.metric('Net units',f'{pnl:+.2f}u')
    b.metric('Won',won)
    c.metric('Lost',lost)
    d.metric('Pending',pending)
    for r in rows:
        horses=', '.join(leg['horse'] for leg in r['legs'])
        title=f"{r['race_date']} · {len(r['legs'])}-fold · {float(r['combined_odds']):.2f} · {r['result']}"
        with st.expander(title):
            st.write(horses)
            st.caption(f"Stake: {float(r['stake_units']):g}u · P/L: " +
                       (f"{(float(r['combined_odds'])-1)*float(r['stake_units']):+.2f}u" if r['result']=='Won' else f"{-float(r['stake_units']):+.2f}u" if r['result']=='Lost' else 'Pending'))
            new=st.selectbox('Set result',['Pending','Won','Lost','Void'],index=['Pending','Won','Lost','Void'].index(r['result']),key='result_'+str(r['id']))
            if st.button('Update result',key='save_result_'+str(r['id']),disabled=new==r['result']):
                try:
                    request('PATCH',payload={'result':new},params={'id':'eq.'+str(r['id'])})
                    st.rerun()
                except Exception as exc:st.error(f'Update failed: {exc}')
    if rows:
        export=pd.DataFrame([{'date':r['race_date'],'horses':', '.join(l['horse'] for l in r['legs']),
                              'odds':r['combined_odds'],'stake_units':r['stake_units'],'result':r['result']} for r in rows])
        st.download_button('Export bet history CSV',export.to_csv(index=False).encode(),'V5_bet_history.csv','text/csv')
    st.caption('Void bets count as zero profit/loss. Pending bets do not affect units. Odds and stake are frozen when saved. No bets are placed automatically.')
