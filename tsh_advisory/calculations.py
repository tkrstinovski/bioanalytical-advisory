"""Deterministic units, independent volume pools, per-run capacity and Decimal costs."""
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from .schemas import Intake, Candidate, Plan, CostAssumptions
from .cost_policy import instrument_plate_rate

def money(value):
    return str(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))

def study_volume(case: Intake, kit: Candidate):
    dilution=(case.study_dilution or case.parallel_start_dilution) if case.calculation_revision=='lot-planning-v3' else kit.dilution_factor
    if any(x is None for x in [kit.well_input_ul, dilution, kit.handling_ul, case.available_ul]):
        return {'status':'unresolved', 'reason':'Assay input, dilution, handling or available study volume is missing.'}
    theoretical=case.initial_wells*kit.well_input_ul/dilution
    initial=theoretical;recipe=[]
    if case.calculation_revision=='lot-planning-v3':
        if kit.well_input_ul<10:return {'status':'unresolved','reason':'Assay plating below 10 µL requires a reviewed alternative preparation procedure.'}
        from .study_preparation import study_recipe
        recipe=study_recipe(dilution,case.initial_wells*kit.well_input_ul,case.preparation_leeway_ul)
        initial=recipe[0]['source_ul']
    repeat=initial*case.complete_repeats
    total=initial+repeat+kit.handling_ul
    return dict(status='pass' if total<=case.available_ul else 'fail',initial_ul=initial,repeat_ul=repeat,
        handling_ul=kit.handling_ul,total_ul=total,available_ul=case.available_ul,remaining_ul=case.available_ul-total,dilution_factor=dilution,dilution_basis='reviewer override' if case.study_dilution is not None else 'lowest parallelism dilution' if case.calculation_revision=='lot-planning-v3' else 'kit record',
        theoretical_neat_ul_per_set=theoretical,preparation=recipe,minimum_transfer_ul=10 if recipe else None,
        feasibility_basis='Pipettable preparation including reserve and independent complete repeats; dilution suitability requires scientist review.' if recipe else 'Historical neat-equivalent estimate')

