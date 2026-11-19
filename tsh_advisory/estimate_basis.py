"""Readable quantities/rates; no public-price or human-attribution claims without records."""
def estimate_rows(packet):
    a=packet.get('cost_assumptions',{});case=packet.get('case',{});v=packet.get('volume',{})
    plates=len(v.get('plate_allocations',[])) or v.get('kits') or 0
    total=a.get('development_hours',0)+a.get('validation_hours',0)
    label=lambda field:'Reviewer estimate' if field in a.get('reviewer_estimates',{}) and a['reviewer_estimates'][field].get('origin')!='system_default' else 'Planning estimate / default'
    rows=[
        {'Input':'Labor','Calculation':f"{a.get('development_hours',0):g} development h + {a.get('validation_hours',0):g} validation h = {total:g} h × ${case.get('labor_rate',35):g}/h",'Basis':'Intake labor rate; '+label('validation_hours')},
        {'Input':'Validation effort','Calculation':f"{plates} plates × {(a.get('labor_hours_per_plate') if a.get('labor_hours_per_plate') is not None else 3.5):g} h/plate"+(' (total override retained)' if 'validation_hours' in a.get('overrides',{}) else ''),'Basis':label('labor_hours_per_plate')},
        {'Input':'Consumables','Calculation':f"{plates} plates × ${a.get('consumables_per_plate',15) or 0:g}/plate"+(' (total override retained)' if 'consumables' in a.get('overrides',{}) else ''),'Basis':label('consumables_per_plate')},
        {'Input':'Shipping','Calculation':f"{v.get('kits',0)} kits × ${a.get('shipping_per_kit',10) or 0:g}/kit"+(' (total override retained)' if 'shipping' in a.get('overrides',{}) else ''),'Basis':label('shipping_per_kit')},
        {'Input':'Contingency','Calculation':f"{a.get('contingency_rate',0)*100:g}% of direct cost plus labor overhead",'Basis':'Recorded planning assumption'},
    ]
    if a.get('class_estimate_mode'):
        rows[1]['Basis']=a.get('labor_timing_basis') or 'Attended labor planning estimate; manual timing not recorded'
        rows[2]['Basis']='Editable class-project basic-consumables benchmark; not a surveyed market average. Kit contents excluded.'
        for row in rows[1:3]:row['Calculation']=row['Calculation'].split(' (total override retained)')[0]
        money=lambda key:'Not estimated' if a.get(key) is None else f"${a[key]:,.2f}"
        rows[3]={'Input':'Shipping: two shipments','Calculation':f"1 kit shipment: {money('kit_shipment_usd')} + 1 matrix shipment: {money('matrix_shipment_usd')}",'Basis':(a.get('shipping_basis') or 'FedEx service, route/zone, weight and packaging assumptions need entry')+'; source: '+a.get('shipping_source','')}
    if a.get('shipping_policy')=='per_kit_plus_matrix':
        rows[3]={'Input':'Shipping','Calculation':f"{v.get('kits',0)} initial/repeat kits × ${a.get('shipping_per_kit',20):g}/kit + ${a.get('matrix_shipment_usd',200):g} matrix shipping",'Basis':'User-provided planning defaults; editable estimates, not a carrier quote'}
    return rows


def summary_cost_chart(lines):
    from decimal import Decimal
    grouped={key:Decimal(0) for key in ('Kits','Labor','Matrix','Instrument','Other incl. contingency')}
    for line in lines:
        name=line['category'];key='Kits' if name in ('Initial kits','Repeat kits') else 'Matrix' if name=='Pooled material' else name if name in ('Labor','Instrument') else 'Other incl. contingency'
        grouped[key]+=Decimal(str(line['usd']))
    return [{'category':k,'usd':str(v)} for k,v in grouped.items()]


def cost_chart_rows(packet):
    """Distinguish unknown costs from explicitly estimated zero in the chart."""
    cost=packet.get('cost',{});a=packet.get('cost_assumptions',{});v=packet.get('volume',{})
    kit=next((k for k in packet.get('candidates',[]) if k['id']==packet.get('selected_kit')),{})
    values={line['category']:float(line['usd']) for line in cost.get('lines',[])}
    unknown=set()
    if kit.get('kit_price') is None or v.get('initial_kits') is None:unknown.add('Initial kits')
    if kit.get('kit_price') is None or v.get('repeat_kits') is None:unknown.add('Repeat kits')
    if a.get('pooled_material') is None:unknown.add('Pooled material')
    if a.get('shipping_policy')=='per_kit_plus_matrix':
        if v.get('kits') is None:unknown.add('Shipping')
    elif a.get('class_estimate_mode') and (a.get('kit_shipment_usd') is None or a.get('matrix_shipment_usd') is None):unknown.add('Shipping')
    if cost.get('instrument_cost_basis',{}).get('usd_per_plate') is None:unknown.add('Instrument')
    for key in unknown:values.setdefault(key,0)
    ordered=sorted(values,key=lambda key:(key in unknown,-values[key],key))
    return [{'category':key.replace('Pooled material','Matrix'),'plot_usd':0 if key in unknown else values[key],'label':'Not estimated' if key in unknown else f"{cost.get('currency','USD')} {values[key]:,.2f}"} for key in ordered]
