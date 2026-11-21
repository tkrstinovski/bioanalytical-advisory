"""Classify saved intake changes and rebuild the requested design without model calls."""
import copy
from .schemas import Intake,Plan,Experiment
from .design import experiment_design,enforce_design
from .names import matches

SCOPE_FIELDS={'analyte','species','species_strain','matrix','intended_use','regulatory_use','instruments'}

def preview(store,rid):
    run=store.run(rid);state=run['data'];saved=store.case(run['case_id'])
    baseline=state.get('applied_intake')
    if baseline is None:
        started=next((e['data']['data']['case']['data'] for e in store.events(rid) if e['data']['event']=='run_started'),state['case'])
        baseline=started
    baseline=Intake.model_validate(baseline).model_dump();current=Intake.model_validate(saved['data']).model_dump()
    changes={field:{'previous':baseline[field],'current':current[field]} for field in current if baseline[field]!=current[field]}
    review=[]
    for field in changes.keys() & SCOPE_FIELDS:
        old,new=baseline[field],current[field]
        if field=='species_strain' and not str(new).strip():continue
        equivalent=matches(old,new,field) if field in ('analyte','species','matrix') else str(old).strip().casefold()==str(new).strip().casefold()
        if not equivalent:review.append(field)
    return {'saved_version':run['case_version'],'current_version':saved['version'],'version_changed':saved['version']!=run['case_version'],'changes':changes,'review_fields':sorted(review),'current_intake':current}

def reconcile_plan(old_case,new_case,plan):
    """Keep saved planning choices where applicable; intake counts/conditions are authoritative."""
    result=plan.model_copy(deep=True);old={e.parameter:e for e in result.experiments};experiments=[]
    lts_unchanged=all(getattr(old_case,f)==getattr(new_case,f) for f in ('long_term_assessments','long_term_storage_conditions'))
    for design in experiment_design(new_case):
        name=design['parameter'];existing=old.get(name)
        if existing:
            experiment=existing.model_copy(deep=True)
            preserve_lts=name=='Long-term stability' and lts_unchanged and len(existing.conditions)==len(design['conditions'])
            if not preserve_lts:experiment.conditions=copy.deepcopy(design['conditions'])
            experiment.wells_per_lot_per_condition=design['wells_per_lot_per_condition']
            experiment.dilution_factors=list(design['dilution_factors'])
            experiment.material_count=design['material_count'];experiment.material_type='lots'
            if 'separate_conditions' in design:experiment.separate_conditions=design['separate_conditions']
        else:
            experiment=Experiment(**design,handling_ul_per_lot=0,controls_per_run=new_case.nonpa_controls,
                sharing_group='long_term' if name=='Long-term stability' else 'core_validation',independent_runs=1,
                timing='Intake-defined conditions; scientist confirms timing and compatibility with shared plates.',
                rationale='Created from updated intake by deterministic reconciliation; no additional research or validated performance is implied.')
        experiment.handling_ul_per_lot=0;experiment.controls_per_run=new_case.nonpa_controls
        experiments.append(experiment)
    result.experiments=experiments
    preserved_lts=next((list(e.conditions) for e in experiments if e.parameter=='Long-term stability'),None) if lts_unchanged else None
    result=enforce_design(new_case,result)
    if preserved_lts:
        next(e for e in result.experiments if e.parameter=='Long-term stability').conditions=preserved_lts
    return result