def validation_volume(case: Intake, kit: Candidate, plan: Plan):
    if kit.well_input_ul is None:
        return {'status':'unresolved','rows':[],'reason':'Kit-specific assay input is unknown.'}
    rows=[]; total_wells=0; kits=0
    # Every experiment occupies independent runs, each with its own controls and repeat run.
    for e in plan.experiments:
        if case.calculation_revision in ('lot-planning-v2','lot-planning-v3'):
            e=e.model_copy(deep=True)
            e.material_type='lots'
            e.handling_ul_per_lot=0 if case.calculation_revision=='lot-planning-v3' else 15
            if e.parameter!='Parallelism':e.dilution_factors=[case.parallel_start_dilution]*len(e.conditions)
        if len(e.conditions)!=len(e.dilution_factors) or any(d<1 for d in e.dilution_factors):
            raise ValueError('Each condition must have a positive dilution factor of at least one.')
        wells_per_lot=e.wells_per_lot_per_condition*len(e.conditions)
        initial=sum((e.wells_per_lot_per_condition*kit.well_input_ul+case.preparation_leeway_ul)/d for d in e.dilution_factors)
        repeat=initial*case.complete_repeats
        # This is a preparation allowance, not a claim that ideal per-well division models serial dilution.
        perlot=initial+repeat+e.handling_ul_per_lot
        material_count=e.material_count or case.lot_count
        sample_wells=wells_per_lot*material_count
        controls=case.nonpa_controls
        if any(n<0 for n in e.control_breakdown.values()):raise ValueError('Negative control well count.')
        capacity=kit.wells_per_kit-controls if controls is not None else None
        if capacity is not None and capacity<1:
            raise ValueError('Controls leave no sample capacity in this kit format.')
        # Long-term assessments occur on separate dates: never pack them onto one initial kit.
        groups=len(e.conditions) if e.parameter=='Long-term stability' else 1
        wells_per_group=sample_wells//groups
        minimum_initial=max(groups,e.independent_runs,ceil(sample_wells/kit.wells_per_kit))
        primary_plates=max(e.independent_runs,groups*ceil(wells_per_group/capacity)) if capacity else None
        repeat_kits=primary_plates*case.complete_repeats if primary_plates is not None else None
        plates=primary_plates+repeat_kits if primary_plates is not None else None
        control_wells=plates*controls if plates is not None else None
        total_wells+=sample_wells*(1+case.complete_repeats)+(control_wells or 0)
        kits+=plates or 0
        parallelism=[]
        if e.parameter=='Parallelism':
            transfer_to_next=0
            for index in reversed(range(len(e.dilution_factors))):
                factor=e.dilution_factors[index]
                wells_volume=e.wells_per_lot_per_condition*kit.well_input_ul
                needed=wells_volume+case.preparation_leeway_ul+transfer_to_next+e.dilution_dead_ul
                ratio=factor/e.dilution_factors[index-1] if index else factor
                if ratio<1:raise ValueError('Parallelism series must be increasing.')
                # Matrix/previous-dilution withdrawals are whole uL; never round down.
                transfer_in=max(10,ceil(needed/ratio),ceil(10/(ratio-1)) if ratio>1 else 0)
                prepared=transfer_in*ratio
                parallelism.insert(0,dict(dilution=f'1:{factor:g}',wells_per_lot=e.wells_per_lot_per_condition,
                    source='Neat serum' if index==0 else f'Previous dilution 1:{e.dilution_factors[index-1]:g}',
                    assay_input_ul_per_well=kit.well_input_ul,prepared_for_wells_ul=wells_volume,
                    transfer_to_next_ul=transfer_to_next,total_to_prepare_ul=prepared,
                    source_or_previous_dilution_ul=transfer_in,diluent_ul=prepared-transfer_in,
                    retained_after_transfer_ul=prepared-transfer_to_next,dead_volume_ul=e.dilution_dead_ul,
                    preparation_leeway_ul=case.preparation_leeway_ul,
                    neat_equivalent_for_wells_ul=wells_volume/factor))
                transfer_to_next=transfer_in
            initial=parallelism[0]['source_or_previous_dilution_ul']
            repeat=initial*case.complete_repeats
            perlot=initial+repeat+e.handling_ul_per_lot
        initial=ceil(initial)
        if case.calculation_revision=='lot-planning-v3':
            if e.parameter!='Parallelism':initial=sum(ceil((e.wells_per_lot_per_condition*kit.well_input_ul+case.preparation_leeway_ul)/d) for d in e.dilution_factors)
            initial*=e.independent_runs;sample_wells*=e.independent_runs
        repeat=initial*case.complete_repeats
        handling=ceil(e.handling_ul_per_lot)
        perlot=initial+repeat+handling
        rows.append(dict(parameter=e.parameter,conditions=e.conditions,initial_wells=sample_wells,
            repeat_wells=sample_wells*case.complete_repeats,initial_ul_per_lot=initial,repeat_ul_per_lot=repeat,
            losses_ul_per_lot=handling,total_ul_per_lot=perlot,total_ul_all_lots=perlot*material_count,
            material_count=material_count,material_type=e.material_type,
            controls_per_run=controls,control_breakdown=e.control_breakdown,control_layout_basis=e.control_layout_basis,
            control_wells=control_wells,initial_kits=primary_plates,repeat_kits=repeat_kits,kits=plates,
            sharing_group=e.sharing_group,independent_runs=e.independent_runs,separate_conditions=e.separate_conditions,
            preparation_leeway_ul=case.preparation_leeway_ul,
            minimum_initial_kits=minimum_initial,minimum_repeat_kits=minimum_initial*case.complete_repeats,
            parallelism_calculation=parallelism,timing=e.timing,rationale=e.rationale))
    # P/A layout replaces, rather than adds, the general 24-well planning allowance.
    pa_standards=case.pa_standard_levels*case.pa_standard_replicates
    pa_controls=case.pa_blank_wells+pa_standards+case.qc_levels*case.qc_wells_per_level
    pa_capacity=kit.wells_per_kit-pa_controls
    if pa_capacity<0:raise ValueError('Standards/blanks and precision/accuracy QCs exceed plate capacity.')
    plate_records=[dict(id=f'PA-{i+1}',phase='initial',group='core_validation',controls=pa_controls,free=pa_capacity,allocations=[]) for i in range(case.precision_accuracy_plates)]
    def allocate(row,phase,wells):
        if not wells:return []
        group=row['sharing_group']
        if group=='review_required':group=row['parameter']
        eligible=[p for p in plate_records if p['phase']==phase and p['group']==group and p['free']>0
            and all(a['parameter']==row['parameter'] for a in p['allocations'])]
        ids=[]
        while wells:
            if eligible:plate=eligible.pop(0)
            else:
                capacity=kit.wells_per_kit-case.nonpa_controls
                if capacity<=0:raise ValueError('Assay controls leave no sample capacity.')
                plate=dict(id=f'{phase.upper()}-{len(plate_records)+1}',phase=phase,group=group,controls=case.nonpa_controls,free=capacity,allocations=[])
                plate_records.append(plate)
            n=min(wells,plate['free']);plate['free']-=n;wells-=n
            plate['allocations'].append({'parameter':row['parameter'],'sample_wells':n});ids.append(plate['id'])
        return ids
    for row in rows:
        if row['parameter']=='Long-term stability':
            row['plate_ids']=[];continue
        before=len(plate_records)
        initial_ids=allocate(row,'initial',row['initial_wells'])
        initial_added=len(plate_records)-before
        repeat_ids=[];before=len(plate_records)
        # Each complete repeat has its own plate group; it does not repeat P/A QC qualification.
        for attempt in range(case.complete_repeats):
            repeat_ids+=allocate(row,f'repeat-{attempt+1}',row['initial_wells'])
        repeat_added=len(plate_records)-before
        row.update(initial_kits=initial_added,repeat_kits=repeat_added,kits=initial_added+repeat_added,
            plate_ids=initial_ids+repeat_ids,kit_count_basis='Additional kits after sharing; see plate allocation for all plates used.')
    long_rows=[r for r in rows if r['parameter']=='Long-term stability']
    if case.calculation_revision=='lot-planning-v3':
        from .planning import allocate_plates
        plate_records=allocate_plates(rows,case,kit);long_rows=[]
    pa_row=dict(parameter='Precision and Accuracy',conditions=[f'{case.precision_accuracy_plates} plates; {case.pa_blank_wells} blank wells + {case.pa_standard_levels} standards x {case.pa_standard_replicates} wells + {case.qc_levels} QCs x {case.qc_wells_per_level} wells'],
        initial_wells=case.precision_accuracy_plates*pa_controls,repeat_wells=0,
        initial_ul_per_lot=None,repeat_ul_per_lot=None,losses_ul_per_lot=None,total_ul_per_lot=None,total_ul_all_lots=0,
        material_count=None,material_type='Kit stock',controls_per_run=pa_controls,
        initial_kits=case.precision_accuracy_plates,repeat_kits=0,kits=case.precision_accuracy_plates,
        plate_ids=[p['id'] for p in plate_records[:case.precision_accuracy_plates]],parallelism_calculation=[],
        timing=f'{case.precision_accuracy_plates} independent qualification plates; no automatic repeat.',rationale=f'{case.pa_blank_wells} blanks + {pa_standards} standards + {case.qc_levels*case.qc_wells_per_level} QCs per plate; controls counted once.',
        matrix_volume_status='Included in the kits; no additional kit-stock material requirement or cost.')
    initial_total=sum(p['phase']=='initial' for p in plate_records)+sum(r['initial_kits'] or 0 for r in long_rows)
    repeat_total=sum(p['phase']!='initial' for p in plate_records)+sum(r['repeat_kits'] or 0 for r in long_rows)
    rows.insert(0,pa_row)
    lot_rows=[r for r in rows if r['material_type']=='lots']
    lot_requirements=[]
    for i in range(max((r['material_count'] for r in lot_rows),default=0)):
        subtotal=sum(r['total_ul_per_lot'] for r in lot_rows if i<r['material_count'])
        lot_requirements.append(dict(lot=f'Lot {i+1}',parameter_requirement_ul=subtotal,aliquotting_loss_ul=200,total_required_ul=subtotal+200))
    other_matrix=sum(r['total_ul_all_lots'] or 0 for r in rows if r['material_type']=='animals')
    complete=all(r['kits'] is not None for r in rows)
    return dict(status='proposed',calculation_version=case.calculation_revision if case.calculation_revision in ('lot-planning-v2','lot-planning-v3') else 'matrix-plus200-v1',plate_allocations=plate_records,
        pa_controls_per_plate=pa_controls,pa_qc_wells_per_plate=case.qc_levels*case.qc_wells_per_level,
        rows=rows,lot_requirements=lot_requirements,aliquotting_loss_ul_per_lot=200,
        total_ul_per_lot=max((r['total_required_ul'] for r in lot_requirements),default=0),
        total_ul_all_lots=sum(r['total_required_ul'] for r in lot_requirements)+other_matrix,matrix_totals_complete=True,kits=initial_total+repeat_total if complete else None,
        initial_kits=initial_total if complete else None,
        repeat_kits=repeat_total if complete else None,
        minimum_initial_kits=initial_total,minimum_repeat_kits=repeat_total,
        control_layouts_complete=complete,total_wells=sum(p['controls']+sum(a['sample_wells'] for a in p['allocations']) for p in plate_records)+sum(r['initial_wells']+r['repeat_wells']+(r['control_wells'] or 0) for r in long_rows) if complete else None,
        initial_sample_wells=sum(r['initial_wells'] for r in rows if r is not pa_row),
        limitations=['Proposed preparation allowances require scientific review.',
            'Matrix used for controls, serial dilution preparation and development scouting require explicit additional allocations.',
            'One kit per plate assumed; compatible parameters share wells on planned plates, without credit for reusing consumed reagents.'])

