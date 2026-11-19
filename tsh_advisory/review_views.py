"""Human-readable scientific views; underlying records remain unchanged."""
import streamlit as st
from .design import pending_work
from .tables import readable_table

def label(value):
    return str(value).replace('_',' ').strip().capitalize()

def protocol_rows(plan,case,volume=None):
    rows=[]
    for e in (plan or {}).get('experiments',[]):
        conditions=e.get('conditions',[])
        count=e.get('material_count') or case.get('lot_count',0)
        computed=next((r for r in (volume or {}).get('rows',[]) if r['parameter']==e.get('parameter')), {})
        rows.append({'Parameter':e.get('parameter','Not specified'),
            'Conditions or endpoints':('1 assessment' if e.get('parameter')=='tQC/EQC' else f'{len(conditions)} dilutions per lot' if e.get('parameter')=='Parallelism' else '; '.join(str(c) for c in conditions)),
            'Lots':count,'Material':'lots','Wells per lot per condition':e.get('wells_per_lot_per_condition'),
            'Initial sample wells':computed.get('initial_wells',count*e.get('wells_per_lot_per_condition',0)*len(conditions))})
    return rows

def protocol_view(plan,case,volume=None):
    if not plan:
        st.info('The validation protocol has not been proposed yet.')
        return
    st.caption('Proposed method and validation plan · scientific review required · no laboratory validation results')
    experiments=plan.get('experiments',[])
    cols=st.columns(3)
    cols[0].metric('Validation parameters',len(experiments))
    cols[1].metric('Distinct pooled lots',case.get('lot_count','Not specified'))
    cols[2].metric('Complete repeats reserved',case.get('complete_repeats','Not specified'))
    st.markdown('#### Experiment overview')
    if volume and volume.get('pa_controls_per_plate'):
        st.write(f"Precision and Accuracy: {case.get('precision_accuracy_plates',6)} initial plates with {volume['pa_controls_per_plate']} control/QC wells per plate, prepared from kit stock. Each plate hosts at most one other parameter. Each parameter has its own repeat plate allocation; long-term assessments stay separate.")
    rows=protocol_rows(plan,case,volume)
    if rows:
        readable_table(rows,hide_index=True,width='stretch',row_height=72)
    else:
        st.warning('No experiments have been specified.')
    st.caption('Calculated material requirements appear in the Volumes tab.')


def candidate_details(kit):
    cols=st.columns(3)
    cols[0].metric('Platform',kit.get('platform','Unresolved'))
    cols[1].metric('Catalog number',kit.get('catalog','Unresolved'))
    price=kit.get('kit_price')
    cols[2].metric('Public price estimate',f'${price:,.2f}' if price is not None else 'Quote required')
    st.write('**Exact instrument model:**',kit.get('required_model') or 'Reviewer decision required')
    st.write('**Documentation version:**',kit.get('documentation_version','Unresolved'))
    eligibility=kit.get('eligibility',{})
    st.write('**Scientific eligibility:**',label(eligibility.get('status','unresolved')))
    for reason in eligibility.get('reasons',[]):st.warning(reason)
    st.markdown('**Claim and evidence trace**')
    for gate,e in kit.get('evidence',{}).items():
        st.markdown('**'+label(gate)+'** — '+str(e.get('claim','')))
        st.caption('Source '+str(e.get('source_id','Unresolved'))+' · '+str(e.get('locator','')))
        st.write(e.get('quote',''))
    for limitation in kit.get('limitations',[]):st.warning(limitation)
