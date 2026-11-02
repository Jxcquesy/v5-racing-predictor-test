"""V5 mobile interface. Existing frozen V5 inference remains unchanged."""
import io
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
import streamlit as st
from v5_engine import predict_v5, select_daily
from pdf_parser import extract
import bet_tracker

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'v5_top3_model.joblib'
KEY = ['RaceDate','Course','RaceTime','HorseName']
st.set_page_config(page_title='V5 Racing Predictor',page_icon='🏇',layout='centered',initial_sidebar_state='collapsed')
st.markdown('''<style>div.stButton>button{min-height:3.1rem;width:100%;border-radius:13px}div[data-testid="stMetric"]{background:rgba(128,128,128,.08);padding:12px;border-radius:12px}input{font-size:18px!important}</style>''',unsafe_allow_html=True)
st.title('🏇 V5 Racing Predictor')
page=st.radio('Navigate',['🗄️ Data & Training','🏇 AI Selections','🎟️ Betslip','📈 History'],horizontal=True,label_visibility='collapsed')

def norm(df):
    missing=[c for c in KEY if c not in df]
    if missing: raise ValueError('Missing columns: '+', '.join(missing))
    x=df.copy()
    dt=pd.to_datetime(x.RaceDate,errors='coerce',format='%d-%b-%y')
    if dt.isna().any():
        dt=pd.to_datetime(x.RaceDate,errors='coerce',dayfirst=True)
    if dt.isna().any():raise ValueError('Invalid RaceDate values')
    x['RaceDate']=dt.dt.strftime('%d-%b-%y')
    return x

def get_master():
    if 'master_bytes' not in st.session_state:
        for p in (ROOT/'RFB_Master_Runners.csv',ROOT/'master.csv'):
            if p.exists():st.session_state.master_bytes=p.read_bytes();break
    if 'master_bytes' not in st.session_state:return None
    return norm(pd.read_csv(io.BytesIO(st.session_state.master_bytes),low_memory=False))

def make_keys(df):
    return pd.MultiIndex.from_arrays([
        pd.to_datetime(df.RaceDate,format='%d-%b-%y').dt.strftime('%Y-%m-%d'),
        df.Course.astype(str).str.strip().str.casefold(),
        df.RaceTime.astype(str).str.strip(),
        df.HorseName.astype(str).str.strip().str.casefold()])

if page=='🗄️ Data & Training':
    st.header('Master database')
    master_upload=st.file_uploader('Load your V5 Master CSV',type='csv',key='master_upload')
    if master_upload and st.button('Use this master CSV'):
        try:
            x=norm(pd.read_csv(io.BytesIO(master_upload.getvalue()),low_memory=False))
            st.session_state.master_bytes=x.to_csv(index=False).encode()
            st.success(f'Loaded {len(x):,} historical runners')
        except Exception as e:st.error(str(e))
    master=get_master()
    if master is None:
        st.info('Upload your master once per app session. Permanent database storage is not yet configured.')
    else:
        dt=pd.to_datetime(master.RaceDate,format='%d-%b-%y')
        a,b=st.columns(2);a.metric('Runners',f'{len(master):,}');b.metric('Recorded dates',dt.nunique())
        st.caption(f'Coverage: {dt.min():%d %b %Y} to {dt.max():%d %b %Y}')
        st.subheader('Find missing dates')
        start=st.date_input('From',value=dt.min().date());end=st.date_input('To',value=date.today()-timedelta(days=1))
        if st.button('🔎 Find missing dates'):
            if start>end:st.error('Start must be before end')
            else:
                recorded=set(dt.dt.date)
                missing=[d.date().isoformat() for d in pd.date_range(start,end) if d.date() not in recorded]
                st.session_state.missing_dates=missing
        if 'missing_dates' in st.session_state:
            st.write(f'{len(st.session_state.missing_dates)} dates not recorded (may include cancelled/no-racing days)')
            st.dataframe(pd.DataFrame({'Date':st.session_state.missing_dates}),hide_index=True)
        st.subheader('Import verified results')
        incoming_file=st.file_uploader('Results CSV in MASTER format',type='csv',key='incoming')
        if incoming_file:
            try:
                incoming=norm(pd.read_csv(io.BytesIO(incoming_file.getvalue()),low_memory=False))
                missing_cols=[c for c in master.columns if c not in incoming]
                if missing_cols:st.error('Missing master fields: '+', '.join(missing_cols))
                else:
                    incoming=incoming.reindex(columns=master.columns)
                    existing=make_keys(master);newkeys=make_keys(incoming)
                    new=incoming.loc[~newkeys.isin(existing)&~newkeys.duplicated()].copy()
                    st.metric('New runner records',len(new))
                    st.caption('Review new records carefully: matching keys do not prove a race is complete.')
                    if len(new):
                        st.dataframe(new[KEY].head(30),hide_index=True)
                        confirm=st.checkbox('I have verified these results and want to merge them')
                        if st.button('Merge verified records',disabled=not confirm):
                            merged=pd.concat([master,new],ignore_index=True)
                            st.session_state.master_backup=st.session_state.master_bytes
                            st.session_state.master_bytes=merged.to_csv(index=False).encode()
                            st.success(f'Merged {len(new)} runners into the session master')
                            st.rerun()
            except Exception as e:st.error(f'Import rejected: {e}')
        st.download_button('⬇️ Download current Master CSV',st.session_state.master_bytes,'V5_Master_UPDATED.csv',mime='text/csv')
        if 'master_backup' in st.session_state:st.download_button('Download previous backup',st.session_state.master_backup,'V5_Master_BACKUP.csv')
    st.divider()
    st.subheader('Retrain V5 AI')
    st.button('🧠 Retrain AI model',disabled=True)
    st.warning('Not enabled yet: this repository contains V5 inference and a trained model, but no validated training pipeline. The current V5 model is protected.')
    st.info('Automatic fetching and permanent master storage are also pending. Streamlit Community Cloud local/session storage is not permanent.')

