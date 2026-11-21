"""Transparent, unscored comparative support; eligibility facts are not superiority claims."""
from .names import matches
import re

RUBRIC=[('Species / analyte / matrix','Essential','Recorded manufacturer support for the intake'),
        ('Sample consumption','High','Input per well and practical preparation with repeat reserve'),
        ('Workflow / equipment','High','Kit-manual workflow and available equipment; scientist confirms'),
        ('Evidence strength','High','Claim-level source passages or identified reviewer assertions'),
        ('Cost','Medium','Same requested scope; public price or labeled estimate'),
        ('Lead time','Medium','Public information or labeled reviewer estimate')]


def selection_analysis(packet,kit):
    ids=packet.get('finalist_ids',[])
    others=[k for k in packet.get('candidates',[]) if k['id']!=kit['id'] and (not ids or k['id'] in ids)]
    reasons=[];tradeoffs=[]
    comparable=[k for k in others if k.get('well_input_ul') is not None]
    value=kit.get('well_input_ul')
    if value is not None and comparable:
        reference=min(comparable,key=lambda k:k['well_input_ul'])
        if value<reference['well_input_ul']:reasons.append(f"Sample-input advantage: {value:g} µL/well versus {reference['well_input_ul']:g} µL/well for {reference['catalog']}. Practical preparation is calculated separately.")
        elif value>reference['well_input_ul']:
            reasons.append(f"Sample-input trade-off: {value:g} µL/well versus {reference['well_input_ul']:g} µL/well for {reference['catalog']}; the selected dilution and allocation require review.")
            tradeoffs.append(reasons[-1])
        else:reasons.append(f"Sample input is tied at {value:g} µL/well with {reference['catalog']}; it does not distinguish the choice.")
    else:reasons.append(f"Recorded sample input: {value:g} µL/well; comparable input is not established for other candidates." if value is not None else 'Sample-input comparison is unresolved.')
    matching=[f for f in ('species','analyte','matrix') if matches(packet.get('case',{}).get(f,''),kit.get(f,''),f)]
    from .evidence_details import core_fact_assessment
    linked_fields={row['Core fact'].casefold() for row in core_fact_assessment(packet,kit) if row['Included in supported count']}
    source_status='Source passages are linked for these matching fields.' if matching and all(('sample matrix' if field=='matrix' else field) in linked_fields for field in matching) else 'Source passages are not linked for every matching field.'
    reasons.append('Recorded '+', '.join(matching)+' values match the intake. '+source_status if matching else 'Recorded fit requires scientist review; source linkage is assessed separately.')
    price=kit.get('kit_price');priced=[k for k in others if k.get('kit_price') is not None]
    if price is not None and priced:
        ref=min(priced,key=lambda k:k['kit_price'])
        reasons.append(f"Price comparison: ${price:,.2f}/kit versus ${ref['kit_price']:,.2f}/kit for {ref['catalog']}. This is a unit-price comparison, not an equivalent full-project quote.")
        if price>ref['kit_price']:tradeoffs.append(f"Higher recorded kit price than {ref['catalog']}; total quantities and price basis must also be considered.")
    else:reasons.append(f"Cost assumption: ${price:,.2f}/kit; alternative pricing is incomplete, so no lowest-cost claim is made." if price is not None else 'Price advantage is not established; a public price or reviewer estimate is needed.')
    reasons.append('Workflow consideration: '+kit.get('assay_duration','Manual duration not recorded')+'. Equipment requirements remain subject to scientist confirmation.')
    from .evidence_details import cell_evidence_detail
    linked=sum(cell_evidence_detail(packet,kit,field)['inspectable'] and not cell_evidence_detail(packet,kit,field)['needs_recheck'] for field in kit.get('cell_evidence',{}))
    reasons.append(f"Evidence basis: {linked} field-level reviewed source link(s). Manual facts, reviewer assertions and estimates are distinguished in cell evidence details; missing evidence is not a competitive advantage.")
    if not priced:tradeoffs.append('Alternative price information is incomplete; the comparison cannot establish a cost winner.')
    if not tradeoffs:tradeoffs.append('No overall superiority score is assigned. The scientist balances documented fit, workflow, evidence and estimated cost.')
    advantages=[r for r in reasons if r.startswith('Sample-input advantage:')]
    conclusion=('A recorded sample-input advantage supports consideration of this kit; the overall choice still balances workflow, evidence and cost.' if advantages else
                'Available records do not establish a clear overall winner. The scientist determines the selection using the disclosed trade-offs, ties and evidence limits.')
    return {'reasons':reasons,'tradeoffs':tradeoffs,'conclusion':conclusion,'rubric':RUBRIC,'basis':'Calculated comparison of saved facts; original agent rationale remains in the audit.'}


