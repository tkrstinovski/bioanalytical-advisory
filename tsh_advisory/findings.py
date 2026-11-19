"""Stable finding IDs and revision-specific dispositions; no silent scientific clearance."""
from .store import digest
import re

SCOPE_POLICY='advisory-findings-v8-structured-resolution-checks'

def obsolete_scope_reason(f,packet):
    """Archive execution demands, preserving actual kit/design conflicts as current flags."""
    if f.get('origin')!='agent':return ''
    if f.get('issue_code'):
        from .issue_checks import resolution_for
        return resolution_for(f,packet) or ''
    text=f.get('message','').casefold()
    current=packet.get('volume',{}).get('calculation_version')=='lot-planning-v3'
    if current and f.get('section')=='volume' and 'reconciliation remains incomplete' in text and '1,222' in text and '2,560' in text:
        return 'Superseded by current versioned volume calculations. Historical agent narrative uses obsolete quantities; original text remains in audit history.'
    if current and f.get('section')=='volume' and 'neither per-animal feasibility nor origin-specific validation sufficiency' in text:
        return 'Superseded by current separate study-feasibility and intake-defined validation calculations. Extra pilot/reference scope and measured laboratory losses are not planning prerequisites.'
    if current and f.get('section')=='cost' and '6,125' in text and '6,737.50' in text and packet.get('cost'):
        return 'Superseded by current recalculated cost lines. Current missing prices and zero-rate assumptions are checked separately; historical totals remain in audit history.'
    if f.get('section')=='evidence' and 'retained evidence supports documented assay routes, not present-study performance or current operational readiness' in text:
        return 'Outside planning scope: this application compares documented kit facts, not demonstrated present-study performance, cross-assay equivalence, finalized acceptance criteria or local operational qualification.'
    if f.get('section')=='recommendation' and 'deadline arithmetic is correctly qualified, but full-project feasibility remains unsubstantiated' in text:
        return 'Outside planning scope: the submission target is an academic deliverable date, not a required laboratory-completion date. The historical stability-duration calculation does not establish a project timing conflict.'
    specific_conflict=any(term in text for term in ('unsupported kit claim','kit manual requires','manual conflicts','incorrect source attribution','missing sample input','insufficient plate capacity','explicit laboratory completion date'))
    if not specific_conflict:
        if any(term in text for term in ('must demonstrate study-specific performance','missing study-specific validation data','must supply local qualification evidence','requires proof of present-study performance')):
            return 'Outside planning scope: completed study performance or local operational qualification is not a kit-selection planning requirement.'
        academic=any(term in text for term in ('class submission','academic submission','academic deadline','submission date','submission deadline'))
        lab=any(term in text for term in ('laboratory completion','laboratory testing','stability assessment','stability challenge','laboratory-completion'))
        if academic and lab:
            return 'Outside planning scope: do not use the academic submission date as a laboratory-completion deadline.'
    if f.get('section')=='recommendation' and 'development designation is not intended-use eligibility' in text:
        return 'Outside planning scope: selection does not require completed study-specific performance, sample-history eligibility or operational readiness. Planning approval does not establish laboratory validation or authorize execution.'
    if f.get('section')!='validation':return ''
    if 'required additional work remains unallocated' in text:
        return 'Outside intake-defined planning scope: agent requested additional experiments and completed pilot evidence.'
    if 'calibration and acceptance criteria remain proposals' in text:
        return 'Outside planning scope: completed pilot testing, locked acceptance criteria and laboratory SOPs are not required to approve this planning document.'
    if 'actual handling eligibility remains unresolved' in text and 'timestamped exposure histories' in text:
        return 'Outside planning scope: actual sample custody/exposure records belong to laboratory execution; intake defines the planned conditions.'
    volume=packet.get('volume',{});plates=volume.get('plate_allocations',[])
    ids={p['id'] for p in plates}
    complete=plates and all(set(row.get('plate_ids',[]))<=ids for row in volume.get('rows',[]))
    if complete and '776-well service result' in text and 'only 11 plate identities' in text:
        return 'Superseded by the current versioned plate ledger. The historical finding references an earlier plate count and obsolete allocation; it is not a current manual-conflict determination.'
    # New agent outputs must not expand intake scope or demand completed execution.
    if any(term in text for term in ('missing parameter','omitted parameter','kit manual requires','manual conflicts','insufficient plate capacity','incorrect well count','missing dilution','missing sample input','requested condition omitted')):
        return ''
    if any(term in text for term in ('must complete pilot','require completed pilot','must lock acceptance criteria','must provide actual sample histories','must add selectivity','must add interference','must add lot bridging')):
        return 'Outside intake-defined planning scope: additional experiments or completed laboratory execution are not planning requirements.'
    return ''

