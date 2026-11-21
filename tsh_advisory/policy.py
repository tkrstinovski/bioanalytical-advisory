from .schemas import Intake, Candidate, Plan, Findings
from .calculations import study_volume
from .store import digest, canonical, now, uid
from .names import matches
from .findings import blocking_findings,SCOPE_POLICY
import copy

SECTIONS=['recommendation','validation','volume','cost','evidence']
POSITIVE={'scientific':['Evidence supports intended use','Assumptions accepted for planning'],
          'director':['Scientific and financial case accepted']}
NEGATIVE=['Insufficient evidence','Scientific design change required','Calculation or costing correction required','Scope change required','Pricing or margin revision required','Resource/timeline concern','Budget ceiling exceeded','Do not proceed','Other']

def packet_hash(packet): return digest(packet)

def selected_review_gaps(packet):
    """Explain current missing inputs without changing or approving the saved packet."""
    kit=next((k for k in packet.get('candidates',[]) if k['id']==packet.get('selected_kit')),None)
    if not kit:return [{'Area':'Kit selection','Missing or unresolved':'No selected kit.','What is needed':'Select a kit for this planning packet.'}]
    sources=packet.get('sources',{});rows=[]
    requirements={
      'identity':('Kit identity / target / species','Manual/vendor passage identifying catalog, analyte and supported species.'),
      'matrix':('Sample matrix','Manual/vendor passage listing the requested matrix, such as serum.'),
      'range':('Manufacturer curve range','Documented range and units with source/page; expected study concentrations are not required.'),
      'volume':('Sample input / dilution','Manual instructions for sample input per well and dilution, with source/page.')}
    aliases={'identity':['kit_identity'],'matrix':['sample_matrix'],'range':['curve_range','assay_range'],'volume':['sample_input','sample_volume']}
    for gate,(area,needed) in requirements.items():
        evidence=kit.get('evidence',{}).get(gate)
        alternative=next((label for label in aliases[gate] if label in kit.get('evidence',{})),None)
        if not evidence:
            detail=f"Citation is saved under '{alternative}' but is not mapped to the '{gate}' check." if alternative else 'No claim-level citation is recorded for this check.'
            rows.append({'Area':area,'Missing or unresolved':detail,'What is needed':needed+' A complete evidence entry includes source ID, page/location and an exact supporting passage.'});continue
        source=sources.get(evidence.get('source_id'))
        problems=[]
        if not source:problems.append('Referenced source snapshot is missing')
        else:
            if not source.get('owner','').strip():problems.append('Source owner is blank')
            if not evidence.get('quote') or evidence['quote'] not in source.get('text',''):problems.append('Supporting passage is absent or does not match the saved source')
            if source.get('content_hash')!=digest(source.get('text','')):problems.append('Source snapshot hash does not match')
            if source.get('synthetic') and packet.get('mode')=='live':problems.append('Synthetic source cannot support live approval')
        if not evidence.get('locator','').strip():problems.append('Page/location is blank')
        if problems:rows.append({'Area':area,'Missing or unresolved':'; '.join(problems),'What is needed':needed})
    for key,label in [('well_input_ul','Sample input per well'),('handling_ul','Study-sample handling allowance')]:
        if kit.get(key) is None:rows.append({'Area':'Study volume','Missing or unresolved':label+' is blank.','What is needed':label+' in µL; handling is a reviewer planning assumption, separate from the validation-lot handling allowance.' if key=='handling_ul' else 'Documented assay sample input in µL per well.'})
    case=Intake.model_validate(packet['case'])
    if case.available_ul is None:rows.append({'Area':'Study volume','Missing or unresolved':'Available study-sample volume is blank.','What is needed':'Enter the per-sample allocation in intake.'})
    evaluated=copy.deepcopy(packet);quality(case,evaluated)
    current=next(k for k in evaluated['candidates'] if k['id']==kit['id'])
    for reason in current.get('eligibility',{}).get('reasons',[]):
        if 'mismatch' in reason or 'gate not passed' in reason:rows.append({'Area':'Selected kit','Missing or unresolved':reason,'What is needed':'Review the documented kit facts and this specific current check; instrument name matching is not required.'})
    study=study_volume(case,Candidate.model_validate({k:v for k,v in kit.items() if k in Candidate.model_fields}))
    if study.get('status')=='fail':rows.append({'Area':'Study volume','Missing or unresolved':f"Requires {study['total_ul']:g} µL; only {study['available_ul']:g} µL is allocated.",'What is needed':'Revise the scientifically justified dilution/sample plan or select another kit.'})
    for issue in packet.get('cost',{}).get('unresolved',[]):rows.append({'Area':'Cost','Missing or unresolved':issue,'What is needed':'Provide the missing estimate in Candidate comparison or Volumes. A nonpublic kit price can be a reviewer estimate.'})
    return rows

