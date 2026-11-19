"""Scientist-facing estimate editor with server-owned rows and genuine-change detection."""
import math,json

FIELDS=[('kit_price','Selected kit price','USD/kit',None,'Public price or reviewer estimate'),('pooled_material','Matrix purchase estimate','USD total',None,'Reviewer estimate for all validation lots'),('development_hours','Development effort','hours/project',0,'Planning allowance'),('labor_hours_per_plate','Fallback attended labor','hours/plate',2,'Used only when source-backed attended timing is unavailable'),('setup_minutes_per_plate','Setup allowance','minutes/plate',15,'Reviewer allowance; confirm no overlap with kit hands-on time'),('review_minutes_per_plate','Data/QC review allowance','minutes/plate',30,'Reviewer allowance'),('consumables_per_plate','Basic consumables benchmark','USD/plate',15,'Class-project benchmark; kit contents excluded'),('kit_shipment_usd','FedEx kit shipment','USD/one shipment',None,'One shipment for all kits'),('matrix_shipment_usd','FedEx matrix shipment','USD/one shipment',None,'One shipment for matrix'),('shipping_basis','Shipping assumptions','text','','Service, route/zone, weight, packaging and rate date'),('shipping_source','Shipping rate source','URL','https://www.fedex.com/en-us/shipping/rate-changes.html','FedEx public rate source'),('contingency_rate','Contingency','%',.1,'Applied to direct costs plus labor overhead')]
TEXT={'shipping_basis','shipping_source'}
FIELDS=[item for item in FIELDS if item[0] not in ('kit_shipment_usd','matrix_shipment_usd','shipping_basis','shipping_source')]
FIELDS[7:7]=[('shipping_per_kit','Kit shipping allowance','USD/kit',20,'User-provided default; applies to initial and repeat kits'),('matrix_shipment_usd','Matrix shipping allowance','USD total',200,'User-provided default for matrix shipping')]
FIELDS=[(field,label,units,3.5 if field=='labor_hours_per_plate' else default,basis) for field,label,units,default,basis in FIELDS]

def rows(packet):
    a=packet.get('cost_assumptions',{});kit=next((k for k in packet.get('candidates',[]) if k['id']==packet.get('selected_kit')),{});result=[]
    for field,label,units,default,basis in FIELDS:
        value=kit.get(field) if field=='kit_price' else a.get(field,default)
        if field in ('shipping_per_kit','matrix_shipment_usd') and a.get('shipping_policy')!='per_kit_plus_matrix':value=default
        if field=='contingency_rate' and value is not None:value*=100
        saved=a.get('reviewer_estimates',{}).get(field,{})
        if saved.get('origin')!='cost_table':saved={}
        if saved:
            kind='Reviewer allowance' if field in ('development_hours','setup_minutes_per_plate','review_minutes_per_plate','contingency_rate') else 'Reviewer estimate'
            basis=kind+'; saved by '+saved['actor']+' on '+saved['timestamp']
        elif field in ('setup_minutes_per_plate','review_minutes_per_plate'):
            basis='Default planning allowance; confirm no overlap with kit hands-on time'
        if field=='kit_price' and kit.get('cell_evidence',{}).get('kit_price',{}).get('supporting_document_id'):
            record=kit['cell_evidence']['kit_price']
            basis='Scientist-reviewed uploaded document passage' if record.get('source_id') else 'Reviewer estimate; supporting document attached without a verified passage'
        result.append({'Input':label,'Value':'' if value is None else value,'Units':units,'Basis':basis,'_field':field,'_saved':saved})
        if field=='labor_hours_per_plate' and kit.get('attended_minutes_per_plate') is not None and kit.get('labor_timing_source'):
            result[-1].update(_field='',Basis='Calculated from documented attended timing plus setup/review allowances; edit those allowances below')
    result.extend([{'Input':'Kit attended timing','Value':kit.get('attended_minutes_per_plate') or 'Not documented','Units':'minutes/plate','Basis':kit.get('labor_timing_source') or 'Use fallback attended labor estimate','_field':'','_saved':{}},{'Input':'Labor rate','Value':packet.get('case',{}).get('labor_rate',35),'Units':'USD/hour','Basis':'Intake','_field':'','_saved':{}},{'Input':'Labor overhead','Value':15,'Units':'% of labor','Basis':'Automatic calculation','_field':'','_saved':{}}])
    add_calculations(result,packet)
    for row in result:
        row['_basis_detail']=row['Basis']
        if row['_saved']:row['Basis']='Reviewer allowance' if row['_field'] in ('development_hours','setup_minutes_per_plate','review_minutes_per_plate','contingency_rate') else 'Reviewer estimate'
        elif row['_field'] in ('shipping_per_kit','matrix_shipment_usd','setup_minutes_per_plate','review_minutes_per_plate'):row['Basis']='Default allowance'
        elif row['_field']=='consumables_per_plate':row['Basis']='Class-project benchmark'
        elif row['_field']=='labor_hours_per_plate':row['Basis']='Fallback estimate'
        elif row['Input']=='Kit attended timing':row['Basis']='Kit timing source' if kit.get('labor_timing_source') else 'Not documented'
        elif row['Input']=='Fallback attended labor' and not row['_field']:row['Basis']='Calculated from kit timing'
    return result