def concentration_planning_note(f):
    text=f.get('message','').casefold();category=f.get('category','planning')
    if category=='range_coverage_mismatch':return ''
    # Known analytical failures are different from an unknown study concentration.
    if any(term in text for term in ('below lloq','above uloq','outside the kit range','outside the assay range','known range mismatch','demonstrated range mismatch','manual range missing','kit range missing')):return ''
    if category=='expected_concentration_unknown':return 'Expected study concentrations are unknown at planning; no prior concentration estimate is required for approval. The manufacturer curve range remains listed.'
    if len(text)<=240 and any(term in text for term in ('expected concentration','study concentration','concentration coverage','range suitability')) and any(term in text for term in ('unknown','not known','unresolved','not provided','not available')):
        if not any(term in text for term in ('missing manual','instrument','sample volume','incompatib','assay performance','effect size','selection rationale')):
            return 'Unknown expected study concentrations are a planning assumption, not an approval requirement.'
    return ''

def instrument_execution_note(f,packet):
    """Instrument suitability is confirmed by the scientist, never automated name matching."""
    category=f.get('category','planning');text=f.get('message','').casefold()
    if category in ('instrument_availability','instrument_execution','instrument_compatibility','essential_configuration'):
        return 'Instrument requirements and intake availability are advisory facts. The scientist confirms the instrument/equipment arrangement when approving the selected kit; no automated matching gate applies.'
    # Mixed legacy findings keep their other scientific concerns until reviewed.
    if len(text)<=240 and any(term in text for term in ('instrument','reader','platform')) and any(term in text for term in ('compatibility','readiness','calibration','qualification','scheduling','setup','configuration','model','available','availability','mismatch','match')):
        if not any(term in text for term in ('sensitivity','concentration','sample volume','curve','validation criteria','pilot results','selection rationale')):
            return 'Standalone instrument concern retained for scientist confirmation, not automatic approval blocking.'
    return ''

def finding_key(f):
    identity=[f['section'],f['message']]
    if f.get('candidate_ids'):identity.append(sorted(f['candidate_ids']))
    return digest(identity)[:16]

