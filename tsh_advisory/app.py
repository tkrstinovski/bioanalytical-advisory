"""Run with python -m streamlit run tsh_advisory/app.py from the project root."""
import os,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import streamlit as st
import pandas as pd
import altair as alt
import importlib
import tsh_advisory as package
# Streamlit reruns app.py but can retain imported calculation/view modules after edits.
# Reload the dependency chain when local source changes, preserving process credentials.
_modules=['schemas','store','manuals','design','names','cost_policy','study_preparation','planning','calculations','research_scope','agents','selection','comparison','kit_library','evidence_details','issue_checks','findings','policy','workflow','tables','review_views','candidate_grid','estimate_basis','client_package','reports']
_modules.append('cost_grid')
_modules.append('supporting_documents')
_modules.append('document_extraction')
_modules.append('intake_updates')
_signature=tuple((Path(__file__).parent/(name+'.py')).stat().st_mtime_ns for name in _modules)
if getattr(package,'_source_signature',None)!=_signature:
    for _name in _modules:
        _module=sys.modules.get('tsh_advisory.'+_name)
        if _module is not None:importlib.reload(_module)
    package._source_signature=_signature
from tsh_advisory.store import Store,digest
from tsh_advisory.schemas import Intake,tsh_case
from tsh_advisory.workflow import Engine
from tsh_advisory.policy import SECTIONS,POSITIVE,NEGATIVE,packet_hash,record_decision,scientific_complete,current_decisions,selected_review_gaps,planning_review_gaps
from tsh_advisory.reports import html_report,pdf_report,evidence_zip,public_lead_time
from tsh_advisory.agents import ROLES,HUMAN_ROLES,api_error_details
from tsh_advisory.review_views import protocol_view,candidate_details
from tsh_advisory.tables import readable_table
from tsh_advisory.planning import plate_rows
from tsh_advisory.findings import blocking_findings,scoped_findings
from tsh_advisory.comparison import manual_reference,concise_concerns,instrument_match,comparison_sources,recommendation_reasons,comparison_rows
from tsh_advisory.candidate_grid import grid_rows,collect_updates,render_grid
from tsh_advisory.kit_library import display_kit

ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title='Bioanalytical Advisory',page_icon='🧬',layout='wide')
from tsh_advisory import sandbox
PUBLIC_DEMO=sandbox.enabled()
if PUBLIC_DEMO:
    @st.cache_resource
    def demo_cleanup_worker():
        sandbox.cleanup()
        sandbox.start_janitor()
        return True
    demo_cleanup_worker()
    token=st.session_state.get('_demo_session')
    if token and not sandbox.session_path(token).exists():
        st.session_state.clear()
        token=None
    if not token:
        token=sandbox.create_session()
        st.session_state['_demo_session']=token
    DATA=sandbox.session_path(token)
    sandbox.touch(token)
    @st.fragment(run_every=60)
    def demo_heartbeat():
        sandbox.touch(st.session_state['_demo_session'])
    demo_heartbeat()
    st.info('Public synthetic sandbox · your edits are private to this browser session · no API key or paid research · reset anytime. Closing the tab abandons your session; inactive data is removed after one hour while the server is running, or on its next start.')
    if st.button('End demo / Reset',key='_reset_demo'):
        sandbox.remove_session(token)
        st.session_state.clear()
        st.rerun()
else:
    DATA=Path(os.getenv('BIO_ADVISORY_DATA',str(ROOT/'runs')))
store=Store(DATA)
if PUBLIC_DEMO and not store.cases() and not store.deleted_cases():
    demo_case=tsh_case().model_dump()
    demo_case.update(title='Synthetic demonstration — editable session copy',scientific_reviewer='Demo Scientist',director='Demo Director',instruments={},field_status={'kit_price':'Agents to research','sample_handling':'Agents to research','validation_conditions':'Agents to research'})
    demo_cid=store.save_case(demo_case)
    demo_engine=Engine(store)
    try:
        demo_engine.start(demo_cid,'fixture',{'manual_demo':True,'planning_version':'lot-planning-v3'})
    finally:
        demo_engine.close()
    st.session_state['case_id']=demo_cid

def engine_action(fn):
    engine=Engine(store)
    try: return fn(engine)
    finally: engine.close()

def nullable_number(label,value,min_value=0.0,step=1.0):
    return st.number_input(label,min_value=min_value,value=float(value) if value is not None else None,step=step)

def intake_view(cid):
    saved=store.case(cid); original=Intake.model_validate(saved['data']); d=original.model_dump()
    st.subheader('Project intake')
    st.caption('Save an incomplete draft. Agents research missing evidence; reviewers resolve scientific decisions. Validation volume is calculated, not entered here.')
    d['title']=st.text_input('Project title',d['title'])
    a,b=st.columns(2)
    with a:
        d['analyte']=st.text_input('Analyte',d['analyte'])
        d['species']=st.text_input('Species',d['species'])
        d['matrix']=st.text_input('Matrix',d['matrix'])
    with b:
        uses=['Detect treatment-related changes versus controls','Preclinical safety assessment','Pharmacodynamic response','Dose-response assessment','Exploratory biomarker assessment','Disease progression monitoring','Method development and validation planning']
        uses=list(dict.fromkeys(uses+([d['intended_use']] if d['intended_use'] else [])))
        d['intended_use']=st.selectbox('Intended use',uses,index=uses.index(d['intended_use']) if d['intended_use'] in uses else 0)
        d['deadline']=st.text_input('Target date',d['deadline'])
        d['regulatory_use']=st.selectbox('Regulatory reliance',['Reviewer decision required','Internal preclinical decision','Human-drug development regulatory support','Veterinary use requires separate applicability review'],index=['Reviewer decision required','Internal preclinical decision','Human-drug development regulatory support','Veterinary use requires separate applicability review'].index(d['regulatory_use']))
    with st.expander('Instruments and configurations',expanded=True):
        families=list(dict.fromkeys(['SpectraMax','Bio-Plex','MSD']+list(d['instruments'])))
        chosen=st.multiselect('Available instrument platforms (select all that apply)',families,default=[k for k,v in d['instruments'].items() if v],accept_new_options=True)
        d['instruments']={family:st.text_input(f'{family} exact model (required)',d['instruments'].get(family,'')) for family in chosen}
        st.caption('Listed platforms/models are your available instruments. Agents list the kit manual/vendor requirements separately; the scientist confirms suitability at approval. Automatic name/model matching does not block approval.')
        if any(not model.strip() for model in d['instruments'].values()):st.warning('Enter an exact model for each selected platform before starting a new run. Drafts can still be saved.')
    with st.expander('Study sample availability',expanded=True):
        a,b,c=st.columns(3)
        with a:
            d['available_ul']=nullable_number('Available study volume (µL)',d['available_ul'],min_value=.01)
            d['volume_basis']=st.text_input('Allocation basis',d['volume_basis'].replace('animal','lot'))
        with b:
            d['initial_wells']=st.number_input('Initial wells per sample',min_value=1,value=d['initial_wells'])
            d['complete_repeats']=st.number_input('Complete repeats to reserve',min_value=0,max_value=3,value=d['complete_repeats'])
        with c:
            v=nullable_number('Study sample count (optional)',d['study_count'],min_value=1.0)
            d['study_count']=int(v) if v is not None else None
        st.caption('Available volume must cover initial wells, the repeat reserve and handling losses. This value is specific to this intake.')
    with st.expander('Validation design requirements',expanded=True):
        d['lot_count']=st.number_input('Distinct pooled lots',min_value=1,max_value=20,value=d['lot_count'])
        st.markdown('#### Plate control layouts')
        for title,fields in [
            ('Precision and Accuracy plates',[('pa_blank_wells','Blank wells'),('pa_standard_levels','Standard levels'),('pa_standard_replicates','Wells per standard level'),('qc_levels','QC levels'),('qc_wells_per_level','Wells per QC level')]),
            ('Non-Precision and Accuracy plates',[('nonpa_blank_wells','Blank wells'),('nonpa_standard_levels','Standard levels'),('nonpa_standard_replicates','Wells per standard level'),('nonpa_qc_levels','QC levels'),('nonpa_qc_replicates','Wells per QC level')])]:
            st.markdown('**'+title+'**')
            columns=st.columns(3)
            for i,(key,caption) in enumerate(fields):
                with columns[i%3]:d[key]=st.number_input(title+' · '+caption,min_value=0 if 'blank' in key else 1,value=d[key],key='control_'+key)
        pa_total=d['pa_blank_wells']+d['pa_standard_levels']*d['pa_standard_replicates']+d['qc_levels']*d['qc_wells_per_level']
        d['assay_control_wells_per_run']=d['nonpa_blank_wells']+d['nonpa_standard_levels']*d['nonpa_standard_replicates']+d['nonpa_qc_levels']*d['nonpa_qc_replicates']
        st.write(f"P/A control wells per plate: {pa_total}. Non-P/A control wells per plate: {d['assay_control_wells_per_run']}.")
        st.caption('Non-P/A starting values preserve the previous 24-well allowance; edit the component counts to match the selected kit.')
        d['preparation_leeway_ul']=st.number_input('Extra prepared volume per dilution/condition (µL)',min_value=10,max_value=20,value=d['preparation_leeway_ul'])
        d['include_tqc_eqc']=st.checkbox('Include optional tQC/EQC (same design as Day 0)',value=d['include_tqc_eqc'])
        st.info(f'Precision and Accuracy: {d["precision_accuracy_plates"]} initial plates, {pa_total} control wells per plate. Each P/A plate hosts at most one additional parameter. Each parameter has its own repeat plate allocation. Long-term assessments remain separate.')
        for key,label in [('day0_wells_per_lot','Day 0 wells per lot'),('stability_wells_per_lot','Stability wells per lot per condition'),('parallel_wells_per_dilution','Parallelism wells per lot per dilution'),('freeze_wells_per_endpoint','Freeze–thaw wells per lot per endpoint')]:
            d[key]=st.number_input(label,min_value=1,value=d[key])
        st.markdown('#### Short-term stability')
        options=['4 °C · 4 hours','4 °C · 24 hours','Room temperature · 4 hours','Room temperature · 24 hours','Room temperature · 48 hours','4 °C · 48 hours']
        options=list(dict.fromkeys(options+d['short_term_conditions']))
        d['short_term_conditions']=st.multiselect('Short-term stability conditions (select all that apply)',options,default=d['short_term_conditions'],accept_new_options=True)
        st.caption('Choose multiple conditions using the dropdown checkmarks, or type a custom temperature and duration. Each selection is a separate assessment condition.')
        st.markdown('#### Long-term stability')
        d['long_term_assessments']=st.number_input('Number of long-term stability assessments',min_value=0,max_value=100,value=d['long_term_assessments'])
        d['long_term_material_type']='lots'
        storage=['−80 °C','−20 °C','2–8 °C','Room temperature']
        d['long_term_storage_conditions']=st.multiselect('Long-term storage conditions (select all that apply)',list(dict.fromkeys(storage+d.get('long_term_storage_conditions',[]))),default=d.get('long_term_storage_conditions',[]),accept_new_options=True)
        st.caption('Each assessment at EACH selected storage condition: 3 lots × 3 wells = 9 initial wells plus one complete repeat. Three assessments at two temperatures means six separate assessments. Set assessments to 0 to omit.')
        st.markdown('#### Freeze–thaw')
        d['freeze_thaw_cycles']=st.number_input('Number of freeze–thaw cycles to test',min_value=3,max_value=20,value=d['freeze_thaw_cycles'])
        st.caption('Each cycle endpoint is tested using separate aliquots. All endpoints are assayed after planned cycling is complete.')
        st.markdown('#### Parallelism dilution series')
        d['parallel_dilution_count']=st.number_input('Number of parallelism dilutions',min_value=1,max_value=20,value=d['parallel_dilution_count'])
        st.caption('Set starting dilution and serial factor in Agent workspace → Volumes after selecting a kit.')
        st.markdown('#### Additional validation parameters (optional)')
        st.caption('Add a row for each extra parameter. Separate conditions with semicolons. Each condition uses the specified wells per lot and the configured complete repeat. Check separate plates when conditions must be assayed separately; scientist confirms timing compatibility. Volumes use the lowest parallelism dilution and the same preparation/handling allowances.')
        custom_rows=[{'Parameter':x['name'],'Conditions / assessments':'; '.join(x['conditions']),'Lots':x['lot_count'],'Wells per lot per condition':x['wells_per_lot_per_condition'],'Separate plates per condition':x['separate_conditions']} for x in d.get('additional_parameters',[])]
        custom=st.data_editor(pd.DataFrame(custom_rows,columns=['Parameter','Conditions / assessments','Lots','Wells per lot per condition','Separate plates per condition']),num_rows='dynamic',hide_index=True,key='custom_parameters_'+cid,column_config={'Lots':st.column_config.NumberColumn(min_value=1,max_value=20,default=3,step=1),'Wells per lot per condition':st.column_config.NumberColumn(min_value=1,default=3,step=1),'Separate plates per condition':st.column_config.CheckboxColumn(default=False)},width='stretch')
        d['additional_parameters']=[]
        for row in custom.to_dict('records'):
            if pd.isna(row['Parameter']) or not str(row['Parameter']).strip():continue
            conditions=row['Conditions / assessments']
            d['additional_parameters'].append({'name':str(row['Parameter']).strip(),'conditions':str(conditions).split(';') if pd.notna(conditions) and str(conditions).strip() else ['1 assessment'],'lot_count':int(row['Lots']) if pd.notna(row['Lots']) else 3,'wells_per_lot_per_condition':int(row['Wells per lot per condition']) if pd.notna(row['Wells per lot per condition']) else 3,'separate_conditions':bool(row['Separate plates per condition']) if pd.notna(row['Separate plates per condition']) else False})
        st.caption('New runs use the corrected planning engine; existing saved revisions remain unchanged.')
        st.info('Agents use these design settings to calculate validation volume per parameter and material unit. Validation material volume is not an intake field.')
    with st.expander('People and costing'):
        d['scientific_reviewer']=st.text_input('Scientific reviewer and business cost approver',d['scientific_reviewer'])
        d['director']=st.text_input('Separate manager or director',d['director'])
        d['labor_rate']=st.number_input('Labor rate (USD/hour)',min_value=.01,value=float(d['labor_rate']))
        d['budget_ceiling']=nullable_number('Optional project budget ceiling (USD)',d['budget_ceiling'],min_value=.01)
        d['budget_basis']=st.selectbox('Ceiling basis',['internal_cost','client_price'],index=['internal_cost','client_price'].index(d['budget_basis']))
        st.caption('Shipping, instrument rates, overhead, contingency and pooled material pricing are researched/proposed for approval. Blank ceiling means no project ceiling.')
    with st.expander('Unresolved fields and comments'):
        st.caption('Expected study concentrations may remain unknown and do not block planning approval. The kit’s documented curve range is still shown in comparison and reports.')
        for field in ['sample_handling','kit_price','validation_conditions']:
            statuses=['Agents to research','Reviewer decision required','Supplied','Confirmed','Not applicable']
            old=d['field_status'].get(field,statuses[0])
            d['field_status'][field]=st.selectbox(field.replace('_',' ').title(),statuses,index=statuses.index(old))
        d['notes']=st.text_area('Additional context',d['notes'])
    try:
        clean=Intake.model_validate(d).model_dump()
        changed=digest(clean)!=digest(original.model_dump())
        if changed:
            store.save_case(clean,cid,expected=saved['version'])
            st.success('Draft autosaved. Existing run approvals remain tied to the previous intake version.')
        else: st.caption(f'Draft saved · version {saved["version"]}')
        if st.button('Save draft now'): st.success('Draft saved.')
    except ValueError as exc: st.error(str(exc))