def add_calculations(result,packet):
    a=packet.get('cost_assumptions',{});v=packet.get('volume',{});cost=packet.get('cost',{})
    plates=len(v.get('plate_allocations',[]));kits=v.get('kits');rate=packet.get('case',{}).get('labor_rate',35)
    money=lambda value:'Not estimated' if value is None else f"{cost.get('currency','USD')} {float(value):,.2f}"
    lines={x['category']:float(x['usd']) for x in cost.get('lines',[])}
    for row in result:
        field=row['_field'];value=row['Value'];row['Calculation']='—';row['Total']='—'
        if field=='kit_price':row.update(Calculation=f'{kits} initial/repeat kits × unit price',Total=money(None if value=='' or kits is None else kits*float(value)))
        elif field=='pooled_material':row.update(Calculation='One total matrix purchase allowance',Total=money(None if value=='' else value))
        elif field=='development_hours':row.update(Calculation=f'{value} h × {money(rate)}/h',Total=money(float(value)*rate))
        elif field=='labor_hours_per_plate' or row['Input']=='Fallback attended labor':row.update(Calculation=f'{plates} plates × {value} h/plate × {money(rate)}/h',Total=money(plates*float(value)*rate))
        elif field in ('setup_minutes_per_plate','review_minutes_per_plate'):row.update(Calculation=f'{plates} plates × {value} min ÷ 60; included only with documented kit timing',Total='Included in attended labor when applicable')
        elif field=='consumables_per_plate':row.update(Calculation=f'{plates} plates × {money(value)}/plate',Total=money(plates*float(value)))
        elif field=='shipping_per_kit':row.update(Calculation=f'{kits} initial/repeat kits × {money(value)}/kit',Total=money(None if kits is None else kits*float(value)))
        elif field=='matrix_shipment_usd':row.update(Calculation='One matrix shipping allowance',Total=money(value))
        elif field=='contingency_rate':row.update(Calculation=f'{value}% × (direct costs + labor overhead)',Total=money(lines.get('Contingency')))
        elif row['Input']=='Labor overhead':row.update(Calculation=f'15% × {money(lines.get("Labor"))}',Total=money(lines.get('Overhead on labor')))
        elif row['Input']=='Kit attended timing':row['Calculation']='Documented hands-on time + setup/review allowances; replaces fallback when available'
        elif row['Input']=='Labor rate':row['Calculation']='Applied to development and attended validation hours'
    instrument=cost.get('instrument_cost_basis',{})
    result.append({'Input':'Instrument use','Value':instrument.get('usd_per_plate') or 'Not estimated','Units':'USD/plate','Basis':'User-provided platform rate','Calculation':f'{plates} plates × instrument rate','Total':money(lines.get('Instrument')),'_field':'','_saved':{}})
    result.append({'Input':'Total project estimate','Value':'','Units':'USD','Basis':'Known subtotal; incomplete' if cost.get('incomplete') else 'Includes overhead and contingency; do not sum timing/reference rows','Calculation':'Kits + matrix + labor + consumables + instrument + shipping + overhead + contingency','Total':money(cost.get('internal_cost')),'_field':'','_saved':{}})

def normalized(field,value):
    if field in TEXT:return str(value or '').strip()
    if value is None or str(value).strip()=='':return None
    number=float(value)
    if not math.isfinite(number) or number<0:raise ValueError('Enter a finite, nonnegative estimate.')
    if field=='kit_price' and number==0:raise ValueError('Kit price must be greater than zero.')
    if field=='contingency_rate' and number>100:raise ValueError('Contingency must be between 0 and 100 percent.')
    return number

