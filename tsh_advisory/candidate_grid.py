"""Single comparison grid: editable facts, derived facts read-only, durable provenance."""
import copy
import math
import json
from .comparison import comparison_rows,manual_reference

FIELDS={'Analyte':'analyte','Species':'species','Species strain (kit documentation)':'species_strain','Matrix':'matrix','Kit curve range':'curve_range',
        'Assay input (µL/well)':'well_input_ul','Manual dilution factor':'dilution_factor',
        'Study handling allowance (µL)':'handling_ul','Kit price (USD)':'kit_price',
        'Lead time':'reviewer_lead_time','Assay duration (manual)':'assay_duration',
        'Vendor website':'vendor_url','Kit manual':'manual_url','Manual checked date/time':'manual_checked_at',
        'Instrument (kit manual/vendor)':'vendor_instruments','Required supporting equipment':'required_equipment',
        'Reviewer notes / evidence references':'reviewer_notes'}
NUMERIC={'well_input_ul','dilution_factor','handling_ul','kit_price'}
LISTS={'vendor_instruments','required_equipment'}

def text_value(value):
    if value is None:return ''
    if isinstance(value,list):return '; '.join(value)
    if isinstance(value,(int,float)):return f'{value:g}'
    return str(value)

def normalized_value(field,value):
    text=text_value(value).strip()
    if field in NUMERIC:
        if not text:return None
        try:return float(text)
        except ValueError:return text
    if field in LISTS:return [part.strip() for part in text.split(';') if part.strip()]
    return text

# Keep browser indication consistent with the server-side comparison.
NORMALIZE_JS="""function(field,value){
    const text=Array.isArray(value)?value.join('; '):String(value ?? '').trim();
    if(['well_input_ul','dilution_factor','handling_ul','kit_price'].includes(field)){
        if(!text)return null;
        const number=Number(text);return Number.isFinite(number)?number:text;
    }
    if(['vendor_instruments','required_equipment'].includes(field))return text.split(';').map(x=>x.trim()).filter(Boolean);
    return text.trim();
}"""

def grid_rows(packet,candidates,lead_time):
    comparison=comparison_rows(packet,candidates,lead_time)
    labels=list(dict.fromkeys([label for values in comparison.values() for label in values]+list(FIELDS)))
    if not str(packet.get('case',{}).get('species_strain') or '').strip():
        labels=[label for label in labels if FIELDS.get(label)!='species_strain']
    rows=[]
    for label in labels:
        row={'criterion':label,'_field':FIELDS.get(label,''),'_original':{},'_reviewed':{},'_evidence':{}}
        for kit,values in zip(candidates,comparison.values()):
            cid=kit['id'];field=FIELDS.get(label);value=values.get(label,'')
            if field:
                value=kit.get(field)
                if field=='reviewer_lead_time' and not value:value=lead_time(packet,kit)
                if field=='vendor_instruments' and not value:value=values.get(label,'')
                if field=='manual_url':value=manual_reference(packet,kit)[0]
                if field=='manual_checked_at':value=manual_reference(packet,kit)[1]
            row[cid]=text_value(value)
            row['_original'][cid]=row[cid]
            saved=kit.get('reviewer_edits',{}).get(field,{}) if field else {}
            genuine=saved and normalized_value(field,saved.get('original'))!=normalized_value(field,saved.get('value'))
            row['_reviewed'][cid]=copy.deepcopy(saved) if genuine else {}
            if field:
                from .evidence_details import cell_evidence_detail
                row['_evidence'][cid]=cell_evidence_detail(packet,kit,field)
        rows.append(row)
    return rows

def collect_updates(edited,baseline,candidates):
    """Compare only editable values against server-owned baseline; never trust grid metadata."""
    base={r['criterion']:r for r in baseline};result={}
    seen=set()
    for row in edited:
        label=row.get('criterion')
        if label not in base or label in seen:raise ValueError('Comparison rows changed; reload the table.')
        seen.add(label);field=FIELDS.get(label)
        if not field:continue
        for kit in candidates:
            cid=kit['id'];value=text_value(row.get(cid)).strip()
            if normalized_value(field,value)==normalized_value(field,base[label][cid]):continue
            if field in NUMERIC:
                value=float(value) if value else None
                if value is not None and not math.isfinite(value):raise ValueError(label+' must be a finite number.')
            elif field in LISTS:value=[part.strip() for part in value.split(';') if part.strip()]
            result.setdefault(cid,{})[field]=value
    if seen!=set(base):raise ValueError('Some comparison rows are missing; reload the table.')
    return result