def settings_view():
    st.subheader('Live agent settings')
    st.caption('Credentials stay in this process environment; never in a report, project file or run log. Role identities in this classroom build are self-attested.')
    key=st.text_input('OpenAI API key (optional if already in environment)',type='password',key='api_key_input')
    if key: os.environ['OPENAI_API_KEY']=key
    st.write('API credential configured:',bool(os.getenv('OPENAI_API_KEY')))
    saved={}
    path=DATA/'settings.json'
    if path.exists(): saved=json.loads(path.read_text())
    with st.form('settings'):
        model=st.text_input('Accessible OpenAI model ID',saved.get('model',os.getenv('OPENAI_MODEL','')))
        rate_date=st.text_input('Rate card date and source URL',saved.get('rate_date',''))
        a,b,c=st.columns(3)
        rates=saved.get('rates',{})
        with a: inp=nullable_number('Input USD per million tokens',rates.get('input'),step=.1)
        with b: cached=nullable_number('Cached input USD per million tokens',rates.get('cached'),step=.1)
        with c: out=nullable_number('Output USD per million tokens',rates.get('output'),step=.1)
        if st.form_submit_button('Save provider settings'):
            path.write_text(json.dumps({'model':model,'rate_date':rate_date,'rates':dict(input=inp,cached=cached,output=out)}),encoding='utf-8')
            st.success('Non-secret settings saved.')
    st.info('Live calls require an accessible model and dated rates. Hard inference cap: $10/run; 40 model calls. Fixture mode uses no model or search calls.')
    if st.button('Test OpenAI connection and model access'):
        try:
            from openai import OpenAI
            if not os.getenv('OPENAI_API_KEY'):raise ValueError('Enter the API key locally first.')
            if not model.strip():raise ValueError('Enter a model ID first.')
            OpenAI(timeout=15,max_retries=0).models.retrieve(model)
            st.success('Connected to OpenAI; the configured model is visible to this API project. No model generation was requested.')
        except ValueError as exc:st.error(str(exc))
        except Exception as exc:st.error(api_error_details(exc)['message'])

