import csv,io,json,zipfile,html,hashlib,re
from pathlib import Path
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,KeepTogether
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.graphics.shapes import Drawing,Rect,String
from .policy import released,packet_hash,current_decisions,SECTIONS
from .store import canonical,digest,now
from .design import pending_work
from .comparison import recommendation_reasons,comparison_rows
from .comparison import manual_reference
from .kit_library import display_kit
from .agents import public_get
from .planning import plate_rows
from .candidate_grid import grid_rows
from .review_views import protocol_rows
from .client_package import client_summary_blocks,currency
from .findings import blocking_findings,scoped_findings,SCOPE_POLICY
from pypdf import PdfReader,PdfWriter

def selected_manual_attachment(store,rid):
    packet=store.run(rid)['data'].get('packet',{})
    kit=next((display_kit(k) for k in packet.get('candidates',[]) if k['id']==packet.get('selected_kit')),None)
    if not kit:raise ValueError('Select a kit before attaching its manual.')
    if kit.get('retained_manual'):
        from .manuals import attachment
        return attachment(store,kit,kit['retained_manual'])
    url,_=manual_reference(packet,kit)
    if not url:raise ValueError('No manual URL is recorded for the selected kit. Enter it in Candidate comparison or export without the attachment.')
    folder=store.root/'manual-attachments';folder.mkdir(exist_ok=True)
    key=digest([kit['id'],kit['catalog'],url]);path=folder/(key+'.pdf');record=folder/(key+'.json')
    if path.exists() and record.exists():
        raw=path.read_bytes();metadata=json.loads(record.read_text(encoding='utf-8'))
        if hashlib.sha256(raw).hexdigest()!=metadata['sha256']:raise ValueError('Saved manual hash does not match its source record. Attachment stopped.')
    else:
        final,content_type,raw=public_get(url)
        if not raw.lstrip().startswith(b'%PDF-'):raise ValueError('The selected manual URL did not return a PDF. Update the direct manual link or export without the attachment.')
        reader=PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or not reader.pages:raise ValueError('Manual PDF is encrypted or empty; use an accessible manual.')
        identity=''.join((reader.pages[i].extract_text() or '') for i in range(min(2,len(reader.pages))))
        if re.sub(r'[^A-Z0-9]','',kit['catalog'].upper()) not in re.sub(r'[^A-Z0-9]','',identity.upper()):
            raise ValueError('The manual’s opening pages do not identify the selected kit catalog. Check the manual URL before attaching it.')
        filename=re.sub(r'[^A-Za-z0-9._-]','_',kit['catalog'])+'-manual.pdf'
        metadata=dict(kit_id=kit['id'],catalog=kit['catalog'],filename=filename,requested_url=url,source_url=final,retrieved_at=now(),sha256=hashlib.sha256(raw).hexdigest(),pages=len(reader.pages))
        path.write_bytes(raw);record.write_text(canonical(metadata),encoding='utf-8')
    store.event(rid,'manual_attachment_prepared','requester',metadata)
    return {'bytes':raw,'metadata':metadata}

def append_manual_pdf(report,attachment):
    meta=attachment['metadata'];cover=io.BytesIO();styles=getSampleStyleSheet()
    text=[('Heading1','Attachment: selected kit manual'),('BodyText','Kit catalog: '+meta['catalog']),
          ('BodyText','Original manual: '+meta['filename']),('BodyText','Source: '+meta['source_url']),
          ('BodyText','Retrieved: '+meta['retrieved_at']),('BodyText','SHA-256: '+meta['sha256']),
          ('BodyText','The following pages reproduce the vendor manual. The original PDF is also embedded as a file attachment. Inclusion does not establish assay validation or project authorization.')]
    SimpleDocTemplate(cover,pagesize=(612,792),leftMargin=48,rightMargin=48,topMargin=48,bottomMargin=48).build([Paragraph(html.escape(value),styles[kind]) for kind,value in text])
    writer=PdfWriter();writer.append(PdfReader(io.BytesIO(report)))
    writer.add_outline_item('Selected kit manual - '+meta['catalog'],len(writer.pages))
    writer.append(PdfReader(io.BytesIO(cover.getvalue())))
    writer.append(PdfReader(io.BytesIO(attachment['bytes'])),import_outline=False)
    writer.add_attachment(meta['filename'],attachment['bytes'])
    output=io.BytesIO();writer.write(output);return output.getvalue()

def report_sections(store,rid):
    run=store.run(rid); s=run['data']; p=s.get('packet',{})
    status='AUTHORIZED PLANNING PACKAGE' if released(store,rid) else 'DRAFT - NOT AUTHORIZED'
    if run['mode']=='fixture': status='SYNTHETIC SOFTWARE TEST - NOT A SCIENTIFIC RECOMMENDATION'
    selected=next((k for k in p.get('candidates',[]) if k['id']==p.get('selected_kit')),None)
    return [('Status',status),('Project',s['case']['title']),('Intended use',s['case']['intended_use']),
        ('Selected kit',selected or 'No kit selected'),('Agent summary',p.get('summary',{})),
        ('All candidates',p.get('candidates',[])),('Study sample feasibility',p.get('study',{})),
        ('Calculated validation material requirements',p.get('volume',{})),('Proposed validation plan',p.get('plan',{})),
        ('Cost estimate and proposed price',p.get('cost',{})),('Scientific findings',p.get('findings',[])),
        ('Named decisions and approved kit record',store.decisions(rid)),
        ('Evidence register',list(p.get('sources',{}).values())),
        ('Limitations','Planning output only; no assay validation results. Identity is self-attested. Public prices are estimates. Proposed preparation and controls need scientific approval.'),
        ('Packet hash',packet_hash(p))]