def cost_estimate(case: Intake, kit: Candidate, volume: dict, a: CostAssumptions):
    a=a.model_copy(update={'overhead_rate':.15,'gross_margin':0.0})
    D=lambda n:Decimal(str(n))
    rate=instrument_plate_rate(kit.platform)
    plates=len(volume['plate_allocations']) if volume.get('plate_allocations') else volume.get('kits')
    instrument=D(rate or 0)*D(plates or 0)
    labor=D(case.labor_rate)*(D(a.development_hours)+D(a.validation_hours))
    lines=[('Labor',labor),('Instrument',instrument),
        ('Shipping',D(a.shipping)),('Consumables',D(a.consumables))]
    unresolved=[]
    if a.shipping_policy=='per_kit_plus_matrix' and volume.get('kits') is None:
        unresolved.append('Kit count is required to calculate per-kit shipping.')
    if a.class_estimate_mode and a.shipping_policy=='legacy':
        if a.kit_shipment_usd is None:unresolved.append('FedEx estimate for one kit shipment is not entered.')
        if a.matrix_shipment_usd is None:unresolved.append('FedEx estimate for one matrix shipment is not entered.')
        if not a.shipping_basis:unresolved.append('Shipping estimate basis (service, route/zone, package weight and packaging assumptions) is not recorded.')
    if rate is None:unresolved.append('Instrument per-plate rate is not configured for selected platform: '+kit.platform)
    if plates is None:unresolved.append('Instrument charges require a calculated plate count.')
    if kit.kit_price is None: unresolved.append('Kit price requires public evidence or an accepted planning estimate.')
    elif volume.get('kits') is None:unresolved.append('Kit quantities require a documented control layout. Minimum kit counts are lower bounds, not a complete purchase estimate.')
    else:
        lines.append(('Initial kits',D(kit.kit_price)*D(volume['initial_kits'])))
        lines.append(('Repeat kits',D(kit.kit_price)*D(volume['repeat_kits'])))
    if a.pooled_material is None: unresolved.append('Pooled material procurement estimate is missing.')
    else: lines.append(('Pooled material',D(a.pooled_material)))
    direct=sum((v for _,v in lines),D(0)); overhead=labor*D(a.overhead_rate)
    contingency=(direct+overhead)*D(a.contingency_rate)
    internal=direct+overhead+contingency; price=internal/(D(1)-D(a.gross_margin))
    def price_for(lab=labor,inst=instrument,kit_cost=D(kit.kit_price or 0)*D(volume.get('kits') or 0),margin=D(a.gross_margin)):
        other=D(a.shipping)+D(a.consumables)+D(a.pooled_material or 0)
        return ((lab+inst+kit_cost+other+lab*D(a.overhead_rate))*(1+D(a.contingency_rate)))/(1-margin)
    sensitivity=[]
    reagent=D(kit.kit_price or 0)*D(volume.get('kits') or 0)
    for label,low,high in [('Reagent cost ±30%',price_for(kit_cost=reagent*D('.7')),price_for(kit_cost=reagent*D('1.3'))),
        ('Labor hours ±25%',price_for(lab=labor*D('.75')),price_for(lab=labor*D('1.25'))),
        ('Instrument charges ±50%',price_for(inst=instrument*D('.5')),price_for(inst=instrument*D('1.5')))]:
        sensitivity.append(dict(assumption=label,lower_delta=money(low-price),higher_delta=money(high-price)))
    lines.extend([('Overhead on labor',overhead),('Contingency',contingency)])
    basis=internal if case.budget_basis=='internal_cost' else price
    exceeded=case.budget_ceiling is not None and basis>D(case.budget_ceiling)
    return dict(lines=[{'category':k,'usd':money(v)} for k,v in lines],internal_cost=money(internal),client_price=money(price),
        instrument_cost_basis={'platform':kit.platform,'usd_per_plate':rate,'plates':plates,'source':'User-provided internal rate; initial and repeat plates included.'},
        gross_margin=a.gross_margin,currency=a.currency,incomplete=bool(unresolved),unresolved=unresolved,
        budget_exceeded=exceeded,budget_basis=case.budget_basis,
        assumptions=a.model_dump(),price_is_estimate=True,
        sensitivity=sensitivity,
        scenarios={'lower_assumption_price':money(price_for(lab=labor*D('.75'),kit_cost=reagent*D('.7'))),
            'base_price':money(price),'higher_assumption_price':money(price_for(lab=labor*D('1.25'),kit_cost=reagent*D('1.3'))),
            'meaning':'Illustrative labor/reagent scenarios, not statistical confidence intervals; kit quantities remain fixed for this design.'},
        study_analysis={'sample_count':case.study_count,'initial_wells_per_sample':case.initial_wells,
            'repeat_wells_per_sample':case.initial_wells*case.complete_repeats,'estimate_status':'Separate study-batch control and labor design required; not included in validation price.'})