def candidate_metrics(packet,kit):
    """Same-scope deterministic comparison; never change the scientist's selection."""
    from .schemas import Intake,Candidate,Plan,CostAssumptions
    from .calculations import study_volume,validation_volume,cost_estimate
    from .planning import scope_costs
    from .evidence_details import cell_evidence_detail
    from .design import enforce_design
    known_fit=all(packet.get('case',{}).get(f) and kit.get(f) for f in ('species','analyte','matrix'))
    fit=('supported' if all(matches(packet['case'][f],kit[f],f) for f in ('species','analyte','matrix')) else 'mismatch') if known_fit else 'unknown'
    from .names import strain_check
    if strain_check(packet.get('case',{}),kit)['mismatch']:fit='mismatch'
    fields=('analyte','species','matrix','well_input_ul','dilution_factor','curve_range')
    from .evidence_details import core_fact_assessment
    evidence=sum(row['Included in supported count'] for row in core_fact_assessment(packet,kit))
    result={'fit':fit,'study_status':'unresolved','matrix_ul':None,'project_cost':None,'evidence_fields':evidence,'lead_days':None,'lead_unit':None,'lead_time':kit.get('reviewer_lead_time') or kit.get('lead_time') or 'Not documented'}
    lead=re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*(business days?|days?|weeks?)\s*',result['lead_time'],re.I)
    if lead:
        result['lead_days']=float(lead.group(2) or lead.group(1))*(7 if 'week' in lead.group(3).lower() else 1)
        result['lead_unit']='business_days' if 'business' in lead.group(3).lower() else 'calendar_days'
    try:
        case=Intake.model_validate(packet['case']);candidate=Candidate.model_validate({k:v for k,v in kit.items() if k in Candidate.model_fields})
        if case.parallel_start_from_kit:
            if candidate.dilution_factor is None:return result
            case.parallel_start_dilution=candidate.dilution_factor
        study=study_volume(case,candidate);result.update(study_status=study['status'],matrix_ul=study.get('total_ul'))
        if packet.get('plan') and packet.get('cost_assumptions'):
            plan=enforce_design(case,Plan.model_validate(packet['plan']))
            volume=validation_volume(case,candidate,plan)
            a,_=scope_costs(case,candidate,volume,CostAssumptions.model_validate(packet['cost_assumptions']))
            cost=cost_estimate(case,candidate,volume,a)
            if not cost['incomplete']:result['project_cost']=float(cost['internal_cost'])
    except (ValueError,KeyError,TypeError):
        result['calculation_note']='Candidate inputs do not yet support a complete same-scope calculation.'
    return result


def refresh_recommendation(packet,previous=None):
    """Conservative dominance, with no hidden weights or missing-data advantage."""
    candidates=packet.get('candidates',[])
    metrics={k['id']:candidate_metrics(packet,k) for k in candidates}
    possible=[k['id'] for k in candidates if metrics[k['id']]['fit']!='mismatch' and metrics[k['id']]['study_status']!='fail']
    def dominates(left,right):
        a,b=metrics[left],metrics[right]
        if a['fit']!='supported' or b['fit']!='supported' or a['study_status']!='pass' or b['study_status']!='pass':return False
        strict=False
        for key,direction in [('matrix_ul',-1),('project_cost',-1),('evidence_fields',1),('lead_days',-1)]:
            x,y=a[key],b[key]
            if key=='lead_days' and a['lead_unit']!=b['lead_unit']:return False
            if x is None and y is None:continue
            if x is None or y is None:return False
            if direction*x<direction*y:return False
            strict|=direction*x>direction*y
        return strict
    frontier=[cid for cid in possible if not any(dominates(other,cid) for other in possible if other!=cid)]
    clear=len(frontier)==1 and metrics[frontier[0]]['fit']=='supported' and metrics[frontier[0]]['study_status']=='pass'
    recommended=frontier[0] if clear else previous if previous in frontier else None
    return {'recommended_kit':recommended,'status':'clear_rule_based_choice' if clear else 'provisional_tie_or_missing_information' if frontier else 'no_supported_feasible_candidate','contenders':frontier,'metrics':metrics,'method':'Rule-based refresh of saved facts: scientific fit and practical study-volume feasibility first; then dominance across matrix demand, same-scope project cost, reviewed evidence coverage and comparable lead time. No weighted score. Missing facts never count as an advantage. Workflow/equipment requires scientist judgment. Original model recommendation is retained; scientist selection is unchanged.'}


def selection_factors(packet,kit,brief=False):
    from .evidence_details import core_fact_summary
    analysis=selection_analysis(packet,kit)
    m=packet.get('recommendation_refresh',{}).get('metrics',{}).get(kit['id']) or candidate_metrics(packet,kit)
    volume=f"{m['matrix_ul']:g} µL matrix per study sample including repeats/reserves; volume status: {m['study_status']}." if m['matrix_ul'] is not None else 'Practical sample-volume calculation unresolved.'
    cost=f"Estimated validation project cost: ${m['project_cost']:,.2f}; same intake scope and current cost assumptions." if m['project_cost'] is not None else 'Complete same-scope cost comparison unavailable; no lowest-cost claim.'
    if brief:
        brief_fit='Recorded fit matches intake; source verification is separate.' if m['fit']=='supported' else 'Recorded mismatch; review required.' if m['fit']=='mismatch' else 'Recorded fit incomplete; sources assessed separately.'
        return [{'Selection factor':'Scientific fit','Current assessment':brief_fit},
                {'Selection factor':'Practical sample volume','Current assessment':f"{m['matrix_ul']:g} µL/sample including repeat/reserves; {m['study_status']}." if m['matrix_ul'] is not None else 'Not yet calculated.'},
                {'Selection factor':'Workflow and equipment','Current assessment':(kit.get('assay_duration') or 'Assay duration not documented')[:100]+'; scientist confirms equipment.'},
                {'Selection factor':'Evidence support','Current assessment':core_fact_summary(packet,kit,brief=True)},
                {'Selection factor':'Total project cost','Current assessment':f"${m['project_cost']:,.2f}; same validation scope." if m['project_cost'] is not None else 'Complete same-scope estimate unavailable.'},
                {'Selection factor':'Lead time','Current assessment':m['lead_time']}]
    return [{'Selection factor':'Scientific fit','Current assessment':analysis['reasons'][1]},
            {'Selection factor':'Practical sample volume','Current assessment':volume},
            {'Selection factor':'Workflow and equipment','Current assessment':analysis['reasons'][3]},
            {'Selection factor':'Evidence support','Current assessment':core_fact_summary(packet,kit)},
            {'Selection factor':'Total project cost','Current assessment':cost},
            {'Selection factor':'Lead time','Current assessment':m['lead_time']+'; public information or labeled reviewer estimate.'}]