def display(value):
    if value is None:return 'Unresolved'
    if isinstance(value,float):return f'{value:,.3f}'.rstrip('0').rstrip('.')
    return str(value).replace('Precision and accuracy / calibration and QC','Precision and Accuracy')

def public_lead_time(packet,kit):
    if kit and kit.get('reviewer_lead_time'):
        from .evidence_details import cell_evidence_detail
        detail=cell_evidence_detail(packet,kit,'reviewer_lead_time')
        if detail['inspectable'] and not detail['needs_recheck']:
            return kit['reviewer_lead_time']+' · scientist-reviewed source passage; '+detail['locator']+'; source '+detail['source_id']
        return kit['reviewer_lead_time']+' · reviewer estimate (not public vendor confirmation)'
    if not kit or not kit.get('lead_time'):return 'Public lead time not available'
    source=packet.get('sources',{}).get(kit.get('lead_time_source_id'))
    if not source or kit['lead_time'] not in source.get('text','') or source.get('synthetic'):
        if kit.get('reviewer_lead_time'):return kit['reviewer_lead_time']+' · reviewer estimate (not public vendor confirmation)'
        return 'Lead time unverified; public source required'
    return kit['lead_time']+' · source '+source['id']+' · checked '+(kit.get('lead_time_checked_at') or source['retrieved_at'])

def summary_blocks(store,rid):
    return client_summary_blocks(store,rid,public_lead_time)