def volume_charts(p,rid):
    selected=next((k for k in p.get('candidates',[]) if k['id']==p.get('selected_kit')),None)
    if selected:
        st.write('Kit used for calculations:',selected['name']+' / '+selected['catalog'])
        if not p.get('calculation_selection'):st.info('Provisional kit calculation. Confirm your kit in Candidate comparison → Scientist kit selection and pricing.')
    if p.get('volume',{}).get('calculation_version')!='lot-planning-v3':st.warning('Historical calculation rules are shown. Apply settings or create a corrected planning revision to use the unified study dilution, rounded preparation and complete run ledger. Prior revisions and approvals remain in history.')
    st.markdown('#### Parallelism and dilution settings')
    case=p.get('case',{})
    minimum=selected.get('dilution_factor') if selected else None
    follow_minimum=st.checkbox('Start parallelism at the selected kit’s recorded minimum dilution',value=bool(minimum is not None and case.get('parallel_start_from_kit',True)),disabled=minimum is None,key='parallel_kit_min_'+rid+'_'+str(p.get('planning_revision',1)))
    if minimum is not None:st.caption(f"Selected kit recorded minimum: 1:{minimum:g}. Confirm its basis in Candidate comparison; uncheck to use a scientist-selected starting dilution.")
    else:st.info('The kit minimum dilution is not recorded. Enter it in Candidate comparison or use a scientist-selected starting dilution; no minimum is inferred from the curve range.')
    with st.form('volume_settings_'+rid):
        st.write('Number of dilutions: '+str(case.get('parallel_dilution_count','Not set'))+' (configured in intake)')
        a,b=st.columns(2)
        with a:start=st.number_input('Starting dilution denominator (1:x)',min_value=1.0,max_value=1000000.0,value=float(minimum if follow_minimum else case.get('parallel_start_dilution',1)),disabled=follow_minimum)
        with b:factor=st.number_input('Serial dilution factor',min_value=1.01,max_value=100.0,value=float(case.get('parallel_serial_factor',2)),step=.5)
        follow=st.checkbox('Study analysis uses lowest tested parallelism dilution',value=case.get('study_dilution') is None)
        study_dilution=None
        study_reason=''
        if not follow:
            study_dilution=st.number_input('Study analysis dilution denominator (1:x)',min_value=1.0,value=float(case.get('study_dilution') or case.get('parallel_start_dilution',1)))
            study_reason=st.text_input('Reason for separate study dilution',case.get('study_dilution_override_reason',''))
        actor=st.text_input('Scientific reviewer name',case.get('scientific_reviewer',''))
        if st.form_submit_button('Apply dilution settings'):
            try:
                engine_action(lambda e:e.configure_review(rid,actor,start=start,factor=factor,use_kit_minimum=follow_minimum,study_settings={'dilution':study_dilution,'reason':study_reason}))
                st.rerun()
            except Exception as exc:st.error(str(exc))
    st.caption('All other validation parameters use the lowest dilution in this series. Pipetting-loss reserves are included in each preparation. Save settings to update an existing packet.')
    v=p.get('volume',{})
    if v.get('rows'):
        for row in v['rows']:
            if row.get('parallelism_calculation'):
                st.markdown('#### Parallelism volume calculation')
                st.caption(f"Preparation table: per lot per independent run. Parameter totals include {row.get('independent_runs',1)} independent run(s) and the configured complete repeats.")
                st.write('Prepare enough at each dilution for its own assay wells and the transfer needed by the next dilution. Only the first dilution pulls from neat serum; all later steps pull from the previous dilution. Withdrawals round upward to whole microlitres, with diluent adjusted to preserve the dilution ratio.')
                raw=pd.DataFrame(row['parallelism_calculation'])
                raw['Neat matrix µL']=[step['source_or_previous_dilution_ul'] if i==0 else 0 for i,step in enumerate(row['parallelism_calculation'])]
                fields=['dilution','source','Neat matrix µL','source_or_previous_dilution_ul','diluent_ul','total_to_prepare_ul','transfer_to_next_ul','retained_after_transfer_ul','prepared_for_wells_ul','wells_per_lot']
                table=raw[[c for c in fields if c in raw.columns]].rename(columns={'dilution':'Dilution','source':'Pull from','wells_per_lot':'Wells per lot','prepared_for_wells_ul':'Volume needed to plate µL','transfer_to_next_ul':'Transfer to next dilution µL','total_to_prepare_ul':'Total prepared µL','source_or_previous_dilution_ul':'Withdraw whole µL','diluent_ul':'Diluent µL','retained_after_transfer_ul':'Retained for plating µL'})
                readable_table(table,hide_index=True,width='stretch')
    st.markdown('#### Study sample feasibility')
    s=p.get('study',{})
    st.write('Study analysis dilution:', '1:'+str(s.get('dilution_factor','Not resolved')), '·',s.get('dilution_basis','Historical kit record'))
    if s.get('status') in ('pass','fail'):
        a,b,c=st.columns(3)
        a.metric('Available per study sample',f'{s["available_ul"]:g} µL')
        b.metric('Initial + repeat + handling',f'{s["total_ul"]:g} µL')
        c.metric('Remaining / shortfall',f'{s["remaining_ul"]:g} µL')
        (st.success if s['status']=='pass' else st.error)('Volume fits the study allocation.' if s['status']=='pass' else 'Required volume exceeds the study allocation.')
    else: st.warning(s.get('reason','Study volume unresolved.'))
    study=p.get('study',{})
    if study.get('preparation'):
        st.markdown('#### Practical study-sample preparation')
        st.caption('Per sample, per initial set. Reserve the same independently prepared setup for each complete repeat. Nonzero source/diluent transfers are at least 10 µL; dilution suitability remains a scientist decision.')
        readable_table([{'Dilution':r['dilution'],'Pull from':r['source'],'Source µL':r['source_ul'],'Diluent µL':r['diluent_ul'],'Prepare µL':r['prepared_ul'],'Transfer next µL':r['transfer_next_ul'],'Retain µL':r['retained_ul'],'Plate µL':r['plate_ul'],'Pipetting reserve µL':r['reserve_ul']} for r in study['preparation']])
        st.write(f"Matrix per sample: {study['initial_ul']:g} µL initial + {study['repeat_ul']:g} µL repeat reserve + {study['handling_ul']:g} µL handling = {study['total_ul']:g} µL. Neat-equivalent arithmetic alone: {study['theoretical_neat_ul_per_set']:g} µL per set.")
        final=study['preparation'][-1]
        required=final['plate_ul']+final['reserve_ul']
        st.success(f"Final dilution has {final['retained_ul']:g} µL available: {final['plate_ul']:g} µL for {case.get('initial_wells',2)} wells + {final['reserve_ul']:g} µL pipetting-loss reserve + {final['retained_ul']-required:g} µL extra. The repeat preparation is reserved separately.")
    st.markdown('#### Calculated validation material requirements')
    v=p.get('volume',{})
    if v.get('rows'):
        df=pd.DataFrame(v['rows'])
        df['parameter']=df['parameter'].replace({'Precision and accuracy / calibration and QC':'Precision and Accuracy'})
        columns=[name for name in ['parameter','material_count','material_type','initial_wells','repeat_wells','initial_ul_per_lot','repeat_ul_per_lot','losses_ul_per_lot','total_ul_per_lot'] if name in df.columns]
        labels={'parameter':'Parameter','material_count':'Lots','material_type':'Material','initial_wells':'Initial wells','repeat_wells':'Repeat wells','initial_ul_per_lot':'Initial µL per lot','repeat_ul_per_lot':'Repeat µL per lot','losses_ul_per_lot':'Losses µL per lot','total_ul_per_lot':'Total µL per lot','total_ul_all_lots':'Total µL across lots','kits':'Kits'}
        shown=df[columns].astype(object).copy()
        for index,row in enumerate(v['rows']):
            if row.get('material_type')=='Kit stock':
                for field in ['material_count','initial_wells','repeat_wells','initial_ul_per_lot','repeat_ul_per_lot','losses_ul_per_lot','total_ul_per_lot']:
                    if field in shown.columns:shown.loc[index,field]='—'
        labels.update(material_count='Lots (not kit stock)',initial_ul_per_lot='Initial matrix µL per lot',repeat_ul_per_lot='Repeat matrix µL per lot',losses_ul_per_lot='Handling matrix µL per lot',total_ul_per_lot='Total matrix µL per lot')
        readable_table(shown.fillna('Not applicable').astype(str).rename(columns=labels),hide_index=True,width='stretch')
        st.caption('P/A kit stock is included in the kits and adds no separate material quantity or cost. Parameter matrix volumes include preparation reserves and handling losses.')
        st.markdown('#### Kit purchase requirements')
        initial=v.get('initial_kits');repeat=v.get('repeat_kits')
        a,b,c=st.columns(3)
        a.metric('Initial kits',initial if initial is not None else 'Unresolved')
        b.metric('Repeat kits',repeat if repeat is not None else 'Unresolved')
        c.metric('Total kits',v.get('kits') if v.get('kits') is not None else 'Unresolved')
        st.caption('Each initial P/A plate combines with at most one parameter. Each parameter has dedicated repeat plates; initial testing is never allocated to repeat plates. Long-term assessments remain separate.')
        if v.get('plate_allocations'):
            st.markdown('#### Shared plate allocation')
            readable_table(plate_rows(v),hide_index=True,width='stretch')
        a,b=st.columns(2);a.metric('Required per pooled lot',f'{v["total_ul_per_lot"]:g} µL');b.metric('Total validation material',f'{v["total_ul_all_lots"]:g} µL')
        if v.get('lot_requirements'):
            readable_table([{'Lot':r['lot'],'Parameters including repeats/reserves (µL)':r['parameter_requirement_ul'],'Aliquoting allowance (µL)':r['aliquotting_loss_ul'],'Total required (µL)':r['total_required_ul']} for r in v['lot_requirements']])
        st.caption('The study volume limit does not apply to validation pooled lots. Scientist to confirm the proposed sample preparation and dilution plan.')

def selection_review_tables(p,kit,rid):
    from tsh_advisory.selection import selection_factors
    from tsh_advisory.evidence_details import core_fact_assessment,cell_evidence_detail,CORE_FACTS
    facts=core_fact_assessment(p,kit);linked=sum(r['Included in supported count'] for r in facts)
    factors=selection_factors(p,kit)
    for row in factors:
        if row['Selection factor']=='Evidence support':row['Current assessment']=f'{linked}/6 core facts have current linked source passages; coverage is detailed below.'
    readable_table(factors)
    st.markdown('#### Core kit facts · source coverage')
    shown=[]
    for row,(field,label) in zip(facts,CORE_FACTS):
        value=row['Current value']
        if field=='dilution_factor' and value is not None:value=f'1:{value:g}'
        if field=='well_input_ul' and value is not None:value=f'{value:g} µL'
        shown.append({'Core fact':label,'Saved value':value if value is not None and value!='' else 'Not recorded','Evidence status':row['Evidence status']})
    readable_table(shown)
    with st.expander('Inspect a core fact and its supporting passage'):
        field=st.selectbox('Core fact',list(CORE_FACTS),format_func=lambda entry:entry[1],key='core_fact_'+rid+kit['id'])[0]
        detail=cell_evidence_detail(p,kit,field)
        st.write('Information basis:',detail['basis'])
        if detail['quote']:
            st.write('Location:',detail['locator']);st.text(detail['quote'])
        else:st.caption('No passage is linked to this field. Add or review evidence using Cell evidence and selection basis below.')
        if detail['url'].startswith(('https://','http://')):st.link_button('Open source document',detail['url'])
        if detail['reviewer']:st.caption('Reviewed by '+detail['reviewer']+' · '+detail['reviewed_at'])