def planning_review_gaps(packet):
    """Kit citation mapping details belong in technical records, not duplicate review flags."""
    citation_topics={'Kit identity / target / species','Sample matrix','Manufacturer curve range','Sample input / dilution'}
    return [row for row in selected_review_gaps(packet) if row['Area'] not in citation_topics]


def quality(case: Intake,packet):
    findings=[]
    def add(section,msg,severity='major',scope='project',candidate_ids=None):
        code='COST_INPUTS' if msg=='Cost estimate has missing material or kit pricing.' else 'STUDY_VOLUME' if 'study volume' in msg.lower() else 'UNSUPPORTED_CLAIM' if 'scientific eligibility' in msg else 'REVIEWER_DIRECTION'
        findings.append(dict(section=section,severity=severity,message=msg,owner='reviewer',scope=scope,candidate_ids=candidate_ids or [],affects_selection_rationale=False,issue_code=code,scope_class='planning'))
    sources=packet.get('sources',{})
    if not packet.get('candidates'): add('recommendation','No candidate supported by retained evidence.')
    eligible=[]
    for c in packet.get('candidates',[]):
        kit=Candidate.model_validate({k:v for k,v in c.items() if k in Candidate.model_fields}); reasons=[]
        for field,expected in [('analyte',case.analyte),('species',case.species),('matrix',case.matrix)]:
            if not matches(expected,getattr(kit,field),field):reasons.append(f'{field} mismatch')
        from .names import strain_check
        strain=strain_check(case.model_dump(),kit.model_dump())
        if strain['mismatch']:reasons.append('strain mismatch: '+strain['requested']+' versus documented '+strain['reported'])
        for gate in ['identity','matrix','range','volume']:
            # Source-backed equivalent names are resolved by canonical matching,
            # rather than a model's exact-string gate. Other evidence checks remain.
            equivalent=(gate=='identity' and not any('mismatch' in r for r in reasons)) or (gate=='matrix' and matches(case.matrix,kit.matrix,'matrix')) or gate=='range' or (gate=='volume' and study_volume(case,kit).get('status')=='pass')
            if kit.gates.get(gate)!='pass' and not equivalent: reasons.append(gate+' gate not passed')
            e=kit.evidence.get(gate)
            source=sources.get(e.source_id) if e else None
            if not source or not source.get('owner','').strip() or not e.locator.strip() or e.quote not in source.get('text',''):
                reasons.append(gate+' lacks inspectable source support')
            elif source.get('content_hash')!=digest(source['text']): reasons.append('source snapshot hash mismatch')
            if source and source.get('synthetic') and packet.get('mode')!='fixture': reasons.append('synthetic evidence in live packet')
        if study_volume(case,kit).get('status')!='pass': reasons.append('study volume not feasible or unresolved')
        c['eligibility']={'status':'pass' if not reasons else 'unresolved','reasons':reasons}
        if not reasons: eligible.append(kit.id)
    selected=packet.get('selected_kit')
    if selected not in eligible: add('recommendation','Selected candidate has unresolved scientific eligibility.','critical','selected_kit' if selected else 'project',[selected] if selected else [])
    chosen=next((k for k in packet.get('candidates',[]) if k['id']==selected),None)
    if chosen and chosen.get('well_input_ul') is not None and chosen['well_input_ul']<10:
        add('volume','Selected kit requires plating below 10 µL. A reviewed alternative preparation/assay procedure is required.','critical','selected_kit',[selected])
    if not case.scientific_reviewer.strip(): add('evidence','A named scientific/cost reviewer must own decision evidence.')
    if not packet.get('plan'): add('validation','No validation plan.')
    if packet.get('mode')=='live' and any(c.get('kit_price') is not None and c.get('price_source') not in sources and not c.get('price_source','').startswith('reviewer:') for c in packet.get('candidates',[]) if c['id']==selected):
        add('cost','Selected kit price has no retained public source.',scope='selected_kit',candidate_ids=[selected])
    if not packet.get('cost') or packet['cost'].get('incomplete'): add('cost','Cost estimate has missing material or kit pricing.')
    if not packet.get('volume') or packet['volume'].get('status')=='unresolved': add('volume','Validation volume cannot yet be calculated.')
    if packet.get('mode')=='live' and packet.get('volume',{}).get('matrix_totals_complete') is False:
        add('volume','QC matrix preparation/dilution is unresolved; displayed validation volume is a known subtotal.')
    return findings