def readable_blocks(store,rid):
    run=store.run(rid);state=run['data'];p=state.get('packet',{});case=state['case']
    blocks=summary_blocks(store,rid)
    summary_length=len(blocks)
    def heading(t):blocks.append(('heading',t))
    def paragraph(t):blocks.append(('paragraph',str(t)))
    def table(headers,rows):blocks.append(('table',[headers]+[[display(v) for v in row] for row in rows]))
    heading('Project and review status')
    paragraph(report_sections(store,rid)[0][1])
    paragraph(case['title']);paragraph('Intended use: '+case['intended_use'])
    paragraph('This report proposes assay selection and validation work. It does not report completed laboratory validation.')
    paragraph('Planning assumptions: kit manual/vendor instrument requirements and intake-listed available instruments are reported separately. Instrument/model/platform matching is not an automated approval requirement. The scientist confirms the instrument/equipment arrangement when approving the selected kit; instrument and configuration concerns remain advisory. Expected study concentrations need not be known for planning approval. Manufacturer curve ranges remain reported; other scientific evidence and known range problems still require review.')
    selected=next((k for k in p.get('candidates',[]) if k['id']==p.get('selected_kit')),None)
    heading('Recommendation and kit selection')
    if selected:
        paragraph(f"Selected for review: {selected['manufacturer']} — {selected['name']} — catalog {selected['catalog']}, platform {selected['platform']}.")
        paragraph('Lead time: '+public_lead_time(p,selected))
        paragraph('Six selection factors and trade-offs for the scientist-selected kit:')
        from .selection import selection_factors
        from .evidence_details import core_fact_assessment,cell_evidence_detail,CORE_FACTS
        core=core_fact_assessment(p,selected)
        factors=selection_factors(p,selected)
        for row in factors:
            if row['Selection factor']=='Evidence support':row['Current assessment']=str(sum(f['Included in supported count'] for f in core))+'/6 core facts have current linked source passages; see the checklist below.'
        table(['Selection factor','Current assessment'],[[row['Selection factor'],row['Current assessment']] for row in factors])
        recommendation=next((k for k in p.get('candidates',[]) if k['id']==p.get('recommended_kit')),None)
        status='provisional; comparison has ties or missing information' if p.get('recommendation_refresh',{}).get('status')!='clear_rule_based_choice' else 'supported by the recorded comparison; scientist confirmation required'
        paragraph('Current planning recommendation: '+(recommendation['name']+' / '+recommendation['catalog']+' ('+status+')' if recommendation else 'Pending; no clear supported choice')+'. Scientist selection and approval remain separate.')
        heading('Core kit facts and evidence coverage')
        core_rows=[]
        for fact,(field,label) in zip(core,CORE_FACTS):
            detail=cell_evidence_detail(p,selected,field);value=fact['Current value']
            if field=='dilution_factor' and value is not None:value=f'1:{value:g}'
            if field=='well_input_ul' and value is not None:value=f'{value:g} µL'
            source='[Source]('+detail['url']+') · '+detail['locator'] if detail['source_id'] and detail['url'].startswith(('https://','http://')) else detail['locator'] or 'Not linked'
            core_rows.append([label,value if value is not None and value!='' else 'Not recorded',fact['Evidence status'],source])
        table(['Core fact','Saved value','Evidence status','Source / location'],core_rows)
    else:paragraph('No kit has been selected.')
    paragraph('Selection and calculation assumptions are recorded in the audit trail.')
    heading('Kit comparison')
    from .selection import selection_analysis
    if selected:
        analysis=selection_analysis(p,selected)
        paragraph(analysis['basis'])
        paragraph(analysis['conclusion'])
        for tradeoff in analysis['tradeoffs']:paragraph('Selection trade-off: '+tradeoff)
    paragraph('Expected study concentrations need not be known for planning. Manufacturer ranges are listed below. Kit instrument requirements and available intake instruments are listed separately for scientist confirmation.')
    finalists=p.get('finalist_ids',[])
    candidates=[display_kit(k) for k in p.get('candidates',[]) if not finalists or k['id'] in finalists]
    comparison=grid_rows(p,candidates,public_lead_time) if candidates else []
    if comparison:
        def comparison_cell(row,kit):
            value=row[kit['id']]
            if row['_field'] in ('vendor_url','manual_url') and value.startswith(('https://','http://')):
                value='['+row['criterion']+']('+value+')'
            return value+(' [Reviewer edited]' if row['_reviewed'][kit['id']] else '')
        table(['Comparison criterion']+[k['name']+' · '+k['catalog'] for k in candidates],
              [[row['criterion']]+[comparison_cell(row,k) for k in candidates] for row in comparison])
    if finalists:
        heading('Alternative kits reviewed')
        table(['Kit / catalog','Platform','Primary reason','Kit manual'],[[k['name']+' / '+k['catalog'],k['platform'],k.get('rejection_reason') or 'Screened; not fully assessed. Exclusion reason requires documentation.',
              '[Kit manual]('+manual_reference(p,k)[0]+')' if manual_reference(p,k)[0] else 'Not provided'] for k in p.get('candidates',[]) if k['id'] not in finalists])
    if p.get('screened_candidates'):
        heading('Additional candidates screened only')
        table(['Kit','Platform','Screening note'],[[k.get('name',''),k.get('platform',''),k.get('reason') or 'Not deeply assessed within the four-kit limit'] for k in p['screened_candidates']])
    heading('Study sample feasibility')
    s=p.get('study',{})
    table(['Available matrix µL','Initial matrix µL','Repeat matrix µL','Handling matrix µL','Remaining balance µL'],[[s.get(k) for k in ['available_ul','initial_ul','repeat_ul','handling_ul','remaining_ul']]])
    paragraph('Volume assessment: '+s.get('status','unresolved')+'. The study allocation is separate from validation material requirements.')
    if s.get('preparation'):
        paragraph('Practical preparation per sample per initial set; the same matrix requirement is reserved for each independently prepared complete repeat. Nonzero transfers are at least 10 µL. Dilution suitability requires scientist review.')
        table(['Dilution','Pull from','Source µL','Diluent µL','Prepare µL','Next transfer µL'],[[step['dilution'],step['source'],step['source_ul'],step['diluent_ul'],step['prepared_ul'],step['transfer_next_ul']] for step in s['preparation']])
        final=s['preparation'][-1]
        paragraph(f"Final dilution retained: {final['retained_ul']:g} µL; covers {final['plate_ul']:g} µL for {case.get('initial_wells',2)} wells plus {final['reserve_ul']:g} µL pipetting-loss reserve. Handling and independently prepared repeat material are budgeted separately.")

    paragraph('Study analysis dilution: 1:'+str(s.get('dilution_factor','not resolved'))+' ('+s.get('dilution_basis','historical kit record')+'). Validation starting dilution: 1:'+str(case.get('parallel_start_dilution',1))+'.')
    plan=p.get('plan') or {};v=p.get('volume',{})
    heading('Proposed validation protocol')
    overview=protocol_rows(plan,case,v)
    if overview:
        headers=list(overview[0]);table(headers,[[row[h] for h in headers] for row in overview])
    heading('Calculated validation material')
    paragraph('P/A kit stock is included in the kits and has no separate material requirement or cost. Other parameters show matrix volume per lot. Preparation reserves and handling losses are included in parameter volumes; the final lot totals add 200 µL per lot for aliquoting.')
    table(['Parameter and material','Initial µL','Repeat µL','Handling µL','Total µL per material unit'],[
        [r['parameter']+' / '+r['material_type']]+(['—']*4 if r['material_type']=='Kit stock' else [r['initial_ul_per_lot'],r['repeat_ul_per_lot'],r['losses_ul_per_lot'],r['total_ul_per_lot']]) for r in v.get('rows',[])])
    paragraph('Total validation material: '+display(v.get('total_ul_all_lots'))+' µL. Amounts are calculated requirements, not intake volume limits.')
    if v.get('lot_requirements'):
        table(['Lot','Parameter requirement µL','Aliquoting allowance µL','Final requirement µL'],[[r['lot'],r['parameter_requirement_ul'],r['aliquotting_loss_ul'],r['total_required_ul']] for r in v['lot_requirements']])
    heading('Estimate assumptions and quantities')
    instrument=p.get('cost',{}).get('instrument_cost_basis',{})
    paragraph('Instrument use: '+str(instrument.get('plates','Not calculated'))+' plates × '+currency(instrument.get('usd_per_plate'))+'/plate. Overhead is 15% of estimated labor cost. Instrument rates are user-provided planning assumptions.')
    from .estimate_basis import estimate_rows
    basis_rows=estimate_rows(p)
    table(['Input','Quantity / rate equation','Information basis'],[[row['Input'],row['Calculation'],row['Basis']] for row in basis_rows])
    heading('Initial and repeat kit requirements')
    table(['Parameter','Initial kits','Repeat kits','Total additional kits'],[[r['parameter'],('Combined: '+', '.join(p for p in r.get('plate_ids',[]) if p.startswith('PA-'))) if r.get('initial_kits')==0 and any(p.startswith('PA-') for p in r.get('plate_ids',[])) else r.get('initial_kits'),r.get('repeat_kits'),r.get('kits')] for r in v.get('rows',[])])
    paragraph(f"Overall: {display(v.get('initial_kits'))} initial kits + {display(v.get('repeat_kits'))} repeat kits = {display(v.get('kits'))} kits.")
    paragraph(f"Each initial P/A plate hosts at most one additional parameter. Each parameter has dedicated repeat plates. The {case.get('precision_accuracy_plates',6)} P/A plates are not automatically repeated. Each long-term assessment and independent run has a separate allocation. Shared row counts represent additional kits, not exclusive use.")
    if v.get('plate_allocations'):
        heading('Shared plate allocation')
        ledger=plate_rows(v);headers=list(ledger[0]);table(headers,[[row[h] for h in headers] for row in ledger])
    for r in v.get('rows',[]):
        if not r.get('parallelism_calculation'):continue
        heading('Parallelism serial preparation')
        paragraph(f"Preparation table is per lot per independent run; {r.get('independent_runs',1)} independent run(s) and {case.get('complete_repeats',1)} complete repeat set(s) are included in parameter totals.")
        paragraph('Prepare the series backward to reserve enough for plating and the next transfer. Only the first step uses neat serum. Later steps pull from the previous dilution. Transfers round upward to whole microlitres; dilution ratios are preserved by the diluent volume.')
        table(['Dilution','Pull from','Withdraw µL','Diluent µL','Prepare µL','Next transfer µL','Retain µL','Plate µL (wells)'],[
            [step['dilution'],step.get('source','Previous dilution'),step['source_or_previous_dilution_ul'],
             step['diluent_ul'],step['total_to_prepare_ul'],step['transfer_to_next_ul'],
             step.get('retained_after_transfer_ul',step['prepared_for_wells_ul']),
             display(step['prepared_for_wells_ul'])+' ('+str(step['wells_per_lot'])+' wells)']
            for step in r['parallelism_calculation']])
        table(['Initial neat matrix µL','Repeat reserve µL','Handling µL','Total matrix per lot µL'],[
            [r['initial_ul_per_lot'],r['repeat_ul_per_lot'],r['losses_ul_per_lot'],r['total_ul_per_lot']]])
    heading('Cost estimate and proposed price')
    cost=p.get('cost',{})
    if cost.get('incomplete'):paragraph('INCOMPLETE ESTIMATE — totals below cover known inputs only; not a complete project quote. Missing: '+'; '.join(cost.get('unresolved',[])))
    paragraph('Currency: '+cost.get('currency','USD')+'. Public prices and planning assumptions require approval.')
    assumptions=p.get('cost_assumptions') or {}
    paragraph('Cost basis: '+assumptions.get('costing_basis','Historical fixed totals'))
    basis=cost.get('instrument_cost_basis',{})
    if basis:
        paragraph('Instrument charge: '+display(basis.get('plates'))+' initial/repeat plates × '+display(basis.get('usd_per_plate'))+' USD per plate for '+basis.get('platform','selected platform')+'. Internal rates: SpectraMax 10 USD/plate; Bio-Plex 35 USD/plate; MSD 35 USD/plate. These are user-provided internal rates, not vendor prices.')
    paragraph('Overhead is calculated automatically as 15% of estimated labor cost. Profit uplift is excluded; proposed price equals internal cost including contingency.')
    table(['Cost component','Amount'],[[line['category'],line['usd']] for line in cost.get('lines',[])])
    paragraph('Internal cost: '+display(cost.get('internal_cost'))+'; proposed client price: '+display(cost.get('client_price'))+'.')
    for issue in cost.get('unresolved',[]):paragraph('Unresolved cost input: '+issue)
    paragraph('Detailed findings and agent rationale are retained in the audit log and evidence bundle.')
    paragraph('Approval scope: selected-kit and project-wide findings are assessed for this plan. All findings are advisory and do not block scientific or director approval; named reviewers retain responsibility.')
    heading('Current advisory flags')
    paragraph('All findings are advisory. Named scientific and director reviews remain accountable decisions for this report version.')
    flags=scoped_findings(p)
    if flags:
        table(['Section / priority','Finding','Status'],[[f['section'].title()+' / '+f['severity'].title(),f['message'],f.get('status','open').replace('_',' ')] for f in flags])
    else:paragraph('No current review flags. Technical source-mapping diagnostics remain in the evidence bundle.')
    heading('Accepted planning and evidence assumptions')
    latest={f.get('id',digest(f)):f for f in p.get('finding_history',[])}
    history=[f for f in latest.values() if f.get('status')=='accepted' and f.get('disposition',{}).get('action')=='accepted']
    if history:
        compact=lambda value,limit: str(value) if len(str(value))<=limit else str(value)[:limit-3]+'...'
        table(['Outcome / section','Finding summary','Reviewer / reason'],[
            ['Accepted for planning / '+f.get('section',''),
             compact(re.sub(r'^(?:FAIL|HOLD|PARTIAL REPAIR)[—–: -]*','',f.get('message','')),220) if 'washer-dependent residual volume' not in f.get('message','') else 'Final readout-buffer volume',
             f.get('disposition',{}).get('actor','System rules')+'; '+compact(f.get('disposition',{}).get('reason') or f.get('resolution',''),300)] for f in history])
        paragraph('These items were explicitly accepted by the scientist for planning/evidence. Acceptance does not establish a passed check or verified evidence. Complete review records are retained in the evidence bundle.')
    else:paragraph('No accepted planning/evidence assumptions recorded.')
    heading('Named review decisions')
    if p.get('intake_application'):
        application=p['intake_application']
        paragraph('Calculations use saved intake version '+str(application['current_version'])+', applied by '+application['actor']+' on '+application['applied_at'][:10]+'. Retained kit research was reused; no additional research was performed. Updated inputs: '+', '.join(field.replace('_',' ') for field in application['changed_fields'])+'.')
        if application.get('review_fields'):paragraph('Retained-evidence applicability reviewed for '+', '.join(application['review_fields'])+': '+application['scope_reason'])
    decisions=list(current_decisions(store,rid,packet_hash(p)).values())
    for d in decisions:
        current='Current packet' if d['packet_hash']==packet_hash(p) else 'Superseded packet'
        paragraph(f"{d['actor']} ({d['role']}) — {d['section']}: {d['action']}. {d['reason']}. {current}. {d['timestamp']}")
        if d.get('simulation'):paragraph('SIMULATED DECISION — test workflow only; no scientific clearance or laboratory authorization.')
        if d.get('instrument_confirmation'):
            confirmation=d['instrument_confirmation']
            paragraph('Scientist instrument/equipment confirmation: '+('Confirmed' if confirmation.get('confirmed') else 'Not confirmed / simulation')+' by '+confirmation.get('responsible_scientist','')+'. Available intake instruments: '+'; '.join(str(k)+': '+str(v) for k,v in confirmation.get('available_instruments_from_intake',{}).items())+'. No automated model-name match was required.')
        if d.get('comments'):paragraph('Comments: '+d['comments'])
        if d.get('kit_record'):paragraph('Kit documented in this decision: '+d['kit_record']['name']+' / '+d['kit_record']['catalog'])
    if not decisions:paragraph('No scientific or director decisions recorded.')
    if p.get('supporting_documents'):
        from .supporting_documents import expiry_status
        heading('Supporting documents')
        kit_labels={k['id']:k['catalog'] for k in p.get('candidates',[])}
        table(['Document / source','Kit','Document date / validity','Reviewed use'],[[r['filename']+' / '+r['source_name'],kit_labels.get(r['candidate_id'],'Project-wide'),(r['document_date'] or 'Date not recorded')+' / '+expiry_status(r),'; '.join(use['field']+': '+str(use['value']) for use in r.get('uses',[])) or 'Retained reference; no value adopted'] for r in p['supporting_documents']])
        paragraph('Uploaded correspondence and quotes are reviewer-provided sources, not public vendor prices. Original files selected for inclusion are retained in the evidence bundle with file hashes and source records.')
    heading('Evidence and limitations')
    from urllib.parse import urlparse,unquote
    references=[]
    for i,source in enumerate(p.get('sources',{}).values(),1):
        url=source['url'];title=source.get('title','')
        if not title or title.startswith(('http://','https://')):
            parsed=urlparse(url);name=unquote(parsed.path.rsplit('/',1)[-1]).replace('_',' ').replace('-',' ')
            title=parsed.netloc+(' / '+name if name else ' / source document')
        title=title.replace('[','(').replace(']',')')
        references.append([str(i),'['+title+']('+url+')' if url.startswith(('https://','http://')) else title+' (uploaded source retained with run)',source.get('retrieved_at','')[:10]])
    if references:table(['Reference','Document / source link','Accessed (UTC)'],references)
    else:paragraph('Source links are listed in the kit comparison. Additional retained source records are not available.')
    paragraph('Manufacturer curve ranges are reported for planning. Local assay performance has not been established by this report. Full source extracts, original agent records and revision history are included in the evidence bundle.')
    paragraph('Document approvals use self-attested named roles in this classroom application.')
    # Keep client decision pages separate from the detailed supporting record.
    detail=blocks[summary_length:]
    def section(start,end=None):
        first=next((i for i,x in enumerate(detail) if x==('heading',start)),None)
        if first is None:return []
        ends=end if isinstance(end,tuple) else (end,)
        last=next((i for i in range(first+1,len(detail)) if detail[i][0]=='heading' and detail[i][1] in ends),len(detail))
        return detail[first:last]
    appendices=[('A','Kit comparison',section('Recommendation and kit selection','Kit comparison')+section('Kit comparison','Study sample feasibility')),
                ('B','Proposed validation protocol',section('Proposed validation protocol','Calculated validation material')+section('Study sample feasibility','Proposed validation protocol')),
                ('C','Calculated validation material',section('Calculated validation material',('Shared plate allocation','Parallelism serial preparation','Cost estimate and proposed price'))),
                ('D','Shared plate allocation',section('Shared plate allocation',('Parallelism serial preparation','Cost estimate and proposed price'))),
                ('E','Parallelism serial preparation',section('Parallelism serial preparation','Cost estimate and proposed price')),
                ('F','Current advisory flags',section('Current advisory flags','Evidence and limitations')),
                ('G','Evidence and limitations',section('Evidence and limitations'))]
    result=blocks[:summary_length]
    for letter,title,content in appendices:
        if not content:continue
        if result and result[-1][0]!='pagebreak':result.append(('pagebreak',''))
        result.append(('eyebrow','TECHNICAL APPENDIX '+letter))
        result.extend(content)
    return result

