"""V4 Racing dashboard: safe historical coverage and import utility."""
import io
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title='V5 Racing Predictor', page_icon='🏇', layout='wide')
st.title('🏇 V5 Racing Predictor')
st.caption('Historical coverage • Safe results imports • Frozen V4 predictions')

DEFAULT_EXCEPTIONS = {
    '2025-12-23': ('No racing', 'Confirmed by owner'),
    '2025-12-24': ('No racing', 'Confirmed by owner'),
    '2025-12-25': ('No racing', 'Confirmed by owner'),
    '2026-01-05': ('Cancelled', 'Confirmed by owner'),
}
KEY = ['RaceDate', 'Course', 'RaceTime', 'HorseName']

@st.cache_data(show_spinner=False)
def read_csv_bytes(data: bytes):
    return pd.read_csv(io.BytesIO(data), low_memory=False)

def normalize(df):
    out = df.copy()
    for col in KEY:
        if col not in out:
            raise ValueError(f'Missing required column: {col}')
    dt = pd.to_datetime(out['RaceDate'], dayfirst=True, errors='coerce')
    if dt.isna().any():
        raise ValueError(f'{dt.isna().sum():,} rows have an invalid RaceDate')
    out['RaceDate'] = dt.dt.strftime('%d-%b-%y')
    return out

def keys(df):
    return pd.MultiIndex.from_frame(pd.DataFrame({
        'RaceDate': pd.to_datetime(df.RaceDate, format='%d-%b-%y').dt.strftime('%Y-%m-%d'),
        'Course': df.Course.astype('string').str.strip().str.casefold(),
        'RaceTime': df.RaceTime.astype('string').str.strip(),
        'HorseName': df.HorseName.astype('string').str.strip().str.casefold()
    }))

with st.sidebar:
    st.header('Master database')
    master_file = st.file_uploader('Upload master runners CSV', type='csv', key='master')
    st.info('Files are processed in your session. Download the updated CSV to keep it; this starter app does not silently overwrite your original.')

if not master_file:
    st.info('Upload your RFB_Master_Runners CSV in the sidebar to begin.')
    st.stop()

try:
    master = normalize(read_csv_bytes(master_file.getvalue()))
except Exception as e:
    st.error(f'Unable to read master: {e}')
    st.stop()

dates = pd.to_datetime(master.RaceDate, format='%d-%b-%y')
left, right = dates.min().date(), dates.max().date()
tab1, tab2, tab3, tab4 = st.tabs(['📅 Coverage checker', '➕ Import results', '🏁 Racecards & V4', '🚀 V5 Top 3 Live'])

with tab1:
    st.subheader('Historical coverage')
    c1,c2,c3 = st.columns(3)
    c1.metric('Runners', f'{len(master):,}')
    c2.metric('Recorded dates', f'{dates.nunique():,}')
    c3.metric('Recorded races', f'{master[KEY[:3]].drop_duplicates().shape[0]:,}')
    start = st.date_input('Start date', left, min_value=date(2000,1,1), max_value=date(2100,1,1))
    end = st.date_input('End date', max(right, date.today()-timedelta(days=1)), min_value=date(2000,1,1), max_value=date(2100,1,1))
    if start > end:
        st.error('Start must be on or before end.')
    else:
        recorded = set(dates.dt.date)
        all_dates = pd.date_range(start,end,freq='D').date
        records=[]
        for day in all_dates:
            iso=day.isoformat()
            if day in recorded:
                status='Recorded — completeness unverified'; note='Check against an external meeting schedule to verify every race'
            elif iso in DEFAULT_EXCEPTIONS:
                status,note=DEFAULT_EXCEPTIONS[iso]
            else:
                status='Missing / needs investigation'; note='Could be no racing, cancelled, or missing results'
            records.append({'Date':iso,'Status':status,'Notes':note})
        coverage=pd.DataFrame(records)
        unresolved=coverage.Status.eq('Missing / needs investigation').sum()
        st.metric('Dates requiring investigation', int(unresolved))
        only_missing=st.checkbox('Show only dates requiring investigation', value=True)
        st.dataframe(coverage[coverage.Status.eq('Missing / needs investigation')] if only_missing else coverage, hide_index=True, use_container_width=True)
        st.download_button('Download coverage report',coverage.to_csv(index=False).encode(),'V4_coverage_report.csv','text/csv')
        st.warning('A recorded date is not necessarily complete. Verifying missing meetings/races requires a trusted schedule or results feed.')