elif page=='🏇 AI Selections':
    st.header('Today’s AI picks')
    master=get_master()
    if master is None:st.warning('Load your master CSV on the Data page first.');st.stop()
    race_day=st.date_input('Race date',value=date.today(),key='race_day')
    pdfs=st.file_uploader('Upload racecard PDFs',type='pdf',accept_multiple_files=True,key='pdfs')
    runner_csv=st.file_uploader('Or upload corrected racecard CSV',type='csv',key='runners')
    runners=None
    if runner_csv:runners=pd.read_csv(io.BytesIO(runner_csv.getvalue()))
    elif pdfs:
        try:
            runners,issues=extract(pdfs,race_day)
            for issue in issues:st.warning(issue)
        except Exception as e:st.error(f'Racecard parsing failed: {e}')
    if runners is not None and not runners.empty:
        for col in ('Jockey','Trainer','Distance'):
            if col not in runners:runners[col]=''
        with st.expander('Verify racecard runners',expanded=True):
            runners=st.data_editor(runners,num_rows='dynamic',hide_index=True,key='verified_runners')
        checked=st.checkbox('I checked racecards, non-runners, going, classes and distances')
        if st.button('Generate V5 AI selections',disabled=not checked,type='primary'):
            try:
                preds=predict_v5(st.session_state.master_bytes,runners,MODEL.read_bytes(),race_day)
                picks=select_daily(preds).copy()
                picks['_sort']=pd.to_datetime(picks.Time.astype(str),format='%H:%M',errors='coerce')
                picks=picks.sort_values(['_sort','Course','Horse'],kind='stable').drop(columns='_sort').reset_index(drop=True)
                st.session_state.picks=picks.to_dict('records')
                st.session_state.pick_day=str(race_day)
                st.session_state.pick_index=0
                st.success(f'{len(picks)} AI selections generated')
            except Exception as e:st.error(f'V5 prediction failed: {e}')
    picks=st.session_state.get('picks',[])
    if picks:
        i=min(st.session_state.get('pick_index',0),len(picks)-1)
        p=picks[i];identifier=f"{st.session_state.pick_day}|{p['Course']}|{p['Time']}|{p['Horse']}"
        st.progress((i+1)/len(picks),text=f'AI pick {i+1} of {len(picks)}')
        st.subheader(str(p['Horse']))
        st.write(f"🕒 **{p['Time']}** · **{p['Course']}** · Top 3")
        prob=float(p['Top 3 Probability']);recommended=1.05/prob if prob>0 else float('inf')
        c1,c2=st.columns(2);c1.metric('Top 3 chance',f'{prob:.1%}');c2.metric('Minimum target odds',f'{recommended:.2f}')
        odds=st.number_input('Bet365 Top 3 decimal odds',min_value=1.01,max_value=1001.0,value=float(st.session_state.get('entered_odds',{}).get(identifier,2.0)),step=.01,key='odds_'+identifier)
        if st.button('➕ Add to Betslip & Next',type='primary'):
            slip=st.session_state.setdefault('slip',{})
            slip[identifier]={'horse':str(p['Horse']),'course':str(p['Course']),'time':str(p['Time']),'probability':prob,'min_odds':recommended,'odds':float(odds),'race_date':st.session_state.pick_day}
            st.session_state.pick_index=min(i+1,len(picks)-1);st.rerun()
        prev,nextcol=st.columns(2)
        if prev.button('← Previous',disabled=i==0):st.session_state.pick_index=i-1;st.rerun()
        if nextcol.button('Skip / Next →',disabled=i==len(picks)-1):st.session_state.pick_index=i+1;st.rerun()
        with st.expander('View all AI selections'):
            st.dataframe(pd.DataFrame(picks)[['Time','Course','Horse','Top 3 Probability']],hide_index=True)
        st.caption(f"{len(st.session_state.get('slip',{}))} selections in your betslip")
    else:st.info('Generate predictions to see only the horses V5 selects, in race-time order.')