def chart_values(lines):
    from decimal import Decimal
    return sorted([(line['category'],float(Decimal(str(line['usd'])))) for line in lines if float(Decimal(str(line['usd'])))>0],key=lambda row:-row[1])


def cost_chart(lines,pdf=False):
    values=chart_values(lines);height=max(60,len(values)*17+10);maximum=max([v for _,v in values] or [1])
    if pdf:
        drawing=Drawing(516,height)
        for i,(label,amount) in enumerate(values):
            y=height-17*(i+1)
            drawing.add(String(0,y+2,label,fontName='Helvetica',fontSize=8.5,fillColor=colors.HexColor('#33465a')))
            drawing.add(Rect(130,y,280*amount/maximum,10,fillColor=colors.HexColor('#168a9b'),strokeColor=None))
            drawing.add(String(510,y+2,currency(amount),textAnchor='end',fontName='Helvetica',fontSize=8.5,fillColor=colors.HexColor('#183248')))
        return drawing
    rows=[]
    for i,(label,amount) in enumerate(values):
        y=17*(i+1)
        rows.append('<text x="0" y="'+str(y)+'" font-size="9">'+html.escape(label)+'</text><rect x="130" y="'+str(y-9)+'" width="'+str(280*amount/maximum)+'" height="10" fill="#168a9b"/><text x="510" y="'+str(y)+'" text-anchor="end" font-size="9">'+html.escape(currency(amount))+'</text>')
    return '<svg role="img" aria-label="Estimated cost by component in USD" viewBox="0 0 516 '+str(height)+'" style="width:100%;max-height:190px">'+''.join(rows)+'</svg>'