def candidate_view(p,rid):
    all_candidates=[display_kit(k) for k in p.get('candidates',[])];finalists=p.get('finalist_ids',[])
    candidates=[k for k in all_candidates if k['id'] in finalists] if finalists else all_candidates
    st.subheader('Candidate comparison')
    if not candidates:st.info('No candidates yet.');return
    with st.expander('Retained kit manuals · download, upload or check for updates'):
        from tsh_advisory import manuals
        manual_kit=st.selectbox('Kit manual to manage',all_candidates,index=next((i for i,k in enumerate(all_candidates) if k['id']==p.get('selected_kit')),0),format_func=lambda k:k['catalog']+' / '+k['name'],key='manual_kit_'+rid)
        retained=manual_kit.get('retained_manual',{})
        if retained:
            readable_table([{'Version':retained.get('version'),'Version basis':retained.get('version_basis'),'Source URL':retained.get('source_url'),'Retrieved':retained.get('retrieved_at'),'File SHA-256':retained.get('sha256'),'Pages':retained.get('pages')}])
            try:
                saved=manuals.attachment(store,manual_kit,retained)
                st.download_button('Download retained manual',saved['bytes'],file_name=saved['metadata']['filename'],mime='application/pdf',key='manual_saved_'+rid+manual_kit['id'])
            except Exception as exc:st.error(str(exc))
        else:st.caption('No PDF pinned to this kit in this run yet. Save from its direct PDF link or upload a searchable PDF.')
        manual_url=st.text_input('Manual source URL',manual_reference(p,manual_kit)[0] or '',key='manual_url_'+rid+manual_kit['id'])
        manual_version=st.text_input('Document version/revision (optional)',key='manual_version_'+rid+manual_kit['id'])
        uploaded=st.file_uploader('Upload manual PDF if vendor download is unavailable',type=['pdf'],key='manual_upload_'+rid+manual_kit['id'])
        st.caption('The run pins its saved PDF version. New versions preserve previous evidence and require renewed review. Saving a PDF does not automatically re-extract or verify kit facts; agents reuse retained text when research resumes. Source and page citations remain required.')
        save_manual=st.button('Save manual from link or upload',key='manual_save_'+rid)
        check_manual=st.button('Check for updated manual at source',key='manual_check_'+rid)
        if save_manual or check_manual:
            try:
                if not manual_url.startswith(('https://','http://')):raise ValueError('Enter the vendor manual source URL.')
                changed=engine_action(lambda e:e.retain_kit_manual(rid,p['case']['scientific_reviewer'],manual_kit['id'],manual_url,raw=uploaded.getvalue() if uploaded and not check_manual else None,version=manual_version,refresh=check_manual))
                if changed:st.rerun()
                else:st.success('The source returned the same manual version. No planning revision or model call was needed.')
            except Exception as exc:st.error(str(exc))
    recommended=next((k for k in all_candidates if k['id']==p.get('recommended_kit')),None)
    if recommended:
        st.markdown('**Current recommended kit:** '+recommended['name']+' · '+recommended['catalog'])
        from tsh_advisory.selection import selection_factors
        refresh=p.get('recommendation_refresh',{})
        st.info('Current saved facts support this rule-based planning recommendation; scientist confirmation remains required.' if refresh.get('status')=='clear_rule_based_choice' else 'Provisional recommendation: ties or missing information prevent a clear overall choice.')
        selection_review_tables(p,recommended,rid)
        st.caption('Six selection factors and trade-offs. Refreshed from saved information without a new model run. The original model recommendation remains in the audit; the scientist’s selected kit is unchanged.')
    else:
        st.info('Recommendation pending: current facts do not establish one supported choice. Review the contender kits and select a kit for scientific review.')
        selected_for_review=next((k for k in all_candidates if k['id']==p.get('selected_kit')),None)
        if selected_for_review:
            from tsh_advisory.selection import selection_factors
            selection_review_tables(p,selected_for_review,rid)
    baseline=grid_rows(p,candidates,public_lead_time)
    st.caption('Double-click a kit fact to edit it. Blue bold text and “Reviewer edited” mark saved corrections; “Unsaved” marks pending changes. Derived calculations and evidence summaries are read-only. Hover over an edited cell to see its original value and editor. Press Tab to finish a cell edit, then save below.')
    edited=render_grid(baseline,candidates,'primary_candidate_grid_v2_'+rid+'_'+str(p.get('planning_revision',1)))
    with st.popover('Cell evidence and selection basis',width='stretch'):
        from tsh_advisory.candidate_grid import FIELDS
        from tsh_advisory.evidence_details import cell_evidence_detail
        from tsh_advisory.selection import selection_analysis
        detail_kit=st.selectbox('Kit for evidence details',candidates,format_func=lambda k:k['catalog'],key='evidence_kit_'+rid)
        criterion=st.selectbox('Comparison cell',list(FIELDS),key='evidence_field_'+rid)
        field=FIELDS[criterion];detail=cell_evidence_detail(p,detail_kit,field)
        st.write('Current value:',detail['value']);st.write('Information basis:',detail['basis'])
        if detail['url'].startswith(('https://','http://')):st.link_button('Supporting document',detail['url'])
        if detail['locator']:st.write('Supporting location:',detail['locator'])
        if detail['quote']:st.text(detail['quote'])
        st.caption('Reviewer: '+(detail['reviewer'] or 'Not recorded')+' · Last changed/reviewed: '+(detail['reviewed_at'] or 'Not recorded'))
        with st.form('cell_evidence_'+rid+'_'+detail_kit['id']+'_'+field):
            evidence_actor=st.text_input('Reviewer linking evidence',p['case']['scientific_reviewer'])
            source_id=st.selectbox('Retained source (blank = reviewer assertion)',[None]+list(p.get('sources',{})),index=([None]+list(p.get('sources',{}))).index(detail['source_id']) if detail['source_id'] in p.get('sources',{}) else 0,format_func=lambda sid:'Reviewer assertion / estimate' if sid is None else sid+' · '+p['sources'][sid]['url'])
            source_url=st.text_input('New public source URL (optional; retrieves and retains document without a model call)',value='')
            locator=st.text_input('Page / section',detail['locator'])
            quote=st.text_area('Exact supporting passage (maximum 400 characters)',detail['quote'],max_chars=400)
            notes=st.text_area('Assertion basis / review notes',detail['notes'])
            verified=st.checkbox('I verified that the passage or assertion supports this displayed value.')
            identity=st.checkbox('For species/analyte: this passage also identifies kit catalog, target and supported species.') if field in ('species','analyte') else False
            if st.form_submit_button('Save cell evidence'):
                try:
                    if not verified:raise ValueError('Confirm your review of this cell value.')
                    engine_action(lambda e:e.configure_review(rid,evidence_actor,evidence_update={'kit_id':detail_kit['id'],'field':field,'entry':{'source_id':source_id,'source_url':source_url,'locator':locator,'quote':quote,'notes':notes,'supports_identity':identity}}));st.rerun()
                except Exception as exc:st.error(str(exc))
        analysis=selection_analysis(p,detail_kit)
        st.markdown('**Selection trade-offs**')
        for text in analysis['tradeoffs']:st.write('• '+text)
        st.markdown('**Decision rubric (no numerical score)**')
        for label,importance,basis in analysis['rubric']:st.write(label+' — '+importance+': '+basis)
    with st.form('candidate_grid_'+rid):
        actor=st.text_input('Scientific reviewer name',p.get('case',{}).get('scientific_reviewer',''))
        current=p.get('selected_kit');index=next((i for i,k in enumerate(candidates) if k['id']==current),None)
        selected=st.selectbox('Select kit for volume calculations',candidates,index=index,format_func=lambda k:k['name']+' / '+k['catalog'],key='kit_choice_'+rid)
        save=st.form_submit_button('Save comparison changes')
        use=st.form_submit_button('Use selected kit and recalculate volumes')
        if save or use:
            try:
                updates=collect_updates(edited,baseline,candidates)
                engine_action(lambda e:e.configure_review(rid,actor,kit_id=selected['id'] if use and selected else None,candidate_updates=updates,use_kit_minimum=True if use and selected else None))
                st.rerun()
            except Exception as exc:st.error(str(exc))
    if p.get('screened_candidates'):
        st.markdown('#### Additional candidates screened only')
        st.caption('These candidates were noted during the lightweight search and were not equally researched within the four-kit assessment limit.')
        readable_table([{'Kit':k.get('name',''),'Platform':k.get('platform',''),'Screening note':k.get('reason') or 'Not deeply assessed within the four-kit limit','Kit manual':k.get('manual_url','')} for k in p['screened_candidates']])
    if finalists:
        st.markdown('#### Alternative kits reviewed')
        readable_table([{'Kit':k['name'],'Platform':k['platform'],'Primary reason':k.get('rejection_reason') or 'Screened; not fully assessed. Exclusion reason requires documentation.','Kit manual':manual_reference(p,k)[0]} for k in all_candidates if k['id'] not in finalists])



SECTION_LABELS={'recommendation':'Kit selection','validation':'Validation plan','volume':'Volumes','cost':'Costs','evidence':'Evidence'}

def review_overview(rid,p,state,run):
    st.markdown('#### Review overview')
    kit=next((k for k in p.get('candidates',[]) if k['id']==p.get('selected_kit')),None)
    study=p.get('study',{});cost=p.get('cost',{})
    a,b,c=st.columns(3)
    a.metric('Scientist-selected kit',kit['catalog'] if kit else 'Not selected',help=kit['name'] if kit else 'Select a kit in Review → Kits')
    b.metric('Study matrix required / available',f"{study['total_ul']:g} / {study['available_ul']:g} µL" if study.get('total_ul') is not None and study.get('available_ul') is not None else 'Not calculated',help='Includes initial preparation, repeat reserve and study handling. Validation material is calculated separately.')
    c.metric('Known subtotal — incomplete' if cost.get('incomplete') else 'Estimated project total',f"${float(cost['internal_cost']):,.2f}" if cost.get('internal_cost') is not None else 'Not estimated')
    decisions=current_decisions(store,rid,packet_hash(p));approved=sum(decisions.get(('scientific',section),{}).get('action')=='approve' for section in SECTIONS)
    director=decisions.get(('director','project'),{}).get('action','pending')
    from tsh_advisory.evidence_details import core_fact_assessment
    linked=sum(r['Included in supported count'] for r in core_fact_assessment(p,kit)) if kit else 0
    st.caption(('Simulated scientific review' if run['mode']=='fixture' else 'Scientific review')+f': {approved}/{len(SECTIONS)} sections approved · Director: {director} · Selected kit source coverage: {linked}/6')
    recommended=next((k for k in p.get('candidates',[]) if k['id']==p.get('recommended_kit')),None)
    if recommended:
        provisional=p.get('recommendation_refresh',{}).get('status')!='clear_rule_based_choice'
        st.write('Planning recommendation: **'+recommended['catalog']+'**'+(' · provisional' if provisional else ' · supported by recorded comparison')+(' · differs from scientist-selected kit' if kit and kit['id']!=recommended['id'] else ''))
    else:st.write('Planning recommendation: pending a supported choice. Scientist selection remains available.')
    with st.expander('Changes since the previous revision'):
        revisions=store.revisions(rid)
        if revisions:
            previous=json.loads(max(revisions,key=lambda r:r['revision'])['data']).get('packet',{})
            changes=[]
            old_kits={k['id']:k for k in previous.get('candidates',[])}
            for candidate in p.get('candidates',[]):
                old=old_kits.get(candidate['id'],{})
                for field in ('kit_price','well_input_ul','dilution_factor','reviewer_lead_time'):
                    if old.get(field)!=candidate.get(field):changes.append({'Input':candidate['catalog']+' · '+field.replace('_',' '),'Previous':old.get(field),'Current':candidate.get(field)})
            for field in ('labor_hours_per_plate','shipping_per_kit','matrix_shipment_usd','consumables_per_plate'):
                old=previous.get('cost_assumptions',{}).get(field);current=p.get('cost_assumptions',{}).get(field)
                if old!=current:changes.append({'Input':field.replace('_',' '),'Previous':old,'Current':current})
            if changes:readable_table(changes)
            else:st.caption('No changes to the displayed kit and cost inputs. Other evidence, metadata or planning details may have changed; complete history is in Evidence.')
        else:st.caption('No previous planning revision.')


