"""User-selected experiment scope shared by fixture and live planners."""
from .schemas import Intake,Plan

def pending_work(plan):
    legacy='Assess selectivity, specificity, accuracy/precision, calibration/QC, additional stability and development scouting before laboratory execution.'
    return ['Review selectivity/specificity, any additional stability requirements, development scouting, kit-stock preparation and parameter timing.' if item==legacy else item for item in plan.get('additional_work',[])]

def experiment_design(case: Intake):
    ds=[case.parallel_start_dilution*case.parallel_serial_factor**i for i in range(case.parallel_dilution_count)]
    result=[dict(parameter='Day 0',conditions=['baseline'],wells_per_lot_per_condition=case.day0_wells_per_lot,dilution_factors=[1],material_count=case.lot_count,material_type='lots')]
    if case.short_term_conditions:
        result.append(dict(parameter='Short-term stability',conditions=case.short_term_conditions,wells_per_lot_per_condition=case.stability_wells_per_lot,dilution_factors=[1]*len(case.short_term_conditions),material_count=case.lot_count,material_type='lots'))
    result.append(dict(parameter='Parallelism',conditions=[f'1:{d:g}' for d in ds],wells_per_lot_per_condition=case.parallel_wells_per_dilution,dilution_factors=ds,material_count=case.lot_count,material_type='lots'))
    result.append(dict(parameter='Freeze-thaw',conditions=[f'cycle {i}' for i in range(1,case.freeze_thaw_cycles+1)],wells_per_lot_per_condition=case.freeze_wells_per_endpoint,dilution_factors=[1]*case.freeze_thaw_cycles,material_count=case.lot_count,material_type='lots'))
    if case.long_term_assessments:
        conditions=[f'Assessment {i} · {temperature}' for temperature in (case.long_term_storage_conditions or ['storage temperature to be proposed']) for i in range(1,case.long_term_assessments+1)]
        result.append(dict(parameter='Long-term stability',conditions=conditions,
            wells_per_lot_per_condition=case.long_term_wells_per_assessment,dilution_factors=[1]*len(conditions),
            material_count=case.long_term_material_count,material_type='lots'))
    if case.include_tqc_eqc:
        result.append(dict(parameter='tQC/EQC',conditions=['Day 0 equivalent assessment'],wells_per_lot_per_condition=case.day0_wells_per_lot,dilution_factors=[1],material_count=case.lot_count,material_type='lots'))
    for custom in case.additional_parameters:
        result.append(dict(parameter=custom.name,conditions=custom.conditions,wells_per_lot_per_condition=custom.wells_per_lot_per_condition,dilution_factors=[1]*len(custom.conditions),material_count=custom.lot_count,material_type='lots',separate_conditions=custom.separate_conditions))
    return result

def enforce_design(case: Intake,plan: Plan):
    expected={d['parameter']:d for d in experiment_design(case)}
    existing={e.parameter:e for e in plan.experiments}
    missing=set(expected)-set(existing)
    if missing:raise ValueError('Planner omitted requested parameters: '+', '.join(sorted(missing)))
    for name,design in expected.items():
        e=existing[name]
        if e.wells_per_lot_per_condition!=design['wells_per_lot_per_condition'] or len(e.conditions)!=len(design['conditions']):
            raise ValueError(name+' plan does not match requested replicate/assessment counts.')
        e.material_count=design['material_count'];e.material_type=design['material_type']
        if case.calculation_revision=='lot-planning-v3':e.handling_ul_per_lot=0
        e.controls_per_run=case.nonpa_controls
        e.control_breakdown={}
        e.control_layout_basis='Intake planning count for assay standards/QCs/blanks; kit-specific component layout requires review.'
        if name in {p.name for p in case.additional_parameters}:
            e.conditions=design['conditions'];e.dilution_factors=design['dilution_factors'];e.separate_conditions=design['separate_conditions']
            e.independent_runs=1
        if name=='Parallelism':
            e.conditions=design['conditions'];e.dilution_factors=design['dilution_factors']
        elif name=='Short-term stability':e.conditions=design['conditions']
        elif name=='Long-term stability' and case.long_term_storage_conditions:e.conditions=design['conditions']
    return plan