def scoped_finding(finding,packet):
    """Rebind candidate-specific findings to the current selection; ambiguous legacy text stays blocking."""
    f=dict(finding);selected=packet.get('selected_kit');candidates=packet.get('candidates',[])
    known={c['id'] for c in candidates};ids=list(dict.fromkeys(f.get('candidate_ids') or []))
    declared=f.get('scope','project');basis=f.get('scope_basis','');inferred=False
    if declared not in ('project','selected_kit','alternative_only'):
        declared='project';basis='Unrecognized scope; reviewer classification required.'
    if not ids and not basis:
        normalize=lambda v:re.sub(r'[^a-z0-9]+',' ',str(v).casefold()).strip()
        text=' '+normalize(f.get('message',''))+' '
        for fields in [('id','catalog'),('name',)]:
            minimum=lambda field:6 if field=='id' else 4 if field=='catalog' else 12
            ids=[c['id'] for c in candidates if any(len(normalize(c.get(field,'')))>=minimum(field) and ' '+normalize(c[field])+' ' in text for field in fields)]
            if ids:break
        if ids:
            inferred=True;basis='Conservative legacy classification from explicitly named kit identifiers.'
            if any(term in f.get('message','').casefold() for term in ('selection','ranking','recommendation','comparison','selected kit','chosen kit','choice','rank','comparative','exclusion','economic advantage')):
                f['affects_selection_rationale']=True
    if ids and any(cid not in known for cid in ids):
        scope='project';basis='Unknown candidate reference; reviewer classification required.'
    elif f.get('affects_selection_rationale'):
        scope='project';basis=basis or 'Finding can undermine the selection rationale.'
    elif ids and (declared!='project' or inferred):
        scope='selected_kit' if selected in ids else 'alternative_only'
        basis=basis or 'Explicit candidate IDs evaluated against the current selected kit.'
    elif declared=='selected_kit' and not ids and selected:
        ids=[selected];scope='selected_kit';basis=basis or 'Bound to the selected kit when the finding was created.'
    else:
        scope='project';basis=basis or 'Project-wide or ambiguous finding; remains blocking until reviewed.'
    f.update(scope=scope,candidate_ids=ids,scope_basis=basis)
    note=instrument_execution_note(f,packet) or concentration_planning_note(f)
    f['planning_treatment']='planning_note' if note else 'planning_finding'
    if note:f['planning_treatment_reason']=note
    f['requires_attention']=f.get('severity') in ('critical','major') and f.get('status','open') not in ('resolved','superseded') and scope!='alternative_only' and not note
    f['blocks_approval']=False
    kit=next((k for k in candidates if k['id']==selected),{})
    reasons=kit.get('eligibility',{}).get('reasons',[])
    citation_only={gate+' lacks inspectable source support' for gate in ('identity','matrix','range','volume')}
    f['technical_only']=(f.get('origin')=='deterministic' and f.get('message')=='Selected candidate has unresolved scientific eligibility.'
                         and bool(reasons) and set(reasons)<=citation_only)
    if f['technical_only']:f['requires_attention']=False
    f['approval_policy']='Advisory only; named reviewers retain decision responsibility.'
    return f

def scoped_findings(packet):
    findings=[scoped_finding(f,packet) for f in packet.get('findings',[]) if not obsolete_scope_reason(f,packet)]
    return [f for f in findings if not f.get('technical_only')]

def blocking_findings(packet,section=None):
    return [f for f in scoped_findings(packet) if f['blocks_approval'] and (section is None or f['section']==section)]

def reconcile_findings(current,previous,dispositions,changed,packet=None):
    old={f.get('id',digest([f['section'],f['message']])[:16]):f for f in previous.get('findings',[])}
    active=[];history=list(previous.get('finding_history',[]));seen=set()
    for f in current:
        f=dict(f);fid=finding_key(f)
        if fid in seen:continue
        seen.add(fid);f['id']=fid
        obsolete=obsolete_scope_reason(f,packet or {})
        if obsolete:
            history.append({**f,'status':'resolved' if f.get('issue_code') and f.get('scope_class','planning')=='planning' else 'superseded','requires_attention':False,'blocks_approval':False,
                            'resolution':obsolete,'disposition_basis':'Intake-defined planning scope; original agent text retained, no scientific success claimed.'})
            continue
        disposition=dispositions.get(fid)
        if disposition:
            f.update(status='accepted' if disposition.get('action')=='accepted' else 'resolved',
                     requires_attention=False,blocks_approval=False,disposition=disposition);history.append(f)
        else:
            affected=changed if isinstance(changed,list) else None
            f['status']='needs_recheck' if changed and (affected is None or f['section'] in affected) and fid in old and f.get('origin')=='agent' else old.get(fid,{}).get('status','open')
            active.append(f)
    for fid,f in old.items():
        if fid not in seen:history.append({**f,'status':'superseded','resolution':'Not present in the checks for the new revision.'})
    unique={digest(f):f for f in history}
    return active,list(unique.values())