def science_review(rid,p,state):
    st.subheader('Scientific and cost accuracy approval')
    st.caption('One named person reviews science and economics. Approving the planning document does not validate a laboratory method.')
    decisions=current_decisions(store,rid,packet_hash(p))
    section_key='approval_section_'+rid
    left,right=st.columns([1,1.7])
    with left:
        st.markdown('**Sections to review**')
        for section_id in SECTIONS:
            current=decisions.get(('scientific',section_id),{})
            status={'approve':'Approved','return':'Returned for revision','reject':'Rejected'}.get(current.get('action'),'Pending')
            if st.button(SECTION_LABELS[section_id]+' · '+status,key='section_card_'+rid+section_id,width='stretch',type='primary' if st.session_state.get(section_key,'recommendation')==section_id else 'secondary'):
                st.session_state[section_key]=section_id
                st.rerun()
        if st.session_state.get(section_key) not in SECTIONS:st.session_state[section_key]=SECTIONS[0]
    with right:
        section=st.session_state[section_key]
        st.caption('Decision applies only to '+SECTION_LABELS[section]+' in the current saved revision.')
    if state.get('status') not in ('awaiting_scientific','scientific_approved','awaiting_director'):
        st.info('This run is not at a review stage.');return
    test_run=store.run(rid)['mode']=='fixture'
    if test_run:st.info('This is a TEST DATA run. Use simulated approval below to exercise the workflow. It records your test decision without clearing findings or authorizing laboratory work.')
    elif blocking_findings(p):
        st.info('Findings are advisory and do not block approval. Review them and document your decision.')
    with right.form('science-decision-'+rid+'-'+str(p.get('planning_revision',1))+'-'+section):
        actor=st.text_input('Named scientific/cost reviewer',state['case']['scientific_reviewer'],disabled=True)
        st.markdown('**'+SECTION_LABELS[section]+' decision**')
        action=st.selectbox('Decision',['approve','return','reject'],index=None)
        reason=st.selectbox('Reason',POSITIVE['scientific']+NEGATIVE,index=None)
        candidates=p.get('candidates',[])
        kit=st.selectbox('Approved kit (explicit choice required for recommendation)',candidates,index=None,format_func=lambda k:k['manufacturer']+' / '+k['name']+' / '+k['catalog']) if section=='recommendation' else None
        comments=st.text_area('Selection rationale, limitations or revision instructions')
        attest=st.checkbox('I am the named reviewer and accept responsibility for this decision.')
        instrument_confirmed=st.checkbox('For recommendation approval: I confirm the available instruments and equipment are suitable for the selected kit.') if section=='recommendation' else False
        simulation=st.checkbox('Record a simulated approval for TEST DATA only',key='science_simulation_'+rid) if test_run else False
        submit=st.form_submit_button('Record section decision')
    if submit:
        if not attest or not action or not reason: st.error('Confirm identity and choose a decision and reason.');return
        try:
            record_decision(store,rid,'scientific',actor,section,action,reason,comments,kit['id'] if kit else None,packet_hash(p),simulation=simulation,instrument_confirmed=instrument_confirmed)
            if action in ('return','reject'):
                engine_action(lambda e:e.resume(rid,{'action':action,'section':section,'comments':comments,'reason':reason}))
            elif scientific_complete(store,rid): engine_action(lambda e:e.resume(rid,{'action':'approve'}))
            st.rerun()
        except Exception as exc: st.error(str(exc))

def cost_view(rid,p,state):
    st.subheader('Cost estimates · scientific/cost accuracy review')
    kit=next((k for k in p.get('candidates',[]) if k['id']==p.get('selected_kit')),None)
    cost=p.get('cost',{})
    if cost:
        a,b=st.columns(2);a.metric('Known cost subtotal (incomplete)' if cost.get('incomplete') else 'Internal cost',f'{cost["currency"]} {cost["internal_cost"]}');b.metric('Complete client quote' if cost.get('incomplete') else 'Proposed client price','Unavailable' if cost.get('incomplete') else f'{cost["currency"]} {cost["client_price"]}')
        st.markdown('#### Cost breakdown')
        from tsh_advisory.estimate_basis import cost_chart_rows
        df=pd.DataFrame(cost_chart_rows(p))
        order=df['category'].tolist()
        base=alt.Chart(df).encode(y=alt.Y('category:N',sort=order,title=None,axis=alt.Axis(labelLimit=240)),x=alt.X('plot_usd:Q',title=cost.get('currency','USD'),scale=alt.Scale(zero=True)),tooltip=[alt.Tooltip('category:N',title='Cost category'),alt.Tooltip('label:N',title='Estimate')])
        bars=base.mark_bar(color='#377b73',size=22)
        labels=base.mark_text(align='left',baseline='middle',dx=6,fontSize=12,color='#e2e8f0' if st.context.theme.type=='dark' else '#23364a').encode(text='label:N')
        st.altair_chart((bars+labels).properties(height=max(250,len(df)*36),padding={'left':5,'top':10,'right':110,'bottom':5}),width='stretch')
        scenarios=cost.get('scenarios',{})
        st.markdown('#### Estimate scenarios')
        scenario_rows=[]
        for key,title,assumptions in [('lower_assumption_price','Lower','Labor hours −25%; kit unit prices −30%'),('base_price','Base','Current saved assumptions'),('higher_assumption_price','Higher','Labor hours +25%; kit unit prices +30%')]:
            amount=f"{cost.get('currency','USD')} {float(scenarios[key]):,.2f}" if scenarios.get(key) is not None else 'Not estimated'
            scenario_rows.append({'Scenario':title,'Known subtotal (incomplete)' if cost.get('incomplete') else 'Estimated total':amount,'Assumptions':assumptions})
        readable_table(scenario_rows)
        st.caption(scenarios.get('meaning','Scenario assumptions require review.'))
        st.markdown('#### Estimate assumptions · editable')
        from tsh_advisory.cost_grid import rows as cost_rows,render as render_cost_grid,changes as cost_changes
        baseline=cost_rows(p)
        st.caption('Double-click an estimate to edit, then press Tab. Only changed values are marked blue and bold. Kit timing, intake labor rate and automatic overhead are read-only.')
        st.caption('Calculations and totals reflect saved estimates. Save changes to recalculate; timing/reference rows are not additional costs.')
        edited=render_cost_grid(baseline,'cost_estimates_'+rid+'_'+str(p.get('planning_revision',1)))
        cost_actor=st.text_input('Reviewer recording estimates',state['case']['scientific_reviewer'])
        if st.button('Save estimate assumptions'):
            try:
                updates=cost_changes(edited,baseline)
                if not updates and p.get('cost_assumptions',{}).get('shipping_policy')=='per_kit_plus_matrix':st.info('No estimate values changed.')
                else:
                    matrix=updates.pop('pooled_material',None);price=updates.pop('kit_price',None)
                    if p.get('cost_assumptions',{}).get('shipping_policy')!='per_kit_plus_matrix':
                        updates.setdefault('shipping_per_kit',20);updates.setdefault('matrix_shipment_usd',200)
                    updates['shipping_policy']='per_kit_plus_matrix'
                    updates.update(class_estimate_mode=True,confirm_scope=True)
                    engine_action(lambda e:e.configure_review(rid,cost_actor,matrix_price=matrix,kit_price=price,cost_settings=updates,estimate_origin='cost_table'));st.rerun()
            except Exception as exc:st.error(str(exc))
        if cost.get('incomplete'): st.warning('Incomplete estimate: '+ '; '.join(cost['unresolved']))
        if cost.get('budget_exceeded'):st.error('Configured project ceiling exceeded.')

def director_view(rid,p,state):
    st.subheader('Manager or director decision')
    kit=next((k for k in p.get('candidates',[]) if k['id']==p.get('selected_kit')),None)
    st.write('Selected kit:',(kit['name']+' / '+kit['catalog']) if kit else 'None')
    st.write('Lead time:',public_lead_time(p,kit))
    approved=[d for d in store.decisions(rid) if d['role']=='scientific' and d['section']=='recommendation' and d['action']=='approve' and d['packet_hash']==packet_hash(p)]
    st.write('Scientific kit approval:',approved[-1]['kit_record']['catalog'] if approved else 'Pending')
    st.write('Scientific and cost accuracy:','Approved' if scientific_complete(store,rid) else 'Pending')
    st.caption('Review project estimates in the Cost estimates tab before recording this decision.')
    if state.get('status')!='awaiting_director': st.info('Director sign-off opens after current scientific/cost accuracy approval.');return
    with st.form('director-decision-'+rid+'-'+str(p.get('planning_revision',1))):
        actor=st.text_input('Named manager/director',state['case']['director'],disabled=True)
        action=st.selectbox('Project decision',['approve','return','reject'],index=None)
        reason=st.selectbox('Project reason',POSITIVE['director']+NEGATIVE,index=None)
        comments=st.text_area('Additional comments or required revision')
        attest=st.checkbox('I am the named manager/director and authorize only the current project version.')
        simulation=st.checkbox('Record a simulated manager approval for TEST DATA only',key='director_simulation_'+rid) if store.run(rid)['mode']=='fixture' else False
        submit=st.form_submit_button('Record project decision')
    if submit:
        try:
            if not attest or not action or not reason: raise ValueError('Confirm identity and choose a decision and reason.')
            record_decision(store,rid,'director',actor,'project',action,reason,comments,expected_hash=packet_hash(p),simulation=simulation)
            engine_action(lambda e:e.resume(rid,{'action':action,'comments':comments,'reason':reason}))
            st.rerun()
        except Exception as exc: st.error(str(exc))

def supporting_documents_view(rid,p,state):
    from tsh_advisory import supporting_documents as documents
    from tsh_advisory.document_extraction import extract_suggestions
    st.subheader('Supporting documents')
    st.caption('Upload → Extract → Confirm. Searchable PDF, EML or UTF-8 TXT, up to 10 MB. Manual estimates and optional passages remain supported.')
    kits=p.get('candidates',[]);labels={k['id']:k['catalog']+' / '+k['name'] for k in kits}
    records=p.get('supporting_documents',[])
    with st.expander('1 · Upload a supporting document',expanded=not bool(records)):
        uploaded=st.file_uploader('Supporting document file',type=['pdf','eml','txt'],max_upload_size=10,key='support_file_'+rid)
        hint={};hint_source='';upload_key=rid
        if uploaded:
            upload_key=rid+digest(uploaded.getvalue())[:12]
            try:
                from datetime import date
                import re
                if uploaded.size>10*1024*1024:raise ValueError('Document exceeds 10 MB.')
                preview_text=documents.extract(uploaded.getvalue(),Path(uploaded.name).suffix.lower())
                preview=extract_suggestions(preview_text,kits)
                hint['suggestions']=preview['suggestions']
                sender=re.search(r'^From:\s*(.+)$',preview_text,re.M)
                vendor=re.search(r'^(?:Vendor|Supplier):\s*(.+)$',preview_text,re.M|re.I)
                hint_source=(sender or vendor).group(1).strip() if sender or vendor else ''
                st.caption(str(len(preview['suggestions']))+' suggestions identified locally. Confirm document details below, then review the values.')
            except Exception as exc:st.error(str(exc))
        def upload_date(field):
            from datetime import date
            values={s['iso_date'] for s in hint.get('suggestions',[]) if s['field']==field and s.get('iso_date')}
            return date.fromisoformat(next(iter(values))) if len(values)==1 else None
        hinted_ids={s['candidate_id'] for s in hint.get('suggestions',[]) if s['field']=='catalog' and s.get('candidate_id')}
        hinted_kit=next(iter(hinted_ids)) if len(hinted_ids)==1 else None
        with st.form('supporting_upload_'+upload_key,clear_on_submit=False):
            supporting_upload_form(rid,p,state,documents,uploaded,upload_key,labels,hint_source,upload_date,hinted_kit)
    if not records:st.info('No supporting documents saved for this run.');return
    supporting_document_review(rid,p,state,documents,kits,labels,records)