elif page=='🎟️ Betslip':
    st.header('My Betslip')
    slip=st.session_state.get('slip',{})
    if not slip:st.info('Add horses from AI Selections first.');st.stop()
    for key,leg in list(slip.items()):
        a,b=st.columns([4,1]);a.write(f"**{leg['horse']}** · {leg['course']} {leg['time']} · Top 3 @ {leg['odds']:.2f}")
        if b.button('✕',key='remove_'+key):del slip[key];st.rerun()
    combined=1.0
    for leg in slip.values():combined*=leg['odds']
    units=st.number_input('Stake in units',min_value=0.01,value=1.0,step=.25)
    unit_value=st.number_input('£ per unit',min_value=.01,value=.40,step=.05)
    a,b=st.columns(2);a.metric('Combined odds',f'{combined:.2f}');b.metric('Potential return',f'{combined*units:.2f}u')
    st.caption(f'Potential profit {(combined-1)*units:.2f}u · £{combined*units*unit_value:.2f} total return')
    if st.button('Save bet to history',type='primary'):
        if not bet_tracker.login():st.stop()
        legs=[{k:v for k,v in leg.items() if k!='race_date'} for leg in slip.values()]
        days={leg['race_date'] for leg in slip.values()}
        if len(days)!=1:st.error('Save separate slips for different race dates.')
        else:
            try:
                bet_tracker.request('POST',payload={'race_date':days.pop(),'legs':legs,'combined_odds':round(combined,6),'stake_units':float(units),'result':'Pending'})
                st.session_state.slip={};st.success('Saved to Supabase history')
            except Exception as e:st.error(f'Could not save: {e}')

else:
    st.header('Bet history & profit')
    if not bet_tracker.login():st.stop()
    try:rows=bet_tracker.request('GET',params={'select':'*','order':'created_at.desc','limit':'1000'})
    except Exception as e:st.error(f'Could not read history: {e}');st.stop()
    pnl=0.0
    for r in rows:
        stake=float(r['stake_units']);result=r['result']
        if result=='Won':pnl+=(float(r['combined_odds'])-1)*stake
        elif result=='Lost':pnl-=stake
    a,b=st.columns(2);a.metric('Net profit',f'{pnl:+.2f}u');b.metric('Recorded bets',len(rows))
    for r in rows:
        with st.expander(f"{r['race_date']} · {len(r['legs'])} legs · {r['result']}"):
            for leg in r['legs']:st.write(f"{leg['horse']} · {leg['time']} · {leg['odds']}")
            st.write(f"Stake {r['stake_units']}u · Combined odds {r['combined_odds']}")
            options=['Pending','Won','Lost','Void']
            current=r['result'] if r['result'] in options else 'Pending'
            status=st.selectbox('Result',options,index=options.index(current),key='status_'+str(r['id']))
            if st.button('Save result',key='update_'+str(r['id']),disabled=status==r['result']):
                try:bet_tracker.request('PATCH',payload={'result':status},params={'id':'eq.'+str(r['id'])});st.rerun()
                except Exception as e:st.error(str(e))
    st.warning('Per-leg non-runner repricing and manual return adjustments are not implemented yet. Do not mark an adjusted accumulator Won until settlement handling is added.')
