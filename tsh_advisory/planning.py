"""Complete run ledger and scope-linked costing for v3."""
from .store import digest

def plate_rows(volume):
    return [{'Plate':p['id'],'Purpose':p['phase'],'Control/QC wells':p['controls'],
             'Sample allocations':'; '.join(a['parameter']+' / '+a.get('condition','')+' / run '+str(a.get('independent_run',1))+': '+str(a['sample_wells']) for a in p['allocations']),
             'Spare wells':p['free']} for p in volume.get('plate_allocations',[])]

def allocate_plates(rows,case,kit):
    controls=case.pa_blank_wells+case.pa_standard_levels*case.pa_standard_replicates+case.qc_levels*case.qc_wells_per_level
    plates=[dict(id=f'PA-{i+1}',phase='initial',group='core_validation',controls=controls,free=kit.wells_per_kit-controls,allocations=[]) for i in range(case.precision_accuracy_plates)]
    for row in rows:
        row['plate_ids']=[];added={'initial':0,'repeat':0}
        separate=row['parameter']=='Long-term stability' or row.get('separate_conditions',False)
        conditions=row['conditions'] if separate else ['Combined compatible conditions']
        wells=row['initial_wells']//row['independent_runs']//len(conditions)
        for phase in ['initial']+[f'repeat-{i+1}' for i in range(case.complete_repeats)]:
            for condition in conditions:
                for run in range(row['independent_runs']):
                    remaining=wells
                    eligible=[p for p in plates if phase=='initial' and not separate and row['sharing_group']=='core_validation' and p['id'].startswith('PA-') and not p['allocations'] and p['free']>0]
                    while remaining:
                        if eligible:plate=eligible.pop(0)
                        else:
                            capacity=kit.wells_per_kit-case.nonpa_controls
                            if capacity<=0:raise ValueError('Controls leave no sample capacity.')
                            plate=dict(id=f'{phase.upper()}-{len(plates)+1}',phase=phase,group=row['parameter'],controls=case.nonpa_controls,free=capacity,allocations=[])
                            plates.append(plate);added['initial' if phase=='initial' else 'repeat']+=1
                        n=min(remaining,plate['free']);remaining-=n;plate['free']-=n
                        plate['allocations'].append(dict(parameter=row['parameter'],sample_wells=n,condition=condition,independent_run=run+1))
                        row['plate_ids'].append(plate['id'])
        row.update(initial_kits=added['initial'],repeat_kits=added['repeat'],kits=sum(added.values()))
        row['control_wells']=sum(p['controls'] for p in plates if p['id'] in row['plate_ids'])
    return plates

def scope_costs(case,kit,volume,assumptions):
    a=assumptions.model_copy(deep=True);a.overhead_rate=.15;a.gross_margin=0.0;n=len(volume.get('plate_allocations',[]))
    if a.shipping_policy=='per_kit_plus_matrix':
        if a.shipping_per_kit is None:a.shipping_per_kit=20
        if a.matrix_shipment_usd is None:a.matrix_shipment_usd=200
    for field,default in [('labor_hours_per_plate',3.5),('reader_hours_per_plate',.5),('consumables_per_plate',15),('shipping_per_kit',10)]:
        if getattr(a,field) is None:setattr(a,field,default)
    a.validation_hours=n*a.labor_hours_per_plate;a.instrument_hours=n*a.reader_hours_per_plate
    a.consumables=n*a.consumables_per_plate;a.shipping=(volume.get('kits') or 0)*a.shipping_per_kit
    if a.class_estimate_mode:
        a.shipping=(a.kit_shipment_usd or 0)+(a.matrix_shipment_usd or 0)
        if kit.attended_minutes_per_plate is not None and kit.labor_timing_source:
            a.labor_hours_per_plate=(kit.attended_minutes_per_plate+a.setup_minutes_per_plate+a.review_minutes_per_plate)/60
            a.validation_hours=n*a.labor_hours_per_plate
            a.labor_timing_basis=f'{kit.attended_minutes_per_plate:g} attended min/plate from {kit.labor_timing_source}; {a.setup_minutes_per_plate:g} setup + {a.review_minutes_per_plate:g} review min/plate are planning allowances; confirm no overlap.'
        else:
            a.labor_timing_basis='Attended labor is an editable planning estimate: source-backed attended timing is not recorded. Elapsed/incubation time is not treated as hands-on labor.'
    if a.shipping_policy=='per_kit_plus_matrix':
        a.shipping=(volume.get('kits') or 0)*a.shipping_per_kit+a.matrix_shipment_usd
        a.shipping_basis='User-provided planning defaults: shipping per initial/repeat kit plus one matrix shipping allowance; not a carrier quote.'
        a.shipping_source='User-provided project assumption'
    a.costing_basis='Plate-based planning estimates. Incubation elapsed time is not labor or reader time; confirm per-plate assumptions.'
    for key,value in a.overrides.items():
        if (a.class_estimate_mode and key in ('shipping','validation_hours','consumables')) or (a.shipping_policy=='per_kit_plus_matrix' and key=='shipping'):continue
        if key in ('validation_hours','instrument_hours','shipping','consumables'):setattr(a,key,value)
    a=type(a).model_validate(a.model_dump())
    scope=digest([case.model_dump(),kit.id,kit.assay_duration,kit.well_input_ul,volume.get('plate_allocations')])
    return a,scope