def supporting_upload_form(rid,p,state,documents,uploaded,upload_key,labels,hint_source,upload_date,hinted_kit):
        kind=st.selectbox('Document type',documents.KINDS)
        linked_kit=st.selectbox('Link document to kit (optional)',[None]+list(labels),index=([None]+list(labels)).index(hinted_kit),format_func=lambda value:labels[value] if value else 'Project-wide reference')
        source_name=st.text_input('Vendor, sender or document source',value=hint_source)
        source_url=st.text_input('Source website URL (optional)')
        a,b=st.columns(2)
        document_date=a.date_input('Quote/email/document date (optional)',value=upload_date('document_date'))
        expires=b.date_input('Expiration / valid-through date (optional)',value=upload_date('expires_on'))
        notes=st.text_area('Document context / limitations (optional)')
        include=st.checkbox('Include original file in exported evidence bundle',value=True)
        actor=st.text_input('Scientist recording the document',state['case']['scientific_reviewer'])
        submit=st.form_submit_button('Save document and review suggestions')
        if submit:
            try:
                if uploaded is None:raise ValueError('Choose a supporting document file.')
                changed=engine_action(lambda e:e.add_supporting_document(rid,actor,uploaded.getvalue(),uploaded.name,{'kind':kind,'candidate_id':linked_kit,'source_name':source_name,'source_url':source_url,'document_date':document_date.isoformat() if document_date else '', 'expires_on':expires.isoformat() if expires else '', 'notes':notes,'include_in_bundle':include}))
                if changed:
                    st.session_state['support_record_'+rid]=store.run(rid)['data']['packet']['supporting_documents'][-1]['id'];st.rerun()
                else:st.info('This file and metadata are already saved in this run.')
            except Exception as exc:st.error(str(exc))


def supporting_document_review(rid,p,state,documents,kits,labels,records):
    from tsh_advisory.document_extraction import extract_suggestions
    st.markdown('#### Saved supporting documents')
    readable_table([{'Document':r['filename']+' · '+r['kind'],'Kit':labels.get(r['candidate_id'],'Project-wide'),'Validity':documents.expiry_status(r),'Review state':str(len(r.get('uses',[])))+' reviewed value(s)' if r.get('uses') else 'Review pending'} for r in records])
    by_id={r['id']:r for r in records};key='support_record_'+rid
    if not isinstance(st.session_state.get(key),str) or st.session_state.get(key) not in by_id:st.session_state[key]=records[-1]['id']
    document_id=st.selectbox('Document to inspect or use',list(by_id),format_func=lambda value:by_id[value]['filename']+' · '+by_id[value]['kind'],key=key)
    record=by_id[document_id]
    try:raw,text=documents.load(store,record)
    except Exception as exc:st.error(str(exc));return
    from tsh_advisory.document_extraction import extract_suggestions
    extraction=record.get('extraction') or extract_suggestions(text,kits)
    suggestions=extraction['suggestions']
    st.markdown('#### 2 · Extracted suggestions')
    if suggestions:
        readable_table([{'Information':s['field'].replace('_',' ').title(),'Proposed value':str(s['value'])+(' '+s.get('currency','')+' / '+s.get('unit','') if s['field']=='price' else ''),'Kit':s.get('catalog') or 'Not established','Source location':s['locator'],'Review note':s.get('review_note','Confirm kit identity.')} for s in suggestions])
    else:st.info('No confident price, lead time, catalog or date suggestions were identified. Manual entry remains available.')
    st.caption(extraction['notice'])
    with st.expander('Review suggested kit association and document dates'):
        from datetime import date
        def suggested_date(field):
            values={s['iso_date'] for s in suggestions if s['field']==field and s.get('iso_date')}
            value=record.get(field) or (next(iter(values)) if len(values)==1 else None)
            return date.fromisoformat(value) if value else None
        detected={s['candidate_id'] for s in suggestions if s['field']=='catalog' and s.get('candidate_id')}
        proposed_kit=record.get('candidate_id') or (next(iter(detected)) if len(detected)==1 else None)
        with st.form('support_metadata_'+rid+record['id']):
            reviewed_kit=st.selectbox('Reviewed document kit association',[None]+list(labels),index=([None]+list(labels)).index(proposed_kit),format_func=lambda value:labels[value] if value else 'Project-wide / multiple kits')
            reviewed_date=st.date_input('Reviewed document date',value=suggested_date('document_date'))
            reviewed_expiry=st.date_input('Reviewed expiration date',value=suggested_date('expires_on'))
            if st.form_submit_button('Confirm document details'):
                try:
                    engine_action(lambda e:e.review_supporting_metadata(rid,state['case']['scientific_reviewer'],record['id'],reviewed_date.isoformat() if reviewed_date else '',reviewed_expiry.isoformat() if reviewed_expiry else '',reviewed_kit or ''));st.rerun()
                except Exception as exc:st.error(str(exc))
    st.download_button('Download original supporting document',raw,file_name=record['filename'],mime={'.pdf':'application/pdf','.eml':'message/rfc822','.txt':'text/plain'}[record['extension']],key='support_download_'+rid+record['id'])
    st.caption('Source: '+record['source_name']+' · Document date: '+(record['document_date'] or 'Not recorded')+' · Recorded by '+record['uploaded_by'])
    with st.expander('Technical file record'):
        readable_table([{'Source ID':record['source_id'],'SHA-256':record['sha256'],'Uploaded':record['uploaded_at']}])
    if documents.expiry_status(record).startswith('Expired'):st.warning('This document is past its recorded expiration date. Consider validity before adopting a value; the original remains available for audit.')
    with st.expander('Extracted document text / email body'):
        st.text(text)
    if record.get('notes'):st.write('Context:',record['notes'])
    if record.get('uses'):
        with st.expander('Recorded evidence uses'):
            readable_table(record['uses'])
    default_purpose=1 if any(s['field']=='price' and s.get('usd_per_kit') is not None for s in suggestions) else 2 if any(s['field']=='lead_time' for s in suggestions) else 0
    st.markdown('#### 3 · Confirm a value')
    purpose=st.selectbox('Use this document for', ['Reference only','Kit price (USD per kit)','Lead time'],index=default_purpose,key='support_purpose_'+rid+record['id'])
    if purpose=='Reference only':
        st.caption('This source is also available in Kit comparison → Cell evidence and selection basis for linking other supported facts.');return
    eligible=[k for k in kits if not record['candidate_id'] or k['id']==record['candidate_id']]
    detected={s['candidate_id'] for s in suggestions if s['field']=='catalog' and s.get('candidate_id')}
    target_default=record.get('candidate_id') or (next(iter(detected)) if len(detected)==1 else None)
    target=st.selectbox('Kit for reviewed value',eligible,index=next((i for i,k in enumerate(eligible) if k['id']==target_default),None),format_func=lambda k:labels[k['id']],key='support_target_'+rid+record['id'])
    if target is None:st.info('Select the kit to review. Multiple or unmatched kit identities are not assigned automatically.');return
    field='kit_price' if purpose.startswith('Kit price') else 'reviewer_lead_time'
    proposals=[s for s in suggestions if (s['field']=='price' and s.get('usd_per_kit') is not None if field=='kit_price' else s['field']=='lead_time') and (not s.get('candidate_id') or s['candidate_id']==target['id'])]
    chosen=st.selectbox('Extracted value to review',[None]+proposals,index=1 if len(proposals)==1 else 0,format_func=lambda s:'Manual entry / no extracted passage' if s is None else (str(s['usd_per_kit'])+' USD/kit' if field=='kit_price' else str(s['value']))+' · '+s['locator'],key='support_proposal_'+rid+record['id']+target['id']+field)
    if chosen:
        st.write('Detected supporting text:',chosen['quote'])
    with st.form('support_adopt_'+rid+record['id']+target['id']+field+digest(chosen)[:8]):
        initial=chosen['usd_per_kit'] if chosen and field=='kit_price' else chosen['value'] if chosen else target.get('kit_price') if field=='kit_price' else target.get('reviewer_lead_time') or target.get('lead_time') or ''
        value=nullable_number('Reviewed price USD per kit',initial,min_value=.01) if field=='kit_price' else st.text_input('Reviewed lead time',initial)
        st.caption('A supporting passage is optional. Leave both citation fields blank to record a reviewer estimate associated with this document. Providing a valid passage records field-level source support.')
        locator=st.text_input('Supporting location (optional PDF page or email section)',chosen['locator'] if chosen else '')
        quote=st.text_area('Exact supporting passage (optional)',chosen['quote'] if chosen else '',max_chars=400)
        reviewer=st.text_input('Scientist verifying this value',state['case']['scientific_reviewer'])
        confirmed=st.checkbox('I am recording a scientist-reviewed value, have considered document date/validity, and checked any optional passage provided.')
        apply=st.form_submit_button('Save reviewed value and recalculate')
    if apply:
        try:
            engine_action(lambda e:e.adopt_supporting_value(rid,reviewer,record['id'],target['id'],field,value,quote,locator,confirmed));st.rerun()
        except Exception as exc:st.error(str(exc))


def updated_intake_view(rid,state):
    from tsh_advisory.intake_updates import preview
    update=preview(store,rid)
    if not update['version_changed']:return
    st.warning('Saved intake has changed. This run still uses intake version '+str(update['saved_version'])+'; the current intake is version '+str(update['current_version'])+'.')
    with st.expander('Review intake changes and recalculate without a model call',expanded=True):
        rows=[]
        for field,change in update['changes'].items():
            def display(value):
                if isinstance(value,(list,dict)):return json.dumps(value,ensure_ascii=False)
                return value
            rows.append({'Input':field.replace('_',' ').title(),'Saved run':display(change['previous']),'Current intake':display(change['current']),'Review': 'Check retained evidence' if field in update['review_fields'] else 'Local recalculation'})
        if rows:readable_table(rows)
        else:st.caption('The saved intake version changed, but its normalized values match the previously applied intake.')
        st.caption('Reuses saved kit research, documents and reviewer facts. Recalculates the requested design, volumes, plate/kit allocation, estimates and comparison. Prior packets and decisions remain in history; the revised packet requires fresh approval.')
        with st.form('apply_intake_'+rid+'_'+str(update['current_version'])):
            actor=st.text_input('Scientist applying updated intake',state['case']['scientific_reviewer'])
            confirmed=False;reason=''
            if update['review_fields']:
                st.info('These changes may affect the retained evidence: '+', '.join(field.replace('_',' ') for field in update['review_fields'])+'. Review its applicability or start a new research run.')
                confirmed=st.checkbox('I reviewed the retained evidence and accept its reuse for this revised planning scope; no new research will be performed.')
                reason=st.text_area('Why the retained evidence remains applicable')
            if st.form_submit_button('Apply updated intake and recalculate'):
                try:
                    engine_action(lambda e:e.apply_updated_intake(rid,actor,scope_confirmed=confirmed,scope_reason=reason,expected_version=update['current_version']))
                    for key in ('pdf_'+rid,'export_'+rid):st.session_state.pop(key,None)
                    st.rerun()
                except Exception as exc:st.error(str(exc))