with tab2:
    st.subheader('Import completed results safely')
    st.write('Upload a results CSV using the same column structure as your master. We check date + course + race time + horse before adding any rows.')
    uploaded=st.file_uploader('New results CSV',type='csv',key='results')
    if uploaded:
        try:
            incoming=normalize(read_csv_bytes(uploaded.getvalue()))
            missing_cols=[c for c in master.columns if c not in incoming.columns]
            if missing_cols:
                st.error('Results file lacks master columns: '+', '.join(missing_cols))
            else:
                incoming=incoming.reindex(columns=master.columns)
                existing_keys=keys(master)
                incoming_keys=keys(incoming)
                new_mask=~incoming_keys.isin(existing_keys)
                duplicates_inside=incoming_keys.duplicated(keep='first')
                add=incoming.loc[new_mask & ~duplicates_inside]
                a,b,c=st.columns(3)
                a.metric('Rows in import',f'{len(incoming):,}')
                b.metric('Already present / repeated',f'{len(incoming)-len(add):,}')
                c.metric('New rows',f'{len(add):,}')
                if len(add):
                    st.dataframe(add[KEY].head(50),hide_index=True,use_container_width=True)
                    st.download_button('Download backup of original master',master.to_csv(index=False).encode(), 'V4_master_backup.csv','text/csv')
                    if st.checkbox('I have checked the new rows and want an updated download'):
                        merged=pd.concat([master,add],ignore_index=True)
                        st.download_button('Download updated master CSV',merged.to_csv(index=False).encode(),'RFB_Master_Runners_UPDATED.csv','text/csv',type='primary')
                else:
                    st.success('No new runner records found.')
        except Exception as e:
            st.error(f'Import could not be validated: {e}')

with tab3:
    st.subheader('Prepare upcoming racecards')
    pdfs=st.file_uploader('Upload At The Races meeting PDFs',type='pdf',accept_multiple_files=True)
    if pdfs:
        st.success(f'{len(pdfs)} PDF(s) received: '+', '.join(x.name for x in pdfs))
    from pdf_parser import extract
    from v4_engine import predict
    st.write('Upload your trusted frozen model, master history and racecards. PDF extraction is best-effort; check the runner table carefully.')
    model_file=st.file_uploader('Frozen V4 model (.joblib)',type='joblib',key='model')
    race_day=st.date_input('Race date for predictions',value=date.today()+timedelta(days=1),key='race_day')
    runner_csv=st.file_uploader('Alternatively, upload a checked combined runners CSV',type='csv',key='runners')
    runners=None
    if runner_csv:
        runners=pd.read_csv(io.BytesIO(runner_csv.getvalue()))
    elif pdfs:
        try:
            runners,issues=extract(pdfs,race_day)
            for issue in issues:st.warning(issue)
        except Exception as exc:st.error(f'PDF extraction failed: {exc}')
    if runners is not None and not runners.empty:
        st.write(f'Extracted {len(runners):,} runners in {runners.groupby(["Course","Time"]).ngroups} races.')
        st.warning('PDF extraction is not guaranteed complete. Check horse names, runner counts, race type, going, class and ratings. Blank going/class affects prediction reliability.')
        st.download_button('Download extracted runner CSV for correction',runners.to_csv(index=False).encode(),'V4_extracted_runners.csv','text/csv')
        runners=st.data_editor(runners,num_rows='dynamic',hide_index=True,use_container_width=True,key='runners_edit')
        blank_going=runners['Final_Going'].isna().sum()+runners['Final_Going'].astype(str).str.strip().eq('').sum()
        blank_type=runners['Final_Race_Type'].isna().sum()+runners['Final_Race_Type'].astype(str).str.strip().eq('').sum()
        blank_class=runners['Final_Class'].isna().sum()+runners['Final_Class'].astype(str).str.strip().eq('').sum()
        st.caption(f'Empty going: {blank_going} · Empty race type: {blank_type} · Empty class: {blank_class}')
        verified=st.checkbox('I have checked the runner list and accept any missing data',value=False)
        if st.button('🏇 Generate Top 10 with frozen V4',type='primary',disabled=not(model_file and verified)):
            with st.spinner('Calculating historical form and frozen V4 probabilities...'):
                try:
                    predictions=predict(master_file.getvalue(),runners,model_file.getvalue(),race_day)
                    st.session_state['v4_predictions']=predictions
                    st.session_state['v4_prediction_day']=str(race_day)
                except Exception as exc:st.error(f'Prediction failed: {exc}')
    if 'v4_predictions' in st.session_state:
        preds=st.session_state['v4_predictions']
        st.subheader('Top 10 horses')
        target=st.selectbox('Rank by',['Top 3','Top 2','Top 4'])
        col='prob_top'+target[-1]
        top=preds.nlargest(10,col).copy()
        for k in (2,3,4):top[f'Top {k} %']=(top[f'prob_top{k}']*100).round(1)
        st.dataframe(top[['Horse','Course','Time','Top 2 %','Top 3 %','Top 4 %','prior_race_count']],hide_index=True,use_container_width=True)
        st.caption('Model estimates, not guarantees. Check for runners omitted or wrongly parsed from PDFs.')
        st.download_button('Download all V4 predictions',preds.to_csv(index=False).encode(),f'V4_predictions_{st.session_state["v4_prediction_day"]}.csv','text/csv')