def current_decisions(store,rid,h):
    result={}
    for d in store.decisions(rid):
        if d['packet_hash']==h: result[(d['role'],d['section'])]=d
    return result

def scientific_complete(store,rid):
    run=store.run(rid); packet=run['data'].get('packet',{}); h=packet_hash(packet)
    decisions=current_decisions(store,rid,h)
    return all(decisions.get(('scientific',s),{}).get('action')=='approve' for s in SECTIONS)

def record_decision(store,rid,role,actor,section,action,reason,comments='',selected_kit=None,expected_hash=None,simulation=False,instrument_confirmed=False):
    store.ensure_active(rid)
    if not store.verify(rid): raise ValueError('Audit chain invalid; release stopped.')
    run=store.run(rid); snapshot=store.case(run['case_id'])
    if snapshot['version']!=run['case_version']: raise ValueError('Intake changed; apply updated intake and recalculate this run, or start a new research run. Existing approvals are stale.')
    state=run['data']; case=Intake.model_validate(state['case']); packet=state['packet']; h=packet_hash(packet)
    if simulation and run['mode']!='fixture':raise ValueError('Simulated approvals are permitted only in TEST DATA runs.')
    if expected_hash!=h: raise ValueError('Report changed; reload before deciding.')
    expected=case.scientific_reviewer if role=='scientific' else case.director
    if role not in POSITIVE or not actor.strip() or actor.strip().casefold()!=expected.strip().casefold(): raise ValueError('Named role identity mismatch.')
    if role=='director' and actor.strip().casefold()==case.scientific_reviewer.strip().casefold(): raise ValueError('Director must be distinct from scientific/cost reviewer.')
    if action not in ['approve','return','reject']: raise ValueError('Unsupported decision.')
    if section not in (SECTIONS if role=='scientific' else ['project']): raise ValueError('Invalid review section.')
    if reason not in (POSITIVE[role] if action=='approve' else NEGATIVE): raise ValueError('Choose a reason compatible with the decision.')
    if (reason=='Other' or action=='return') and not comments.strip(): raise ValueError('Provide an actionable comment.')
    if action=='approve':
        if role=='scientific' and section=='recommendation':
            if selected_kit!=packet.get('selected_kit'): raise ValueError('Select the evaluated kit explicitly; evaluate an alternative before approval.')
            kit=next((k for k in packet['candidates'] if k['id']==selected_kit),None)
            if not kit: raise ValueError('Select an existing kit.')
        if role=='director':
            if not scientific_complete(store,rid): raise ValueError('Current scientific/cost approval required.')
    data=dict(id=uid(),run_id=rid,section=section,role=role,actor=actor,action=action,reason=reason,comments=comments,
        selected_kit=selected_kit,packet_hash=h,timestamp=now(),identity_assurance='self-attested classroom role',mode=run['mode'],simulation=simulation,
        advisory_findings_at_decision=copy.deepcopy(packet.get('findings',[])),approval_scope='TEST WORKFLOW ONLY — not scientific clearance or laboratory authorization' if simulation else 'Planning document review',finding_scope_policy=SCOPE_POLICY)
    if selected_kit:
        data['kit_record']=next((k for k in packet.get('candidates',[]) if k['id']==selected_kit),None)
    if role=='scientific' and section=='recommendation' and action=='approve':
        from .kit_library import display_kit
        data['instrument_confirmation']={'confirmed':bool(instrument_confirmed),'responsible_scientist':actor,'available_instruments_from_intake':case.instruments,'vendor_instruments':display_kit(data.get('kit_record') or {}).get('vendor_instruments',[]),'basis':'Scientist confirmation; no automated instrument/platform matching requirement.'}
    with store.connect() as c:
        c.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?)',(data['id'],rid,section,role,actor,action,h,canonical(data)))
        store._event(c,rid,'human_decision',actor,data)
    return data

def released(store,rid):
    run=store.run(rid); state=run['data']; packet=state.get('packet',{})
    if run['mode']!='live' or run['stopped'] or not store.verify(rid): return False
    if store.case(run['case_id'])['version']!=run['case_version']: return False
    d=current_decisions(store,rid,packet_hash(packet)).get(('director','project'),{})
    return scientific_complete(store,rid) and d.get('action')=='approve' and state.get('status')=='authorized'
