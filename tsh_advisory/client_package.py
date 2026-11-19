"""Client-facing decision pages, using the same saved facts as the technical packet."""
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from .policy import packet_hash,current_decisions,SECTIONS,released
from .comparison import recommendation_reasons
from .findings import scoped_findings
from .review_views import protocol_rows
from .estimate_basis import estimate_rows,summary_cost_chart


def currency(value,code='USD'):
    if value is None:return 'Not available'
    try:return ('$' if code=='USD' else code+' ')+f'{Decimal(str(value)):,.2f}'
    except Exception:return str(value)


def accepted_assumptions(packet):
    latest={f.get('id',str(i)):f for i,f in enumerate(packet.get('finding_history',[]))}
    return [f for f in latest.values() if f.get('status')=='accepted' and f.get('disposition',{}).get('action')=='accepted']


def client_summary_blocks(store,rid,lead_time):
    run=store.run(rid);state=run['data'];p=state['packet'];case=p.get('case',state['case'])
    v=p.get('volume',{});cost=p.get('cost',{});details=p.get('report_details',{})
    selected=next((k for k in p.get('candidates',[]) if k['id']==p.get('selected_kit')),None)
    decisions=current_decisions(store,rid,packet_hash(p))
    approved=sum(decisions.get(('scientific',s),{}).get('action')=='approve' for s in SECTIONS)
    director=decisions.get(('director','project'),{}).get('action','pending')
    current_kit=decisions.get(('scientific','recommendation'),{})
    kit_approved=current_kit.get('action')=='approve' and current_kit.get('selected_kit')==p.get('selected_kit')
    complete=approved==len(SECTIONS) and director=='approve'
    state_label='SYNTHETIC SOFTWARE TEST - PLANNING DEMONSTRATION' if run['mode']=='fixture' else 'APPROVED PLANNING PACKAGE' if released(store,rid) else 'DRAFT - APPROVAL PENDING'
    date=datetime.now(ZoneInfo('America/New_York')).strftime('%d %b %Y')
    ref=details.get('project_reference') or 'BIO-'+rid[:8].upper()
    b=[]
    def add(kind,value):b.append((kind,value))
    def table(headers,rows):add('clienttable',[headers]+[[str(x) if x is not None else 'Not available' for x in row] for row in rows])
    add('eyebrow','BIOANALYTICAL PLANNING / CLIENT DECISION BRIEF')
    add('hero',case['title'])
    add('status',state_label)
    add('summaryparagraph',f"Client: {details.get('client_name') or 'Not specified'} | Reference: {ref} | Version: {p.get('planning_revision',1)} | Issued: {date}")
    add('summaryheading','Scientific approval summary')
    table(['Estimated project cost','Assay plates / kits','Validation matrix'],[[currency(cost.get('internal_cost'),cost.get('currency','USD'))+(' - incomplete subtotal' if cost.get('incomplete') else ''),f"{v.get('initial_kits','?')} initial + {v.get('repeat_kits','?')} repeat = {v.get('kits','?')}",f"{v.get('total_ul_all_lots','?'):,} µL total" if isinstance(v.get('total_ul_all_lots'),(int,float)) else 'Not calculated']])
    add('summaryheading','Selected kit and intended use')
    add('summaryparagraph',(('Approved kit: ' if kit_approved else 'Approval pending. Selected for review: ')+selected['name']+' / '+selected['catalog']+' ('+selected['manufacturer']+').') if selected else 'No candidate selected.')
    add('summaryparagraph','Intended use: '+case.get('intended_use','Not specified'))
    add('summaryparagraph','Lead time: '+lead_time(p,selected)+'.')
    add('summaryparagraph',p.get('research_scope',{}).get('method','Bounded candidate assessment; not an exhaustive market review.') if p.get('research_scope',{}).get('deep_kit_limit') else 'Candidate assessment uses retained sources; it is not an exhaustive market review.')
    add('summaryheading','Six selection factors and trade-offs')
    if selected:
        from .selection import selection_factors
        table(['Selection factor','Current assessment'],[[r['Selection factor'],r['Current assessment']] for r in selection_factors(p,selected,brief=True)])
        recommendation=next((k for k in p.get('candidates',[]) if k['id']==p.get('recommended_kit')),None)
        provisional=p.get('recommendation_refresh',{}).get('status')!='clear_rule_based_choice'
        add('summaryparagraph','Planning recommendation: '+(recommendation['catalog']+(' — provisional' if provisional else ' — supported by recorded comparison') if recommendation else 'Pending')+'. Scientist selection and approval remain separate.')
    else:add('summaryparagraph','Select a kit before finalizing the recommendation.')
    add('summaryheading','Project and review status')
    table(['Scientific / cost review','Manager / director'],[[f"{approved} of {len(SECTIONS)} sections approved; reviewer: {case.get('scientific_reviewer') or 'Not assigned'}",director.capitalize()+'; '+(case.get('director') or 'Not assigned')]])
    add('pagebreak','')
    add('eyebrow','CLIENT SUMMARY / VALIDATION PLAN')
    add('hero','Validation plan at a glance')
    add('summaryparagraph',f"{case.get('lot_count','?')} distinct pooled lots | {case.get('complete_repeats',1)} complete repeat set(s) | Study samples and validation materials are budgeted separately.")
    rows=protocol_rows(p.get('plan'),case,v)
    plan_rows=[]
    for row in rows:
        conditions=row['Conditions or endpoints']
        if row['Parameter']=='Long-term stability':
            e=next((e for e in p.get('plan',{}).get('experiments',[]) if e['parameter']=='Long-term stability'),{})
            temperatures=', '.join(case.get('long_term_storage_conditions',[]))
            conditions=str(len(e.get('conditions',[])))+' assessments'+(' at '+temperatures if temperatures else '')+'; full schedule in Appendix B'
        if len(conditions)>100:conditions=conditions[:97]+'... (full conditions in Appendix B)'
        plan_rows.append([row['Parameter'],conditions,str(row['Lots'])+' lots × '+str(row['Wells per lot per condition'])+' wells',row['Initial sample wells']])
    table(['Parameter','Conditions / endpoints','Per condition','Initial wells'],plan_rows)
    add('summaryheading','Precision and Accuracy / plate allocation')
    add('summaryparagraph',f"{case.get('precision_accuracy_plates',6)} initial Precision and Accuracy plates. Each plate includes {case.get('pa_blank_wells',2)} blank wells + {case.get('pa_standard_levels',7)} standards × {case.get('pa_standard_replicates',2)} wells + {case.get('qc_levels',5)} QC levels × {case.get('qc_wells_per_level',6)} wells. Each initial plate hosts at most one additional parameter; repeat plates and long-term assessments are allocated separately.")
    add('summaryheading','Material requirements and study feasibility')
    study=p.get('study',{})
    table(['Validation material','Separate study-sample allocation'],[[f"{v.get('total_ul_per_lot','?')} µL per lot; {v.get('total_ul_all_lots','?')} µL total. Includes 200 µL per lot for aliquoting.",f"Available: {study.get('available_ul','?')} µL. Required: {study.get('total_ul','?')} µL including repeat and handling. Remaining balance: {study.get('remaining_ul','?')} µL. Preparation status: {study.get('status','unresolved')}; dilution suitability remains under scientist review."]])
    add('summaryparagraph','Kit stock is included in the kits. Biological matrix volumes include the selected dilution, preparation reserve, repeat reserve and handling allowances. Full preparation and plate details appear in Appendices B-E.')
    add('summaryheading','Items requiring a client/reviewer decision')
    flags=[f for f in scoped_findings(p) if f.get('requires_attention')]
    if flags:
        for f in flags[:3]:add('summaryparagraph',f['section'].capitalize()+': '+(f['message'] if len(f['message'])<=220 else f['message'][:217]+'... (see Appendix F)'))
        if len(flags)>3:add('summaryparagraph',f'{len(flags)-3} additional current advisories are listed in Appendix F.')
    else:add('summaryparagraph','No current needs-attention flags. Approval status remains as recorded on page 1.')
    if run['mode']=='fixture':add('summaryparagraph','Test decisions do not establish scientific clearance or authorize laboratory work.')
    add('pagebreak','')
    add('eyebrow','CLIENT SUMMARY / ESTIMATE')
    add('hero','Project estimate')
    add('summaryparagraph',('Known subtotal - incomplete estimate: ' if cost.get('incomplete') else 'Estimated project total: ')+currency(cost.get('internal_cost'),cost.get('currency','USD')))
    add('costchart',summary_cost_chart(cost.get('lines',[])))
    table(['Cost component','Estimated amount ('+cost.get('currency','USD')+')'],[[line['category'],currency(line['usd'],cost.get('currency','USD'))] for line in cost.get('lines',[])]+[['TOTAL'+(' - INCOMPLETE' if cost.get('incomplete') else ''),currency(cost.get('internal_cost'),cost.get('currency','USD'))]])
    basis=cost.get('instrument_cost_basis',{})
    add('summaryparagraph','Costs use the saved project assumptions, including 15% labor overhead and recorded contingency. No profit uplift. Detailed rates, shipping allowances and calculations are in Appendix C. The chart groups smaller costs; the table itemizes them.')
    if cost.get('incomplete'):add('summaryparagraph','Complete quote unavailable until the missing inputs below are supplied.')
    for issue in cost.get('unresolved',[]):add('summaryparagraph','Estimate input required: '+issue)
    scenarios=cost.get('scenarios',{})
    if scenarios:
        table(['Scenario','Known subtotal' if cost.get('incomplete') else 'Estimated total','Assumptions changed'],[
            ['Lower',currency(scenarios.get('lower_assumption_price')),'Labor −25%; kit unit price −30%'],
            ['Base',currency(scenarios.get('base_price')),'Saved planning assumptions'],
            ['Higher',currency(scenarios.get('higher_assumption_price')),'Labor +25%; kit unit price +30%']])
        add('summaryparagraph','Illustrative planning scenarios; kit quantities are fixed. Not confidence intervals or binding quotes.')
    add('summaryheading','Accepted planning / evidence assumptions')
    accepted=accepted_assumptions(p)
    if accepted:
        for f in accepted[:2]:add('summaryparagraph',f.get('disposition',{}).get('reason','Accepted planning assumption')+' - '+f.get('disposition',{}).get('actor','Reviewer'))
        if len(accepted)>2:add('summaryparagraph','Additional accepted assumptions are documented in Appendix F.')
    else:add('summaryparagraph','No accepted planning/evidence assumptions recorded.')
    add('summaryparagraph','Public kit prices and reviewer estimates are identified in Appendix A. Study-sample analysis beyond the validation plan is excluded from this estimate unless explicitly included. The full evidence bundle accompanies this report.')
    add('pagebreak','')
    return b