def render_grid(rows,candidates,key):
    import pandas as pd
    import streamlit as st
    from st_aggrid import AgGrid,JsCode,DataReturnMode
    records={row['criterion']:{'field':row['_field'],'original':row['_original'],'reviewed':row['_reviewed'],'evidence':row.get('_evidence',{})} for row in rows}
    renderer=JsCode(r"""class ReviewerCell { init(p){
        const root=document.createElement('div');root.style.whiteSpace='pre-wrap';root.style.lineHeight='1.5';
        const value=String(p.value ?? '');
        const records=__RECORDS__;
        const record=records[p.data.criterion];
        const column=p.colDef.field;
        const normalize=__NORMALIZE__;
        const editable=Boolean(record && record.field && Object.prototype.hasOwnProperty.call(record.original,column));
        const pending=editable && JSON.stringify(normalize(record.field,value))!==JSON.stringify(normalize(record.field,record.original[column]));
        const saved=editable ? record.reviewed[column] : null;
        const marked=editable && (pending || (saved && Object.keys(saved).length>0));
        root.style.color=marked?'__EDIT_COLOR__':'inherit';
        root.style.fontWeight=marked?'700':'400';
        const detail=record && record.evidence ? record.evidence[column] : null;
        if(detail)root.title='Basis: '+detail.basis+'\nLocation: '+detail.locator+'\nPassage: '+detail.quote+'\nReviewer: '+detail.reviewer+'\nReviewed: '+detail.reviewed_at;
        const pattern=/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s]+)/g;
        let match,last=0;
        while((match=pattern.exec(value))!==null){
            root.appendChild(document.createTextNode(value.slice(last,match.index)));
            const link=document.createElement('a');link.textContent=match[1] || match[3];link.href=match[2] || match[3];
            link.target='_blank';link.rel='noopener noreferrer';root.appendChild(link);last=pattern.lastIndex;
        }
        root.appendChild(document.createTextNode(value.slice(last)));
        if(marked){
            const marker=document.createElement('span');marker.textContent=pending?' • Unsaved':' • Reviewer edited';
            marker.style.fontSize='11px';marker.style.display='block';root.appendChild(marker);
            root.title=(pending?'Save changes below.':('Edited by '+saved.actor+' at '+saved.timestamp+'; original: '+JSON.stringify(saved.original)))+'\n'+(root.title || '');
        }this.eGui=root;
    } getGui(){return this.eGui;} }""".replace('__NORMALIZE__',NORMALIZE_JS).replace('__RECORDS__',json.dumps(records,ensure_ascii=True)).replace('__EDIT_COLOR__','#9fc9ff' if st.context.theme.type=='dark' else '#1559a6'))
    columns=[{'field':'criterion','headerName':'Comparison criterion','pinned':'left','width':240,'editable':False,'wrapText':True,'autoHeight':True}]
    for kit in candidates:
        columns.append({'field':kit['id'],'headerName':kit['name']+' · '+kit['catalog'],
                        'flex':1,'minWidth':300,'editable':JsCode('function(p){return Boolean(p.data._field);}'),
                        'cellRenderer':renderer,'cellEditor':'agLargeTextCellEditor','cellEditorPopup':True,
                        'wrapText':True,'autoHeight':True,'wrapHeaderText':True,'autoHeaderHeight':True})
    for column in columns[1:]:column['cellStyle']=JsCode("function(p){return p.data._field?{backgroundColor:'var(--ag-background-color)'}:{backgroundColor:'var(--ag-header-background-color)'};}")
    transport=[{'criterion':row['criterion'],'_field':row['_field'],**{kit['id']:row.get(kit['id'],'') for kit in candidates}} for row in rows]
    response=AgGrid(pd.DataFrame(transport),gridOptions={'columnDefs':columns,'defaultColDef':{'resizable':True,'sortable':False},
                    'stopEditingWhenCellsLoseFocus':True,'singleClickEdit':False,'suppressFieldDotNotation':True},
                    height=720,key=key,allow_unsafe_jscode=True,enable_enterprise_modules=False,
                    data_return_mode=DataReturnMode.AS_INPUT,update_on=['cellValueChanged'],show_toolbar=False)
    return response.data.to_dict('records')
