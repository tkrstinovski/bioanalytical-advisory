"""Structured resolution predicates; unknown concerns stay open for human review."""

CHECKS={'MISSING_MATRIX_PRICE','MISSING_KIT_PRICE','MISSING_SAMPLE_INPUT','STUDY_VOLUME','PLATE_CAPACITY','INTAKE_PARAMETER_OMITTED','COST_INPUTS'}


def resolution_for(f,packet):
    code=f.get('issue_code','')
    kit=next((k for k in packet.get('candidates',[]) if k['id']==packet.get('selected_kit')),None)
    if f.get('candidate_ids') and kit and kit['id'] not in f['candidate_ids']:return None
    remains=None
    if code=='MISSING_MATRIX_PRICE':remains=packet.get('cost_assumptions',{}).get('pooled_material') is None
    elif code=='COST_INPUTS':remains=not packet.get('cost') or packet['cost'].get('incomplete',True)
    elif code=='MISSING_KIT_PRICE':remains=not kit or kit.get('kit_price') is None
    elif code=='MISSING_SAMPLE_INPUT':remains=not kit or kit.get('well_input_ul') is None
    elif code=='STUDY_VOLUME':remains=packet.get('study',{}).get('status')!='pass'
    elif code=='PLATE_CAPACITY':
        plates=packet.get('volume',{}).get('plate_allocations',[])
        if plates:remains=any(p.get('free',0)<0 for p in plates)
    elif code=='INTAKE_PARAMETER_OMITTED':
        from .design import experiment_design
        from .schemas import Intake
        required={e['parameter'] for e in experiment_design(Intake.model_validate(packet['case']))}
        actual={e['parameter'] for e in packet.get('plan',{}).get('experiments',[])}
        remains=not required<=actual
    if remains is False:return 'Current deterministic '+code+' check no longer applies; corrected input/calculation retained in this revision.'
    if code not in CHECKS and f.get('scope_class') in ('execution_detail','out_of_scope'):
        return 'Outside the intake-defined planning scope; original finding preserved as a historical execution consideration.'
    return None
