"""Field-level provenance: passage verification is separate from scientific eligibility."""
from .store import digest
import re

FIELD_GATES={'analyte':'identity','species':'identity','matrix':'matrix','curve_range':'range',
             'well_input_ul':'volume','dilution_factor':'volume'}
ALIASES={'identity':['kit_identity'],'matrix':['sample_matrix'],'range':['curve_range','assay_range'],
         'volume':['sample_input','sample_volume']}

CORE_FACTS=(('analyte','Analyte'),('species','Species'),('matrix','Sample matrix'),('well_input_ul','Sample input per well'),('dilution_factor','Sample dilution'),('curve_range','Kit curve range'))

def core_fact_assessment(packet,kit):
    rows=[]
    for field,label in CORE_FACTS:
        detail=cell_evidence_detail(packet,kit,field)
        missing=detail['value'] is None or detail['value']==''
        counted=bool(not missing and detail['inspectable'] and not detail['needs_recheck'])
        status=('Value not recorded' if missing else 'Needs recheck after value change' if detail['needs_recheck'] else 'Scientist-verified passage' if counted and detail['scientist_verified'] else 'Source passage linked' if counted else 'No current linked source passage')
        from .names import species_parts
        displayed=species_parts(detail['value'])[0] if field=='species' else detail['value']
        rows.append({'Core fact':label,'Current value':displayed,'Evidence status':status,'Included in supported count':counted,'Source ID':detail['source_id'],'Location':detail['locator']})
    return rows

def core_fact_summary(packet,kit,brief=False):
    rows=core_fact_assessment(packet,kit);count=sum(r['Included in supported count'] for r in rows)
    if brief:
        short={'Analyte':'analyte','Species':'species','Sample matrix':'matrix','Sample input per well':'input/well','Sample dilution':'dilution','Kit curve range':'curve range'}
        linked=', '.join(short[r['Core fact']] for r in rows if r['Included in supported count']) or 'none'
        other=', '.join(short[r['Core fact']] for r in rows if not r['Included in supported count']) or 'none'
        return f'{count}/6 linked: {linked}.'+(f' Not current/linked: {other}.' if count<6 else '')
    return f'{count} of 6 core facts have current linked source passages. Each fact is assessed separately:\n'+'\n'.join(r['Core fact']+': '+r['Evidence status']+(' (counted)' if r['Included in supported count'] else ' (not counted)') for r in rows)


def cell_evidence_detail(packet,kit,field):
    current=kit.get(field);record=kit.get('cell_evidence',{}).get(field,{})
    automatic=kit.get('auto_evidence',{}).get(field,{})
    record_source=bool(record.get('source_id'))
    gate=FIELD_GATES.get(field);evidence=(record if record_source else automatic) or record or kit.get('evidence',{}).get(gate,{})
    if not evidence and gate:
        evidence=next((kit.get('evidence',{}).get(key) for key in ALIASES[gate] if kit.get('evidence',{}).get(key)),{})
    source=packet.get('sources',{}).get(evidence.get('source_id'),{}) if evidence else {}
    changed=bool(record_source and record.get('value_at_review')!=current) or bool(not record_source and automatic and automatic.get('value_at_review')!=current) or bool(not automatic and not record_source and record and record.get('value_at_review')!=current) or bool(not record and not automatic and kit.get('reviewer_edits',{}).get(field))
    inspectable=bool(source and evidence.get('quote') and evidence['quote'] in source.get('text','') and source.get('content_hash')==digest(source.get('text','')) and evidence.get('locator'))
    basis='Reviewer assertion / estimate'
    if inspectable:basis='Source passage linked; scientist interpretation required'
    scientist_verified=bool(record_source and record.get('verified_by') and inspectable and not changed)
    if scientist_verified:basis='Scientist-verified supporting passage'
    if changed:basis='Value changed since evidence review; source interpretation needs recheck'
    return {'field':field,'value':current,'basis':basis,'source_id':evidence.get('source_id','') if evidence else '',
        'url':source.get('url') or record.get('reference_url') or kit.get('manual_url') or kit.get('vendor_url',''),'locator':evidence.get('locator','') if evidence else '',
        'quote':evidence.get('quote','') if evidence else '', 'reviewer':record.get('verified_by') or kit.get('reviewer_edits',{}).get(field,{}).get('actor',''),
        'reviewed_at':record.get('reviewed_at') or kit.get('reviewer_edits',{}).get(field,{}).get('timestamp',''),
        'notes':record.get('notes',''),'needs_recheck':changed,'inspectable':inspectable,'scientist_verified':scientist_verified}


def verified_cell_record(packet,kit,field,entry,actor,timestamp):
    if not field or field not in kit:raise ValueError('Select a valid kit field.')
    result={'value_at_review':kit.get(field),'verified_by':actor,'reviewed_at':timestamp,'notes':entry.get('notes','').strip(),
            'reference_url':entry.get('reference_url','').strip()}
    if entry.get('supporting_document_id'):result['supporting_document_id']=entry['supporting_document_id']
    sid=entry.get('source_id')
    if sid:
        source=packet.get('sources',{}).get(sid)
        quote=entry.get('quote','').strip();locator=entry.get('locator','').strip()
        if source and quote and quote not in source.get('text',''):
            match=re.search(r'\s+'.join(re.escape(word) for word in quote.split()),source.get('text',''))
            if match:quote=match.group(0)
        if not source or not quote or quote not in source.get('text','') or not locator:raise ValueError('Select a retained source, a location and an exact passage contained in that source.')
        if not source.get('owner','').strip():raise ValueError('Retained source must have an accountable owner.')
        if source.get('content_hash')!=digest(source.get('text','')):raise ValueError('Source hash mismatch.')
        if source.get('synthetic') and packet.get('mode')!='fixture':raise ValueError('Synthetic evidence cannot support a live record.')
        if len(quote)>400:raise ValueError('Use a supporting passage of at most 400 characters.')
        result.update(source_id=sid,quote=quote,locator=locator,claim=field+': '+str(kit.get(field)))
    elif not result['notes']:raise ValueError('Document the reviewer assertion or estimate basis.')
    return result