def html_report(store,rid):
    content=[];blocks=readable_blocks(store,rid)
    links=[(i,value) for i,(kind,value) in enumerate(blocks) if kind=='hero' or kind=='eyebrow' and str(value).startswith('TECHNICAL APPENDIX')]
    content.append('<nav aria-label="Report contents">'+''.join('<a href="#section-'+str(i)+'">'+html.escape(title)+'</a>' for i,title in links)+'</nav>')
    for i,(kind,value) in enumerate(blocks):
        if kind=='pagebreak':content.append('<div class="pagebreak"></div>');continue
        if kind=='costchart':content.append(cost_chart(value));continue
        if kind in ('table','summarytable','clienttable'):
            head='<thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in value[0])+'</tr></thead>'
            body='<tbody>'+''.join('<tr>'+''.join('<td>'+linked_text(x)+'</td>' for x in row)+'</tr>' for row in value[1:])+'</tbody>'
            content.append('<div class="table-scroll"><table'+(' class="cost-table"' if value[0][0]=='Cost component' else '')+'>'+head+body+'</table></div>')
        else:
            tag='h1' if kind=='hero' else 'h2' if kind in ('heading','summaryheading') else 'p'
            content.append('<'+tag+' id="section-'+str(i)+'" class="'+kind+'">'+html.escape(value)+'</'+tag+'>')
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Bioanalytical client planning package</title><style>body{font:15px/1.5 system-ui;max-width:1050px;margin:40px auto;padding:24px;color:#23364a}nav{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;padding:12px;background:#f4f7fa}h1,h2{color:#12334c}h1{font-size:30px;margin:10px 0}h2{font-size:19px;margin:20px 0 8px}.eyebrow{font-size:12px;letter-spacing:1.4px;color:#168a9b;font-weight:700}.status{padding:10px;background:#eaf3f6;color:#12334c;font-weight:700}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{border:1px solid #dfe7ee;padding:9px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#12334c;color:white}tbody tr:nth-child(even){background:#f4f7fa}table.cost-table tbody tr:last-child{font-weight:700;background:#e4f1f4}.table-scroll{overflow-x:auto}p{overflow-wrap:anywhere}.pagebreak{margin:28px 0;border-bottom:1px solid #dfe7ee}@page{size:letter;margin:0.67in}@media print{nav{display:none}body{font-size:10pt;line-height:1.35;margin:0;padding:0;max-width:none}h1{font-size:24pt}h2{font-size:12pt}th,td{font-size:9pt;padding:5pt}svg{max-height:160pt}.pagebreak{break-after:page;border:0;margin:0}thead{display:table-header-group}h1,h2{break-after:avoid}tr{break-inside:avoid}}</style>'+''.join(content)+'</html>'


def linked_text(value,pdf=False):
    escaped=html.escape(str(value)).replace('\n','<br/>')
    if pdf:escaped=escaped.replace('–','-').replace('—','-').replace('×','x')
    pattern=r'\[([^\]]+)\]\((https?://[^\s<>]+)\)'
    result=re.sub(pattern,r'<link href="\2" color="blue">\1</link>' if pdf else r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',escaped)
    if str(value).endswith(' [Reviewer edited]'):
        return '<font color="#1559a6"><b>'+result+'</b></font>' if pdf else '<strong style="color:#1559a6">'+result+'</strong>'
    return result

APPENDIX_TITLES={'A':'Kit comparison','B':'Validation protocol and study preparation','C':'Material, kit and estimate assumptions','D':'Plate allocation','E':'Parallelism preparation','F':'Reviews and accepted assumptions','G':'Evidence register'}


class ClientDocument(SimpleDocTemplate):
    def afterFlowable(self,flowable):
        if not isinstance(flowable,Paragraph):return
        text=flowable.getPlainText();style=flowable.style.name
        if style=='ClientHero' or (style=='ClientEyebrow' and text.startswith('TECHNICAL APPENDIX')):
            self._outline_count=getattr(self,'_outline_count',0)+1;key='section-'+str(self._outline_count)
            label=('Appendix '+text[-1]+' - '+APPENDIX_TITLES.get(text[-1],text)) if text.startswith('TECHNICAL APPENDIX') else text
            self.canv.bookmarkPage(key);self.canv.addOutlineEntry(label,key,level=0,closed=False)


def pdf_report(store,rid,include_manual=False,manual_attachment=None):
    out=io.BytesIO();styles=getSampleStyleSheet();story=[]
    navy=colors.HexColor('#12334c');teal=colors.HexColor('#168a9b')
    styles['BodyText'].fontSize=9.5;styles['BodyText'].leading=13;styles['BodyText'].spaceAfter=6;styles['BodyText'].textColor=colors.HexColor('#23364a')
    styles['Heading2'].textColor=navy;styles['Heading2'].fontSize=14;styles['Heading2'].leading=18;styles['Heading2'].spaceBefore=12;styles['Heading2'].spaceAfter=8
    styles['Heading3'].textColor=navy;styles['Heading3'].fontSize=11;styles['Heading3'].leading=14
    styles.add(ParagraphStyle('ClientHero',parent=styles['Heading1'],fontSize=24,leading=28,textColor=navy,spaceAfter=12))
    styles.add(ParagraphStyle('ClientEyebrow',parent=styles['BodyText'],fontSize=8.5,leading=11,textColor=teal,spaceAfter=8))
    styles.add(ParagraphStyle('ClientCell',parent=styles['BodyText'],fontSize=9,leading=12,spaceAfter=0))
    styles.add(ParagraphStyle('ClientHeader',parent=styles['ClientCell'],fontName='Helvetica-Bold',textColor=colors.white))
    for kind,value in readable_blocks(store,rid):
        if kind=='pagebreak':story.append(PageBreak());continue
        if kind=='costchart':story.extend([cost_chart(value,pdf=True),Spacer(1,8)]);continue
        if kind in ('table','clienttable','summarytable'):
            data=[[Paragraph(('<b>'+linked_text(cell,pdf=True)+'</b>') if value[0][0]=='Cost component' and i==len(value)-1 else linked_text(cell,pdf=True),styles['ClientHeader'] if i==0 else styles['ClientCell']) for cell in row] for i,row in enumerate(value)]
            widths=[516/len(value[0])]*len(value[0])
            if kind=='clienttable' and len(widths)==4:widths=[105,190,135,86]
            if value[0][0]=='Cost component':widths=[345,171]
            if value[0][0]=='Reference':widths=[64,352,100]
            if value[0][:2]==['Dilution','Pull from']:widths=[52,90,58,52,60,62,65,77]
            table=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),navy),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f4f7fa')]),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#dfe7ee')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
            if value[0][0]=='Cost component':
                table.setStyle(TableStyle([('BACKGROUND',(0,-1),(-1,-1),colors.HexColor('#e4f1f4')),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
                story.extend([KeepTogether([table,Spacer(1,8)])])
            elif value[0][:2]==['Core fact','Saved value']:
                preceding=story.pop() if story and isinstance(story[-1],Paragraph) and story[-1].getPlainText()=='Core kit facts and evidence coverage' else None
                story.append(KeepTogether(([preceding] if preceding else [])+[table,Spacer(1,8)]))
            elif value[0][:2]==['Input','Quantity / rate equation']:
                preceding=story.pop() if story and isinstance(story[-1],Paragraph) and story[-1].getPlainText()=='Estimate assumptions and quantities' else None
                story.append(KeepTogether(([preceding] if preceding else [])+[table,Spacer(1,8)]))
            elif value[0][:2]==['Parameter','Initial kits']:
                preceding=story.pop() if story and isinstance(story[-1],Paragraph) and story[-1].getPlainText()=='Initial and repeat kit requirements' else None
                story.append(KeepTogether(([preceding] if preceding else [])+[table,Spacer(1,8)]))
            else:story.extend([table,Spacer(1,8)])
        else:
            text=value.replace('–','-').replace('—','-').replace('×','x')
            style=styles['ClientHero'] if kind=='hero' else styles['ClientEyebrow'] if kind=='eyebrow' else styles['Heading2'] if kind=='heading' else styles['Heading3'] if kind=='summaryheading' else styles['BodyText']
            story.append(Paragraph(html.escape(text),style))
    packet=store.run(rid)['data'].get('packet',{});details=packet.get('report_details',{})
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#52616b'))
        ref=details.get('project_reference') or 'BIO-'+rid[:8].upper()
        canvas.drawString(48,28,ref+' | Version '+str(packet.get('planning_revision',1)))
        canvas.drawRightString(564,28,'Page '+str(doc.page));canvas.restoreState()
    ClientDocument(out,title='Bioanalytical client planning package',pagesize=(612,792),leftMargin=48,rightMargin=48,topMargin=42,bottomMargin=44).build(story,onFirstPage=footer,onLaterPages=footer)
    report=out.getvalue()
    return append_manual_pdf(report,manual_attachment or selected_manual_attachment(store,rid)) if include_manual else report


def csv_bytes(rows):
    f=io.StringIO()
    keys=list(dict.fromkeys(k for row in rows for k in row))
    if keys:
        w=csv.DictWriter(f,fieldnames=keys); w.writeheader()
        for row in rows: w.writerow({k:canonical(v) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    return f.getvalue().encode('utf-8-sig')

def evidence_zip(store,rid,include_manual=False):
    if not store.verify(rid): raise ValueError('Audit chain verification failed.')
    state=store.run(rid)['data']; packet=state.get('packet',{})
    manual=selected_manual_attachment(store,rid) if include_manual else None
    files={'report/report.html':html_report(store,rid).encode(),'report/report.pdf':pdf_report(store,rid,include_manual=include_manual,manual_attachment=manual),
        'intake.json':canonical(state['case']).encode(),'packet.json':canonical(packet).encode(),
        'tasks.json':canonical(store.tasks(rid)).encode(),'events.jsonl':'\n'.join(canonical(e) for e in store.events(rid)).encode(),
        'approvals.json':canonical(store.decisions(rid)).encode(),'usage.csv':csv_bytes(store.usage(rid)),
        'finding-scopes.json':canonical({'policy':SCOPE_POLICY,'selected_kit':packet.get('selected_kit'),'findings':scoped_findings(packet)}).encode(),
        'reviewed-findings.json':canonical(packet.get('finding_history',[])).encode(),
        'cell-evidence-details.json':canonical({k['id']:k.get('cell_evidence',{}) for k in packet.get('candidates',[])}).encode(),
        'research-scope.json':canonical(packet.get('research_scope',{})).encode(),
        'screened-candidates.json':canonical(packet.get('screened_candidates',[])).encode(),
        'reviewer-cell-edits.json':canonical({k['id']:k.get('reviewer_edits',{}) for k in packet.get('candidates',[])}).encode(),
        'report-details.json':canonical(packet.get('report_details',{})).encode(),
        'cost-policy.json':canonical({'overhead_on_labor':.15,'profit_uplift':False,'instrument_usd_per_plate':{'SpectraMax':10,'Bio-Plex':35,'MSD':35},'basis':packet.get('cost',{}).get('instrument_cost_basis',{})}).encode(),
        'candidates.csv':csv_bytes(packet.get('candidates',[])),
        'validation-volume.csv':csv_bytes(packet.get('volume',{}).get('rows',[])),
        'costs.csv':csv_bytes(packet.get('cost',{}).get('lines',[])),
        'authorship.json':canonical({'agent_drafts':'See agent_output events and section artifacts','human_text':'Reviewer cell edits, finding dispositions and decision comments are separately recorded; direct report editing is not supported.',
            'limitation':'Imported intake prose and external editing need additional per-person attribution before course submission.'}).encode(),
        'reconstruction-guide.txt':b'Inspect packet.json; follow candidate evidence source IDs into sources. Recompute calculations from intake and proposed plan. Verify decisions match packet hash. Distinguish synthetic fixtures from live runs.',
        'failure-reflection.txt':b'Actual errors, tool failures and QA findings appear in events.jsonl. Human catches must be described by the reviewer in return comments; none are inferred automatically.'}
    if manual:
        files['manuals/'+manual['metadata']['filename']]=manual['bytes']
        files['manuals/source-record.json']=canonical(manual['metadata']).encode()
    files['supporting-documents/register.json']=canonical(packet.get('supporting_documents',[])).encode()
    from .supporting_documents import load as load_supporting_document
    for record in packet.get('supporting_documents',[]):
        if record.get('include_in_bundle'):
            raw,_=load_supporting_document(store,record)
            files['supporting-documents/'+record['id']+record['extension']]=raw
    for revision in store.revisions(rid):files[f"planning-revisions/revision-{revision['revision']}.json"]=revision['data'].encode()
    for sid,source in packet.get('sources',{}).items(): files['sources/'+digest(sid)[:16]+'.json']=canonical(source).encode()
    base=Path(__file__).parent
    for path in (base/'skills').glob('*.md'): files['agents-and-skills/'+path.name]=path.read_bytes()
    manifest={'run_id':rid,'mode':state['mode'],'exported_at':now(),'released':released(store,rid),'packet_hash':packet_hash(packet),
        'files':{name:digest(content.hex()) for name,content in files.items()},'hash_method':'SHA256 of canonical JSON string of file hex bytes',
        'limitations':['Self-attested local identities','Desktop authoring inference usage unavailable','Local audit chain is not immutable to administrator']}
    files['manifest.json']=canonical(manifest).encode()
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in files.items(): z.writestr(name,content)
    store.event(rid,'evidence_export','requester',{'packet_hash':packet_hash(packet),'mode':state['mode'],'released':manifest['released']})
    return output.getvalue()