with tab4:
    st.subheader('V5 — frozen Top 3 model')
    st.caption('Same pre-September-2026 model used in the historical audit. Racecards and results require manual uploads; this is not an automatic live odds/results feed.')
    from v5_engine import predict_v5,select_daily
    v5day=st.date_input('V5 race date',value=date.today(),key='v5day')
    v5pdfs=st.file_uploader('At The Races PDFs',type='pdf',accept_multiple_files=True,key='v5pdf')
    v5csv=st.file_uploader('Or corrected combined runners CSV',type='csv',key='v5csv')
    v5r=None
    if v5csv:
        v5r=pd.read_csv(io.BytesIO(v5csv.getvalue()))
    elif v5pdfs:
        try:
            v5r,issues=extract(v5pdfs,v5day) if 'extract' in globals() else __import__('pdf_parser').extract(v5pdfs,v5day)
            for issue in issues:st.warning(issue)
        except Exception as e:st.error(f'PDF parsing error: {e}')
    if v5r is not None and not v5r.empty:
        st.warning('Verify EVERY race and runner before prediction. In particular: going, class, type, distance, jockey, trainer and non-runners. PDF parsing is best-effort.')
        for col in ('Jockey','Trainer','Distance'):
            if col not in v5r:v5r[col]=''
        with st.expander('🔍 PDF extraction diagnostics', expanded=True):
            st.write('Parser module:', getattr(__import__('pdf_parser'), '__file__', 'unknown'))
            st.write('Columns returned:', ', '.join(map(str, v5r.columns)))
            for field in ('Jockey', 'Trainer', 'Final_Going'):
                if field in v5r.columns:
                    count = int(v5r[field].fillna('').astype(str).str.strip().ne('').sum())
                    st.write(f'{field}: {count}/{len(v5r)} populated')
                else:
                    st.write(f'{field}: column missing')
            preview_cols = [c for c in ('Horse', 'Course', 'Time', 'Jockey', 'Trainer', 'Final_Going') if c in v5r.columns]
            st.dataframe(v5r[preview_cols].head(15), hide_index=True, use_container_width=True)
        v5r=st.data_editor(v5r,num_rows='dynamic',hide_index=True,use_container_width=True,key='v5edit')
        st.download_button('Download corrected V5 racecard',v5r.to_csv(index=False).encode(),f'V5_racecard_{v5day}.csv','text/csv')
        nbad=v5r.groupby(['Course','Time']).Horse.transform('size').lt(6).sum()
        st.caption(f'{len(v5r):,} entered runners · {nbad:,} runners in races with fewer than six entries (excluded)')
        checked=st.checkbox('I have checked runners, withdrawals, race types, distances and other inputs',key='v5checked')
        if st.button('Generate frozen V5 Top 3 rankings',disabled=not checked,type='primary',key='v5run'):
            try:
                with st.spinner('Building historical features and predicting...'):
                    model_bytes=(Path(__file__).parent/'v5_top3_model.joblib').read_bytes()
                    results=predict_v5(master_file.getvalue(),v5r,model_bytes,v5day)
                    st.session_state['v5results']=results
                    st.session_state['v5date']=str(v5day)
            except Exception as e:st.error(f'V5 could not run: {e}')
    if 'v5results' in st.session_state:
        preds=st.session_state['v5results']
        picks=select_daily(preds)
        from bet_tracker import show as show_bet_builder
        show_bet_builder(picks,st.session_state['v5date'])
        st.download_button('Download all V5 predictions',preds.to_csv(index=False).encode(),f'V5_predictions_{st.session_state["v5date"]}.csv','text/csv')
        st.subheader('Manual treble results tracker')
        treble = picks.head(3)
        result_key='v5track_'+st.session_state['v5date']
        states=[]
        for i,(_,leg) in enumerate(treble.iterrows(),1):
            status=st.selectbox(f'{leg.Horse} ({leg.Course} {leg.Time})', ['Pending','1st','2nd','3rd','Unplaced','Non-runner'],key=result_key+str(i))
            states.append(status)
        if states:
            good={'1st','2nd','3rd'}
            wins=sum(s in good for s in states)
            losses=sum(s=='Unplaced' for s in states)
            st.progress(wins/len(states))
            if losses:st.error('Treble lost — at least one leg unplaced')
            elif 'Non-runner' in states:st.warning('Non-runner: settlement depends on the bookmaker; verify revised bet terms')
            elif wins==len(states):st.success('All three legs placed')
            else:st.info(f'{wins}/{len(states)} placed; {states.count("Pending")} pending')
        st.caption('Tracker inputs are session-only. Download predictions to preserve your record. No automatic betting, result settlement or profit calculation is implied.')