def run_view(cid):
    st.caption('Bioanalytical Advisory · Scientist workspace')
    st.subheader(store.case(cid)['data']['title'])
    runs=store.runs(cid)
    with st.expander('Run setup',expanded=not bool(runs)):
        with st.expander('Organization and skills'):
            for name,goal in ROLES.items():st.markdown('**'+name.title()+'** — '+goal)
            st.markdown('**Human approvals**')
            for name,responsibility in HUMAN_ROLES.items():st.markdown('**'+name+'** — '+responsibility)
        mode=st.radio('Run mode',['fixture'] if PUBLIC_DEMO else ['fixture','live'],horizontal=True,format_func=lambda s:'Test data · live-style review' if s=='fixture' else 'Live OpenAI research')
        if mode=='fixture': st.info('New-run setting: Test data. This applies only to Start new run; it does not describe the saved run selected below.')
        if st.button('Start new run',type='primary'):
            settings_path=DATA/'settings.json';settings=json.loads(settings_path.read_text()) if settings_path.exists() else {}
            settings['planning_version']='lot-planning-v3'
            if mode=='fixture':settings['manual_demo']=True
            if mode=='live' and not settings.get('rate_date'):st.error('Save a dated provider rate card in Settings first.')
            else:
                try:
                    with st.spinner('Agents working; source, task and model events are retained…'): engine_action(lambda e:e.start(cid,mode,settings))
                    st.rerun()
                except Exception as exc:st.error(str(exc))
    runs=store.runs(cid)
    if not runs:return
    rid=st.selectbox('Saved run',[r['id'] for r in runs],format_func=lambda x:x[:12]+' · '+next(r['mode'] for r in runs if r['id']==x))
    run=store.run(rid);state=run['data'];p=state.get('packet',{})
    if p and not run['stopped'] and state.get('status') in ('awaiting_scientific','awaiting_director','authorized'):updated_intake_view(rid,state)
    if p and not run['stopped'] and state.get('status') in ('awaiting_scientific','awaiting_director','authorized') and p.get('cost_assumptions',{}).get('estimate_rules_version',0)<2:
        engine_action(lambda e:e.apply_estimate_defaults(rid))
        st.rerun()
    if p and not run['stopped'] and state.get('status') in ('awaiting_scientific','awaiting_director','authorized') and not p.get('recommendation_refresh'):
        engine_action(lambda e:e.configure_review(rid,state['case']['scientific_reviewer']))
        st.rerun()
    if p and p.get('volume',{}).get('calculation_version') not in ('matrix-plus200-v1','lot-planning-v2','lot-planning-v3'):
        st.warning('This saved packet contains earlier volume calculations. Refresh them below to use whole-microlitre matrix withdrawals and the current serial-dilution table.')
        if st.button('Refresh saved calculations and parallelism table'):
            engine_action(lambda e:e.recalculate(rid))
            for key in ['pdf_'+rid,'export_'+rid]:st.session_state.pop(key,None)
            st.rerun()
    if p and p.get('volume',{}).get('rows') and 'initial_kits' not in p['volume']['rows'][0]:
        st.warning('This saved run uses the earlier calculation format. Start a new run to apply the corrected kit counts, tQC/EQC option and detailed parallelism calculations. Prior results and decisions are preserved.')
    human_status={'awaiting_scientific':'Awaiting scientific review','awaiting_director':'Awaiting director authorization','authorized':'Project authorized','running':'Agents working','failed':'Run needs attention'}.get(state.get('status'),str(state.get('status','')).replace('_',' ').capitalize())
    st.caption(('Live research' if run['mode']=='live' else 'Test data')+' · Revision '+str(state.get('planning_revision',1))+' · '+('Stopped' if run['stopped'] else human_status))
    with st.expander('Run tools',expanded=False):
        if p and not run['stopped'] and state.get('status') in ('awaiting_scientific','awaiting_director','authorized'):
            if st.button('Reassess saved packet with current rules (no model calls)'):
                try:
                    with st.spinner('Reassessing retained evidence and calculations; no live model run…'):engine_action(lambda engine:engine.reassess_saved_run(rid))
                    st.rerun()
                except Exception as exc:st.error(str(exc))
        if p and p.get('volume',{}).get('calculation_version')!='lot-planning-v3' and not run['stopped'] and state.get('status') in ('awaiting_scientific','awaiting_director','authorized'):
            st.info('A corrected planning revision is available. Creating it archives the current packet and requires fresh scientific/cost and director decisions. No model calls are needed.')
            if st.button('Create corrected planning revision (preserve history)'):
                try:engine_action(lambda engine:engine.configure_review(rid,state['case']['scientific_reviewer']));st.rerun()
                except Exception as exc:st.error(str(exc))
        if st.button('Stop this run'):store.stop(rid,'local project owner');st.rerun()
    if run['stopped']:
        errors=[e['data']['data'] for e in store.events(rid) if e['data']['event']=='run_error']
        if errors and errors[-1].get('message','').startswith('Planner omitted requested parameters:'):
            st.warning('The planner omitted requested experiments. Resume the saved planner step with design correction; completed research and finalist selection are retained. Existing API spending and call limits still apply.')
            if st.button('Resume failed planner using saved finalists'):
                try:
                    with st.spinner('Correcting the validation plan and continuing saved tasks…'):engine_action(lambda e:e.retry_planner_step(rid))
                    st.rerun()
                except Exception as exc:st.error(str(exc))
        if errors and errors[-1].get('message','').endswith('-call limit reached.') and p:
            st.warning('The revision reached its call limit. A completed draft is available for human review; scientific blockers remain visible.')
            if st.button('Recover completed draft for scientific review (no API calls)'):
                try:
                    engine_action(lambda e:e.recover_completed_draft(rid));st.rerun()
                except Exception as exc:st.error(str(exc))
        if errors and errors[-1].get('message')=='Agent reached its six-step tool limit; human intervention required.':
            st.info('This run stopped at the old research-step limit. Its sources and usage are retained; the failed step can resume without repeating completed stages.')
            if st.button('Resume interrupted research using saved sources'):
                try:
                    with st.spinner('Resuming the failed research step…'):engine_action(lambda e:e.retry_research_step(rid))
                    st.rerun()
                except Exception as exc:st.error(str(exc))
    if not p:
        st.info('No packet available yet. Inspect logged errors below.');st.json(store.events(rid));return
    if run['mode']=='fixture':st.info('TEST DATA · Same review workflow as live mode. Manual-linked examples and test assumptions; no live research or approval is implied.')
    review_overview(rid,p,state,run)
    stage=st.radio('Workspace',['Review','Evidence','Approvals','Export'],horizontal=True,key='workspace_stage_'+rid)
    if stage=='Review':
        tabs=st.tabs(['Plan','Kits','Volumes','Costs','Documents'])
        with tabs[0]:
            approved=current_decisions(store,rid,packet_hash(p)).get(('scientific','recommendation'),{})
            approved_kit=approved.get('kit_record') if approved.get('action')=='approve' else None
            st.write('**Reviewer-approved kit:**',(approved_kit['name']+' / '+approved_kit['catalog']) if approved_kit else 'Approval pending')
            with st.expander('Proposed validation protocol',expanded=True):protocol_view(p.get('plan'),state['case'],p.get('volume'))
        with tabs[1]:candidate_view(p,rid)
        with tabs[2]:volume_charts(p,rid)
        with tabs[3]:cost_view(rid,p,state)
        with tabs[4]:supporting_documents_view(rid,p,state)
    elif stage=='Approvals':
        tabs=st.tabs(['Scientific & cost','Director'])
        with tabs[0]:science_review(rid,p,state)
        with tabs[1]:director_view(rid,p,state)
    elif stage=='Evidence':run_evidence_view(rid,p,state,run,cid)
    else:export_view(rid,p,state,run,cid)