def changes(edited,baseline):
    expected={r['Input']:r for r in baseline};seen=set();updates={}
    for row in edited:
        label=row.get('Input')
        if label not in expected or label in seen:raise ValueError('Estimate rows changed; reload the table.')
        seen.add(label);base=expected[label];field=base['_field']
        if not field:continue
        value=normalized(field,row.get('Value'));old=normalized(field,base['Value'])
        if value==old:continue
        if value is None:raise ValueError(label+' cannot be cleared here; enter a reviewed estimate.')
        updates[field]=value/100 if field=='contingency_rate' and value is not None else value
    if seen!=set(expected):raise ValueError('Estimate rows are missing; reload the table.')
    return updates

def render(baseline,key):
    import pandas as pd
    import streamlit as st
    from st_aggrid import AgGrid,JsCode,DataReturnMode
    records={r['Input']:{'value':r['Value'],'field':r['_field'],'saved':r['_saved']} for r in baseline}
    renderer=JsCode(r'''class CostCell {init(p){const el=document.createElement('div');el.style.whiteSpace='pre-wrap';const r=__RECORDS__[p.data.Input];
      const norm=v=>r&&['shipping_basis','shipping_source'].includes(r.field)?String(v??'').trim():(String(v??'').trim()===''?null:Number(v));
      const changed=r&&r.field&&norm(p.value)!==norm(r.value);const saved=r&&r.field&&r.saved&&Object.keys(r.saved).length;
      el.textContent=String(p.valueFormatted??p.value??'');if(changed||saved){el.style.color='__EDIT_COLOR__';el.style.fontWeight='700';const mark=document.createElement('small');mark.style.display='block';mark.textContent=changed?'Unsaved':'Reviewer edited';el.appendChild(mark);}
      if(saved)el.title='Edited by '+r.saved.actor+' at '+r.saved.timestamp;this.eGui=el;}getGui(){return this.eGui;}}'''.replace('__RECORDS__',json.dumps(records,ensure_ascii=True)).replace('__EDIT_COLOR__','#9fc9ff' if st.context.theme.type=='dark' else '#1559a6'))
    options={'columnDefs':[{'field':'Input','pinned':'left','minWidth':210,'flex':1},{'field':'Value','headerName':'Estimate / value','editable':JsCode('function(p){return Boolean(p.data._field);}'),'cellRenderer':renderer,'minWidth':150,'flex':.7},{'field':'Units','minWidth':110,'flex':.6},{'field':'Basis','minWidth':220,'flex':1.2},{'field':'Calculation','minWidth':250,'flex':1.5},{'field':'Total','headerName':'Total / cost contribution','minWidth':200,'flex':1}], 'defaultColDef':{'wrapText':True,'autoHeight':True,'resizable':True,'sortable':False,'wrapHeaderText':True,'autoHeaderHeight':True},'stopEditingWhenCellsLoseFocus':True}
    options['columnDefs'][1].update(pinned='left',cellStyle=JsCode("function(p){return p.data._field?{backgroundColor:'var(--ag-background-color)'}:{backgroundColor:'var(--ag-header-background-color)'};}"),valueFormatter=JsCode("function(p){if(p.value===''||p.value===null||p.value===undefined)return '—';const n=Number(p.value);if(!Number.isFinite(n))return p.value;return String(p.data.Units).startsWith('USD')?'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):n.toLocaleString('en-US',{maximumFractionDigits:2});}"))
    options['columnDefs'][3].update(minWidth=170,tooltipField='_basis_detail')
    options['columnDefs'][-1].update(pinned='right',minWidth=190,cellStyle=JsCode("function(p){return {textAlign:'right',fontWeight:p.data.Input==='Total project estimate'?'700':'400',backgroundColor:'var(--ag-header-background-color)'};}"))
    transport=[{k:str(v) if k=='Value' else v for k,v in row.items() if k!='_saved'} for row in baseline]
    response=AgGrid(pd.DataFrame(transport),gridOptions=options,key=key,height=650,allow_unsafe_jscode=True,enable_enterprise_modules=False,data_return_mode=DataReturnMode.AS_INPUT,update_on=['cellValueChanged'],show_toolbar=False)
    return response.data.to_dict('records')