def run_evidence_view(rid,p,state,run,cid):
    st.markdown('#### Review flags and current findings')
    st.caption('Refresh rechecks saved inputs and current rules without a live model call. Addressed or superseded flags move to history; uncertain agent concerns remain for scientist review.')
    if st.button('Refresh review flags',key='refresh_flags_'+rid):
        try:
            engine_action(lambda e:e.refresh_review_flags(rid));st.rerun()
        except Exception as exc:st.error(str(exc))
    flags=scoped_findings(p)
    attention=[f for f in flags if f.get('requires_attention')]
    a,b,c=st.columns(3)
    a.metric('Needs attention',len(attention));b.metric('Other advisory flags',len(flags)-len(attention));c.metric('Approval blocks',0)
    st.caption('All flags are advisory. They do not prevent scientific or director approval. Saving reviewer information updates the plan; it does not erase historical evidence gaps or turn estimates into verified facts.')
    gaps=planning_review_gaps(p)
    if gaps:
        with st.expander('Missing information for the selected kit',expanded=True):
            readable_table([{'Topic':g['Area'],'Missing information':g['Missing or unresolved'],'Suggested action':g['What is needed']} for g in gaps])
            st.caption('Enter kit facts, estimates and supporting references in Candidate comparison. Kit compatibility and source links are reviewed in Candidate comparison.')
    if not flags:st.success('No current review flags.')
    if flags:
        with st.form('review_flags_'+rid):
            review_actor=st.text_input('Scientist reviewing flags',state['case']['scientific_reviewer'])
            reviews={}
            for f in sorted(flags,key=lambda f:(not f.get('requires_attention'),f.get('section',''))):
                fid=f['id']
                title=('Needs attention' if f.get('requires_attention') else 'Information')+' · '+f.get('section','').title()+' · '+f.get('severity','').title()
                with st.expander(title,expanded=False):
                    st.write(f.get('message',''))
                    st.caption('Owner: '+f.get('owner','Reviewer')+' | Status: '+f.get('status','open').replace('_',' ')+' | Applies to: '+f.get('scope','project').replace('_',' '))
                    if f.get('planning_treatment_reason'):st.info(f['planning_treatment_reason'])
                    checked=st.checkbox('I reviewed this flag',key='flag_checked_'+rid+'_'+fid)
                    outcome=st.selectbox('Review outcome',['Accepted for planning','Corrected'],key='flag_outcome_'+rid+'_'+fid)
                    reason=st.text_area('Reason / action taken',key='flag_reason_'+rid+'_'+fid)
                    evidence=st.text_input('Supporting reference (optional)',key='flag_reference_'+rid+'_'+fid)
                    if checked:reviews[fid]={'action':'accepted' if outcome=='Accepted for planning' else 'corrected','reason':reason,'evidence':evidence}
            st.caption('Accepted flags move to reviewed history as accepted assumptions, not passed checks. Corrected means the scientist reports an action taken; an active deterministic failure cannot be marked corrected.')
            if st.form_submit_button('Save checked flag reviews'):
                try:
                    engine_action(lambda e:e.acknowledge_findings(rid,review_actor,reviews));st.rerun()
                except Exception as exc:st.error(str(exc))
    with st.expander('Technical findings and disposition records'):
        readable_table(p.get('findings',[]))
        with st.expander('Raw reviewed finding records'):
            st.json(p.get('finding_history',[]))
        st.caption('Citation mapping diagnostics are retained here for reconstruction, rather than repeated as review flags. Reviewer entries are not automatically verified public evidence.')
        readable_table(selected_review_gaps(p))
    with st.expander('Reviewed flags · accepted, corrected and superseded'):
        history_rows=[]
        for f in p.get('finding_history',[]):
            d=f.get('disposition',{});status=f.get('status','')
            outcome='Accepted for planning' if status=='accepted' else 'Corrected / resolved' if status=='resolved' else 'Superseded'
            history_rows.append({'Review':'✓ '+outcome,'Section':f.get('section','').title(),'Flag':f.get('message',''),
                'Reviewer':d.get('actor','System rules'),'Reason':d.get('reason') or f.get('resolution',''),
                'Reference':d.get('evidence',''),'Recorded':d.get('timestamp','')})
        readable_table(history_rows)
    st.write('Audit hash chain:', 'Valid' if store.verify(rid) else 'FAILED')
    with st.expander('Technical record · raw protocol and candidate data'):
        st.caption('Underlying structured data retained for reconstruction and audit.')
        st.json({'plan':p.get('plan',{}),'candidates':p.get('candidates',[])})
    with st.expander('Agent tasks and handoffs',expanded=False):
        readable_table(store.tasks(rid),hide_index=True,width='stretch')
    with st.expander('Name equivalence checks'):
        st.caption('Alias checks are informational for instruments; the scientist confirms the instrument arrangement. Species, analyte and matrix evidence are reviewed separately.')
        rows=[]
        for kit_id,checks in p.get('name_matching',{}).get('candidates',{}).items():
            for field,check in checks.items():rows.append({'Kit ID':kit_id,'Field':field,**check})
        readable_table(rows)
    with st.expander('Resolve a reviewed agent finding'):
        st.caption('Only a named reviewer with a reason and evidence reference can resolve an agent finding. Deterministic checks must be corrected through their inputs.')
        eligible=[f for f in p.get('findings',[]) if f.get('origin')=='agent' and f.get('id')]
        if eligible:
            with st.form('resolve_finding_'+rid):
                finding=st.selectbox('Finding to resolve',eligible,format_func=lambda f:f['section']+' · '+f['message'][:130])
                actor=st.text_input('Reviewer resolving finding',state['case']['scientific_reviewer'])
                reason=st.text_area('Resolution reason')
                evidence=st.text_input('Supporting evidence reference (source ID, document URL or controlled record)')
                if st.form_submit_button('Record resolution and reopen review'):
                    try:engine_action(lambda engine:engine.resolve_finding(rid,actor,finding['id'],reason,evidence));st.rerun()
                    except Exception as exc:st.error(str(exc))
        else:st.write('No current agent findings eligible for manual disposition.')
    with st.expander('Classify a kit-specific agent finding'):
        agent_findings=[f for f in scoped_findings(p) if f.get('origin')=='agent' and f.get('id')]
        if agent_findings:
            with st.form('classify_finding_'+rid):
                finding=st.selectbox('Finding to classify',agent_findings,format_func=lambda f:f['message'][:150])
                scope=st.selectbox('Finding applies to',['project','selected_kit','alternative_only'])
                kits={k['id']:k['name']+' / '+k['catalog'] for k in p.get('candidates',[])}
                ids=st.multiselect('Kits affected by this finding',list(kits),format_func=lambda cid:kits[cid])
                affects=st.checkbox('This concern undermines the selection rationale itself')
                category=st.selectbox('Finding type',['planning','instrument_availability','instrument_execution','instrument_compatibility','essential_configuration','expected_concentration_unknown','range_coverage_mismatch'])
                instrument_model=st.text_input('Instrument model concerned (if applicable)')
                required_configuration=st.text_input('Specific essential configuration gap (if applicable)')
                actor=st.text_input('Reviewer classifying finding',state['case']['scientific_reviewer'])
                reason=st.text_area('Classification reason')
                evidence=st.text_input('Evidence supporting this classification')
                if st.form_submit_button('Save classification as new review revision'):
                    try:engine_action(lambda engine:engine.classify_finding(rid,actor,finding['id'],scope,ids,affects,reason,evidence,category=category,instrument_model=instrument_model,required_configuration=required_configuration));st.rerun()
                    except Exception as exc:st.error(str(exc))
        else:st.write('No current agent findings to classify.')
    with st.expander('Archived planning revisions'):
        readable_table([{'Revision':r['revision'],'Packet hash':r['packet_hash']} for r in store.revisions(rid)])
    usage=store.usage(rid);st.metric('Recorded inference cost',f'${sum(u.get("cost") or 0 for u in usage if not u.get("usage_unknown")):.4f}')
    if any(u.get('usage_unknown') for u in usage):st.warning('Some failed requests have unknown billed usage. Their budget reservations are not confirmed API charges.')
    if not usage:st.caption('No billed model calls in this run. Desktop build-authoring usage is not available here.')
    with st.expander('Model usage'):st.json(usage)
    for e in reversed(store.events(rid)):
        payload=e['data']
        with st.expander(f'{payload["event"]} · {payload["actor"]} · {payload["timestamp"]}'):
            st.json(payload['data'])


def export_view(rid,p,state,run,cid):
    with st.expander('Client report details'):
        details=p.get('report_details',{})
        with st.form('report_details_'+rid):
            client_name=st.text_input('Client / company name (optional)',details.get('client_name',''))
            project_reference=st.text_input('Client project reference (optional)',details.get('project_reference',''))
            st.caption('Save these before approval. Changes create a report revision; existing decisions remain in history.')
            if st.form_submit_button('Save client report details'):
                try:
                    engine_action(lambda e:e.configure_review(rid,state['case']['scientific_reviewer'],report_details={'client_name':client_name,'project_reference':project_reference}));st.rerun()
                except Exception as exc:st.error(str(exc))
    st.download_button('Download HTML report',html_report(store,rid),file_name=f'{rid[:12]}-report.html',mime='text/html')
    selected=next((display_kit(k) for k in p.get('candidates',[]) if k['id']==p.get('selected_kit')),None)
    manual_url=manual_reference(p,selected)[0] if selected else ''
    attach_manual=st.checkbox('Attach selected kit manual to PDF report and evidence bundle',value=bool(manual_url),disabled=not bool(manual_url),key='attach_manual_'+rid)
    export_options=(packet_hash(p),attach_manual,'client-visual-parity-v16')
    if st.session_state.get('export_options_'+rid)!=export_options:
        st.session_state.pop('pdf_'+rid,None);st.session_state.pop('export_'+rid,None)
        st.session_state['export_options_'+rid]=export_options
    st.caption('Adds the complete manual after the report and embeds the original PDF as an attachment. The evidence ZIP also includes a separate manual PDF and its source/hash record. If retrieval fails, update the direct PDF link or uncheck this option.')
    if st.button('Prepare readable PDF report'):
        st.session_state['pdf_'+rid]=pdf_report(store,rid,include_manual=attach_manual)
    if 'pdf_'+rid in st.session_state:
        st.download_button('Download PDF report',st.session_state['pdf_'+rid],file_name=f'{rid[:12]}-report.pdf',mime='application/pdf')
    if st.button('Prepare evidence bundle (PDF, HTML, JSON and CSV)'):
        st.session_state['export_'+rid]=evidence_zip(store,rid,include_manual=attach_manual)
    if 'export_'+rid in st.session_state:st.download_button('Download evidence ZIP',st.session_state['export_'+rid],file_name=f'{rid[:12]}-evidence.zip',mime='application/zip')
    st.caption('Synthetic or unapproved outputs carry draft/test status. A final package requires current named decisions.')


with st.sidebar:
    st.header('Projects')
    if not PUBLIC_DEMO and st.button('New blank project'):
        st.session_state['case_id']=store.save_case(Intake(title='Untitled project').model_dump());st.rerun()
    if st.button('New mouse TSH test case'):
        st.session_state['case_id']=store.save_case(tsh_case().model_dump());st.rerun()
    cases=store.cases()
    deleted=store.deleted_cases()
    ids=[c['id'] for c in cases]
    cid=st.session_state.get('case_id')
    if cid not in ids:
        cid=ids[-1] if ids else None
        st.session_state['case_id']=cid
    with st.expander(f'Active ({len(cases)})',expanded=True):
        if not cases:st.caption('No active projects. Create a project above or restore one from Deleted.')
        for project in cases:
            selected=project['id']==cid
            if st.button(project['title'],key='active_project_'+project['id'],type='primary' if selected else 'secondary',width='stretch',help='Open project · '+project['id'][:8]):
                st.session_state['case_id']=project['id'];st.rerun()
        if cid:
            st.caption('Selected project · '+str(len(store.runs(cid)))+' saved run(s)')
            if st.button('Move selected project to Deleted',key='delete_project_'+cid,width='stretch',help='Recoverable. Runs and evidence stay with the project.'):
                for run in store.runs(cid):
                    for prefix in ['pdf_','export_']:st.session_state.pop(prefix+run['id'],None)
                store.delete_case(cid);st.session_state.pop('case_id',None);st.rerun()
    with st.expander(f'Deleted ({len(deleted)})',expanded=False):
        if not deleted:st.caption('No deleted projects.')
        for project in deleted:
            st.write(project['title'])
            st.caption('Deleted '+project['deleted_at'][:10])
            if st.button('Restore to Active',key='restore_project_'+project['id'],width='stretch',help='Restore this project with all saved runs and evidence.'):
                store.restore_case(project['id']);st.session_state['case_id']=project['id'];st.rerun()
    page=st.radio('View',['Intake','Agent workspace'] if PUBLIC_DEMO else ['Intake','Agent workspace','Settings'])
    st.caption('Whole-microlitre serial preparation · self-attested roles · no external purchasing or instrument actions')
if page!='Agent workspace':
    st.title('Bioanalytical Advisory')
    st.caption('Platform and kit selection · validation planning · accountable scientific and business decisions')
try:
    if page=='Settings':settings_view()
    elif not cases:st.info('Create a blank project or load the mouse TSH test case to begin.')
    elif page=='Intake':intake_view(cid)
    else:run_view(cid)
except Exception as exc:
    st.error(str(exc))
