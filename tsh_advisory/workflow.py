import sqlite3, json, copy
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command
from .schemas import Intake,Candidate,Plan,CostAssumptions,Findings
from .calculations import study_volume, validation_volume, cost_estimate
from .agents import LiveProvider,Tools,work,fixture
from .policy import quality,scientific_complete,current_decisions,packet_hash
from .store import now,digest
from .design import experiment_design,enforce_design,pending_work

WORKER_ORDER=['researcher','platform','planner','cost','author','quality']

def normalize_tasks(result):
    tasks=result.get('tasks')
    if not isinstance(tasks,list) or not tasks or len(tasks)>100:
        raise ValueError('Orchestrator must return between 1 and 100 tasks.')
    groups={role:[] for role in WORKER_ORDER}
    for task in tasks:
        if not isinstance(task,dict):raise ValueError('Each task must be an object with role and objective.')
        role=str(task.get('role','')).strip().lower()
        if role not in groups:raise ValueError('Unsupported worker role: '+role)
        objective=task.get('objective')
        if not isinstance(objective,str) or not objective.strip():raise ValueError('A task objective is missing.')
        groups[role].append(objective.strip())
    missing=[role for role in WORKER_ORDER if not groups[role]]
    if missing:raise ValueError('Required worker roles missing: '+', '.join(missing))
    # All original objectives are retained; execution follows typed artifact dependencies.
    return [dict(role=role,objective='\n'.join(f'{i+1}. {text}' for i,text in enumerate(groups[role])),subtasks=groups[role]) for role in WORKER_ORDER]

class State(TypedDict,total=False):
    run_id:str
    case:dict
    mode:str
    settings:dict
    queue:list
    results:dict
    packet:dict
    feedback:list
    iteration:int
    status:str
    continuation:dict
    other_candidates:list
    review_configuration:dict
    planning_revision:int
    finding_dispositions:dict
    report_details:dict
    supporting_documents:list
    applied_intake:dict
    intake_application:dict

class Engine:
    def __init__(self,store):
        self.store=store
        self.connection=sqlite3.connect(store.root/'checkpoints.sqlite',check_same_thread=False)
        saver=SqliteSaver(self.connection)
        graph=StateGraph(State)
        for name,node in [('orchestrate',self.orchestrate),('worker',self.worker),('assemble',self.assemble),('scientific',self.scientific),('director',self.director)]: graph.add_node(name,node)
        graph.add_edge(START,'orchestrate')
        graph.add_edge('orchestrate','worker')
        graph.add_conditional_edges('worker',lambda s:'worker' if s['queue'] else 'assemble',{'worker':'worker','assemble':'assemble'})
        graph.add_conditional_edges('assemble',lambda s:'orchestrate' if s.get('status')=='peer_rework' else 'scientific',{'orchestrate':'orchestrate','scientific':'scientific'})
        graph.add_conditional_edges('scientific',lambda s:s['status'],{'rework':'orchestrate','targeted_rework':'worker','scientific_approved':'director','rejected':END})
        graph.add_conditional_edges('director',lambda s:s['status'],{'rework':'orchestrate','targeted_rework':'worker','authorized':END,'rejected':END})
        self.graph=graph.compile(checkpointer=saver)
    def close(self): self.connection.close()
    def persist(self,s,updates):
        state={**s,**updates}; self.store.save_run(s['run_id'],state); return updates
    def provider(self,s): return LiveProvider(self.store,s['run_id'],s['settings'].get('model',''),s['settings'].get('rates',{}),max_calls=s['settings'].get('model_call_limit',40))
    def orchestrate(self,s):
        rid=s['run_id']; self.store.ensure_active(rid)
        iteration=s.get('iteration',0)
        if iteration>2: raise ValueError('Revision limit reached; create a new run after human intervention.')
        case=Intake.model_validate(s['case'])
        if not all([case.analyte,case.species,case.matrix,case.intended_use]): raise ValueError('Analyte, species, matrix and purpose are required to start research.')
        if s['mode']=='live' and (not case.instruments or any(not v.strip() for v in case.instruments.values())):raise ValueError('Select available instrument platforms and enter an exact model for each.')
        if s['mode']=='fixture':
            tasks=[{'role':r,'objective':f'Synthetic fixture: exercise {r} handoff'} for r in ['researcher','platform','planner','cost','author','quality']]
            result={'goal':'Exercise the new harness with fictional data','tasks':tasks,'limitations':'Not a live agent run.'}
        else:
            context={'case':s['case'],'feedback':s.get('feedback',[]),
                'execution_policy':{'required_worker_roles':WORKER_ORDER,'stage_order':WORKER_ORDER,
                    'retrieval':'The downstream researcher has public search/read tools. The orchestrator itself does not.',
                    'confirmed_semantics':'Available volume applies to study samples only; validation matrix is separately calculated. One complete repeat means an additional full set of measurements. Human approval is handled by the harness, not a worker task. Intake confirmations must not be silently reopened.'}}
            contract={'goal':'string','tasks':[{'role':'one of researcher, platform, planner, cost, author, quality','objective':'specific worker objective'}],
                'requirements':'Include all six worker roles. Quality must inspect the assembled report. Related subtasks may be consolidated by the harness. Return action=finish with this object in result.'}
            for attempt in range(2):
                result=work(self.provider(s),'orchestrator',context,contract)
                try:
                    tasks=normalize_tasks(result)
                    break
                except ValueError as exc:
                    self.store.event(rid,'orchestrator_plan_rejected','orchestrator',{'attempt':attempt+1,'reason':str(exc),'plan':result})
                    if attempt==1:raise ValueError('Orchestrator could not produce a complete worker plan after correction: '+str(exc)) from None
                    context['plan_correction']={'rejected_plan':result,'error':str(exc),'required_roles':WORKER_ORDER}
            self.store.event(rid,'task_plan_normalized','orchestrator',{'original_task_count':len(result['tasks']),'worker_stage_count':len(tasks),'tasks':tasks,'policy':'Retain all objectives, consolidate by role, enforce dependencies and final quality review.'})
        self.store.event(rid,'goal_decomposition','orchestrator',result)
        for task in tasks: self.store.task(rid,task['role'],task['objective'],'ready',{'iteration':iteration,'dependencies':'previous accepted output'})
        results={} if iteration==0 else dict(s.get('results',{}))
        return self.persist(s,{'queue':tasks,'results':results,'status':'running'})
    def worker(self,s):
        rid=s['run_id']; self.store.ensure_active(rid)
        task=s['queue'][0]; role=task['role']; results=dict(s.get('results',{})); case=Intake.model_validate(s['case'])
        operation_key=digest([rid,s.get('iteration',0),role,task['objective']])
        with self.store.connect() as c: old=c.execute('SELECT data FROM operations WHERE key=?',(operation_key,)).fetchone()
        if old: output=json.loads(old[0])
        elif s['mode']=='fixture':
            if s.get('settings',{}).get('manual_demo'):
                from .kit_library import manual_demo
                f=manual_demo(case)
            else:f=fixture(case)
            output={'researcher':{'sources':f['sources'],'candidates':f['candidates']},'platform':{'candidates':f['candidates'],'selected_kit':f['candidates'][0]['id'],'rationale':'Synthetic test preference only'},
                'planner':f['plan'],'cost':f['cost_assumptions'],'author':{'summary':'Test planning packet; no laboratory validation or approval.','limitations':f['plan']['additional_work']},
                'quality':{'findings':[],'review':'Synthetic check; deterministic quality gates still run.'}}[role]
        else:
            context={'case':s['case'],'task':task,'results':results,'feedback':s.get('feedback',[])}
            context['research_scope']='First perform a lightweight search; deeply assess at most four credible kits. Return other discovered kits as brief screened_candidates entries (name, platform, reason, manual_url), not full candidates. Use concise source passages and targeted follow-up; do not reread whole manuals to repair a single fact. This is a bounded search, never an exhaustive market review.'
            context['structured_findings']='Assign issue_code to each finding: MISSING_MATRIX_PRICE, MISSING_KIT_PRICE, MISSING_SAMPLE_INPUT, STUDY_VOLUME, PLATE_CAPACITY, INTAKE_PARAMETER_OMITTED, UNSUPPORTED_CLAIM or REVIEWER_DIRECTION. Set scope_class=planning for current intake/calculation concerns; execution_detail or out_of_scope for optional future laboratory work. Split mixed findings. Known issue codes are rechecked against current saved values; unknown issues stay for human review. Do not resolve a concern based on prose alone.'
            context['selection_rubric']='Explain comparative trade-offs, not five generic advantages. Species/analyte/matrix are eligibility facts; compare sample consumption, pipettable preparation, kit-manual workflow/equipment, evidence strength, same-scope cost and lead time. Missing competitor facts do not establish superiority. No fabricated scores.'
            context['name_matching']='Use canonical species/analyte/matrix aliases and normalized manufacturer/platform names. Mus musculus = mouse; Rattus norvegicus = rat; thyroid stimulating hormone = TSH; Bio-Plex = BioPlex. Formatting differences are not incompatibilities. Do not equate different instrument models or infer performance from name similarity. Cite actual manual support.'
            context['species_field_format']='Candidate species must contain only the documented species name(s), e.g. Monkey. Do not append vendor calibration commentary to species, and do not relocate that commentary into reviewer_notes/evidence. Preserve original source snapshots; the comparison species cell is only the species label.'
            context['product_page_policy']='vendor_url must point to the specific kit/catalog product page when available, not the vendor homepage. Check that page for the matching kit size and public unit price before reporting public pricing unavailable. Retain the price passage, currency, package size, source ID and checked date. A blocked/failed page is a retrieval limitation, not proof that the price is not public. Do not use prices from related products.'
            context['optional_strain_and_reader_policy']='NHP, Monkey and non-human primate are equivalent broad naming labels. Cyno/cynomolgus/Macaca fascicularis are aliases; rhesus/Macaca mulatta are aliases. Do not conflate explicit cynomolgus and rhesus species. Store any kit strain restriction separately as species_strain. Intake species_strain is OPTIONAL: blank means no strain restriction and must never produce missing-strain, species-mismatch or strain-mismatch findings. Only flag a documented explicit strain conflict when intake strain is provided and kit strain differs; undocumented kit strain is not a mismatch. Microplate reader, microtitre plate reader and microtiter plate reader are SpectraMax family naming equivalents, not exact model specifications. Extract wavelength and detection_mode into candidate fields from manual/vendor when available. These two fields are informational for scientist review: neither absent values nor differing wavelength/detection mode produce mismatch findings, eligibility penalties or approval blockers. Preserve the documented values without claiming verified equipment capability.'
            context['planning_boundaries']='Intake instruments are the available instruments. List vendor/manual instrument requirements separately; scientist confirms the equipment arrangement at approval. Instrument compatibility, configuration and readiness are advisory, not automatic gates. Assay calibration standards and QCs remain part of the plan. Expected study concentrations are unknown by design and are NOT an approval requirement: use category expected_concentration_unknown for that planning note. Always report and cite the manufacturer curve range. Do not fail the range gate solely because study concentrations are unknown. A documented known range problem uses category range_coverage_mismatch and remains a planning finding. Split mixed findings into separate issues.'
            context['instrument_policy']='Report vendor_instruments only from the kit manual/vendor; never copy intake instruments into that field or infer brand/model support from a platform name. Intake instruments are a separate availability list. Do not require agents to match instruments, models or platforms; do not fail instrument gates or planning approval because of missing/mismatched instrument information. Instrument compatibility, essential configuration and readiness are advisory notes under the instrument finding categories. The named scientist confirms the arrangement at recommendation approval. Continue reporting documented requirements and concerns without asserting a match. This instrument policy supersedes any earlier instrument matching requirement.'
            context['finding_scope_rules']='For every finding specify scope project, selected_kit or alternative_only; include exact candidate_ids for kit-specific issues. An unrelated alternative-only gap does not block the selected kit. Set affects_selection_rationale=true when an incorrect comparison, invalid exclusion or missing alternative evidence undermines the recommendation itself; those remain project-wide advisory findings. Uncertain attribution stays project scope. Do not mark a gap resolved just because a different kit was selected.'
            context['intake_scope_contract']='Intake parameters, counts and selected conditions are the authoritative planning scope. Check completeness and internal consistency against that scope and current deterministic calculations. Do not add experiments, independent replication, pilot studies, actual sample histories, finalized acceptance criteria, laboratory SOPs or proof of validated performance as missing requirements. Do not treat the class submission date as a laboratory completion deadline. A specific documented kit-manual conflict with the requested plan remains an actionable advisory; cite it and separate it from optional future execution considerations. All findings are advisory; no scientific/director approval blockers.'
            context['financial_policy']='Overhead is calculated automatically as 15 percent of estimated labor cost. Gross profit and margin are excluded. Proposed price equals internal cost including contingency. Instrument charges use the selected kit platform: SpectraMax $10/plate, Bio-Plex $35/plate, MSD $35/plate, including initial and repeat plates; these are user-provided internal rates, not vendor prices.'
            context['class_cost_policy']='Use class_estimate_mode=true. Consumables use an editable $15/plate class-project benchmark, not a surveyed market average; no individual item price research. Shipping policy is per_kit_plus_matrix: $20 shipping per initial/repeat kit plus $200 total matrix shipping. These are user-provided planning defaults, not carrier quotes. Do not research FedEx or require route/weight/rate sources. For candidates extract attended_minutes_per_plate only from explicit manual/vendor hands-on timing and cite labor_timing_source with URL and page/location; otherwise leave null. Fallback attended labor is 3.5 hours per plate when documented hands-on timing is unavailable. Fallback attended labor is 3.5 hours per plate when documented hands-on timing is unavailable. Elapsed incubation is not attended labor. Setup/review allowances are labeled estimates.'
            context['validation_volume_allowances']='Use the intake preparation_leeway_ul pipetting reserve for every validation preparation, including each parallelism dilution and each repeat. No fixed 15 uL handling addition per lot/parameter: handling_ul_per_lot=0 in current plans. Parallelism retains enough volume for plating plus pipetting reserve after onward transfer. The final 200 uL per-lot aliquoting allowance is added once in the lot totals; do not duplicate it in parameters. Study-sample handling is a separate kit-specific calculation.'
            context['evidence_and_timing_scope']='Compare manufacturer/manual facts for this planning packet. Do not flag absence of demonstrated study-specific assay performance, cross-assay equivalence, validated concentration coverage, local instrument qualification or completed acceptance-criteria work. A background study or white paper is contextual evidence, not proof of those outcomes; state that as a source limitation without a major/critical finding unless a specific comparison claim misuses it. The intake deadline is the academic report submission target, never a laboratory-completion requirement. Do not compare a stability duration or vendor lead time to that date to demand deadline extension or scope reduction. Only evaluate a laboratory-completion conflict if the reviewer explicitly specifies a separate laboratory completion requirement; quote that requirement. Preserve kit lead times and chosen stability conditions as planning facts.'
            context['review_scope']='Use kit manuals and intake for a practical planning comparison. No ICH M10 or biomarker guidance reference is required. Do not create missing-guideline or acceptance-criteria blockers. Keep rationale brief and return only actionable concerns: documented requirement mismatches, missing assay input/dilution, capacity, timing or costing inputs. No public price means not available publicly, with reviewer pricing allowed. Preserve original evidence and unknown facts. Record vendor_url, manual_url, manual_checked_at and assay_duration from original manuals when available. All sample materials are lots.'
            if s.get('continuation'):
                context['reviewer_decisions']=s['continuation']
                context['rules']='Reuse retained evidence only; no new broad research. Confirmed intake and deterministic service calculations are authoritative. Work on the chosen finalists only. Selection for development is not scientific approval. Do not invent acceptance, pilot results, costs, dates or replacement arithmetic in narrative.'
                reduced={k:v for k,v in results.items() if k in ('researcher','platform','planner','cost')}
                reduced=copy.deepcopy(reduced)
                if role=='quality':reduced['author']=copy.deepcopy(results.get('author',{}))
                sources=reduced.get('researcher',{}).get('sources',{})
                for source in sources.values():source['text']=source.get('text','')[:12000]
                context['results']=reduced
                context['blocking_findings']=[{'section':f['section'],'severity':f['severity'],'message':f['message'][:700]} for f in s.get('packet',{}).get('findings',[])]
                try:
                    candidate=next(c for c in results['platform']['candidates'] if c['id']==s['continuation']['working_kit'])
                    candidate={k:v for k,v in candidate.items() if k in Candidate.model_fields}
                    kit=Candidate.model_validate(candidate)
                    plan=Plan.model_validate(results['planner'])
                    volumes=validation_volume(case,kit,plan)
                    context['deterministic_calculations']={'study':study_volume(case,kit),'validation':volumes,'cost':cost_estimate(case,kit,volumes,CostAssumptions.model_validate(results['cost']))}
                except (KeyError,ValueError,StopIteration,TypeError):context['deterministic_calculations']={'status':'Inputs unresolved; do not invent calculated values.'}
            if role=='planner':
                context['required_experiment_design']=experiment_design(case)
                context['precision_accuracy_service_rules']='Calculator allocates P/A plates with the configured blank, standard and QC layout from intake. Do not duplicate this experiment. P/A uses kit stock, not reference lot/animal matrix. Calibration and QCs are planned on every plate. Each P/A plate hosts at most one additional parameter; each parameter has dedicated repeat plates; never place initial runs on repeat plates. Use the configured 10–20 uL pipetting reserve per preparation, including each repeat; no fixed per-parameter handling addition. Set sharing_group=core_validation only where timing permits sharing P/A plates; long-term assessments cannot share them.'
            contracts={
                'researcher':{'candidates_schema':Candidate.model_json_schema(),'output':'{candidates:[up to 4 Candidate],screened_candidates:[{name,platform,reason,manual_url}]}; sources are retained by tools; search and read original sources for every critical claim'},
                'platform':{'candidate_schema':Candidate.model_json_schema(),'output':'{candidates:[Candidate],selected_kit:string,rationale:string,selection_reasons:[five distinct primary evidence-supported reasons for the selected kit]}; preserve source IDs; never invent reasons or superiority'},
                'planner':Plan.model_json_schema(),'cost':CostAssumptions.model_json_schema(),
                'author':{'summary':'string with evidence references','limitations':['string']},
                'quality':{'type':'object','properties':{'findings':{'type':'array','items':Findings.model_json_schema()},'review':{'type':'string'}},'required':['findings','review'],'additionalProperties':False}}
            tools=Tools(self.store,rid,case.scientific_reviewer) if role=='researcher' else None
            from .research_scope import validate_research,validate_platform
            validator=validate_research if role=='researcher' else (lambda result:validate_platform(result,results.get('researcher',{}).get('candidates',[]))) if role=='platform' else (lambda result: enforce_design(case,Plan.model_validate(result)).model_dump()) if role=='planner' else None
            output=work(self.provider(s),role,context,contracts[role],tools,validate_result=validator)
            if tools:
                prior=results.get('researcher',{}).get('sources',{})
                output['sources']={**prior,**tools.sources}
            if role=='planner': output=enforce_design(case,Plan.model_validate(output)).model_dump()
            if role=='cost': output=CostAssumptions.model_validate(output).model_dump()
            if role=='cost' and case.calculation_revision=='lot-planning-v3':
                output['class_estimate_mode']=True
                output['consumables_per_plate']=15
                output.update(shipping_policy='per_kit_plus_matrix',shipping_per_kit=20,matrix_shipment_usd=200)
                output.update(labor_hours_per_plate=3.5,estimate_rules_version=2)
            if role=='cost':output['reviewer_estimates']=copy.deepcopy(results.get('cost',{}).get('reviewer_estimates',{}))
            if role in ('researcher','platform'):
                previous={c['id']:c for c in s.get('packet',{}).get('candidates',[])}
                for c in output.get('candidates',[]):
                    if not c.get('reviewer_edits',{}).get('handling_ul'):c['handling_ul']=20
                    c['retained_manual']=copy.deepcopy(previous.get(c['id'],{}).get('retained_manual',{})) if previous.get(c['id'],{}).get('manual_url')==c.get('manual_url') else {}
                    for field_name in ('reviewer_edits','cell_evidence'):c[field_name]=copy.deepcopy(previous.get(c['id'],{}).get(field_name,{}))
            if role in ('platform','researcher'): output['candidates']=[Candidate.model_validate(c).model_dump() for c in output.get('candidates',[])]
        if s.get('continuation') and role=='platform':
            ids=s['continuation']['finalist_ids'];working=s['continuation']['working_kit']
            if not output.get('recommended_kit'):output['recommended_kit']=output.get('selected_kit')
            supplied={c['id']:c for c in output.get('candidates',[]) if c['id'] in ids}
            prior={c['id']:c for c in results.get('platform',{}).get('candidates',[]) if c['id'] in ids}
            output['candidates']=[supplied.get(cid,prior[cid]) for cid in ids]
            output['selected_kit']=working
        if role=='platform' and 'recommended_kit' not in output:output['recommended_kit']=output.get('selected_kit')
        if not old:
            with self.store.connect() as c: c.execute('INSERT INTO operations VALUES(?,?)',(operation_key,json.dumps(output)))
            self.store.event(rid,'agent_output',role,{'task':task,'iteration':s.get('iteration',0),'output':output})
        self.store.task(rid,role,task['objective'],'completed',{'iteration':s.get('iteration',0),'output_hash':digest(output)})
        results[role]=output
        return self.persist(s,{'queue':s['queue'][1:],'results':results})
    def assemble(self,s):
        r=s['results']; case=Intake.model_validate(s['case']); platform=r.get('platform',{})
        candidates=copy.deepcopy(platform.get('candidates',r.get('researcher',{}).get('candidates',[])))
        from . import manuals
        for candidate in candidates:
            if candidate.get('retained_manual') or not candidate.get('manual_url'):continue
            retained=manuals.cached(self.store,candidate['manual_url'])
            if retained:
                src=manuals.source(self.store,retained,case.scientific_reviewer)
                if src['id'] in r.get('researcher',{}).get('sources',{}):candidate['retained_manual']=retained
        if s.get('continuation'):
            known={c['id'] for c in candidates}
            candidates.extend(copy.deepcopy(c) for c in s.get('other_candidates',[]) if c['id'] not in known)
        from .manual_facts import extract,vendor_dispatch
        for candidate in candidates:
            proposals=extract(candidate,r.get('researcher',{}).get('sources',{}))
            candidate['manual_extraction']=proposals
            dispatch=vendor_dispatch(candidate,r.get('researcher',{}).get('sources',{}))
            if dispatch:
                candidate['manual_extraction']['lead_time']=dispatch
                candidate.update(lead_time=dispatch['value'],lead_time_quote=dispatch['quote'],lead_time_source_id=dispatch['source_id'],lead_time_checked_at=dispatch['checked_at'])
            for field in ('well_input_ul','dilution_factor','curve_range','assay_duration'):
                if field not in proposals or candidate.get('reviewer_edits',{}).get(field):continue
                if field=='assay_duration' or candidate.get(field) in (None,''):
                    candidate[field]=proposals[field]['value']
            for field in ('well_input_ul','dilution_factor','curve_range'):
                proposal=proposals.get(field)
                if proposal and candidate.get(field)==proposal['value'] and not candidate.get('cell_evidence',{}).get(field,{}).get('source_id'):
                    candidate.setdefault('auto_evidence',{})[field]={**proposal,'value_at_review':candidate[field],'mapping_version':'manual-procedure-v1'}
        selected=platform.get('selected_kit'); kit=next((Candidate.model_validate(c) for c in candidates if c['id']==selected),None)
        if kit and case.parallel_start_from_kit and kit.dilution_factor is None:
            case.parallel_start_from_kit=False;s['case']=case.model_dump()
        if kit and case.parallel_start_from_kit and kit.dilution_factor is not None:
            case.parallel_start_dilution=kit.dilution_factor;s['case']=case.model_dump()
            if r.get('planner'):r['planner']=enforce_design(case,Plan.model_validate(r['planner'])).model_dump()

        if r.get('cost'):r['cost'].update(overhead_rate=.15,gross_margin=0.0)
        packet=dict(mode=s['mode'],case=s['case'],sources=r.get('researcher',{}).get('sources',{}),candidates=candidates,selected_kit=selected,
            finalist_ids=s.get('continuation',{}).get('finalist_ids',[]),reviewer_decisions=s.get('continuation',{}),calculation_selection=s.get('review_configuration',{}),recommended_kit=platform.get('recommended_kit',selected),plan=r.get('planner'),summary=r.get('author',{}),ranking_rationale=platform.get('rationale',''),cost_assumptions=r.get('cost'))
        if kit and packet['plan'] and packet['cost_assumptions']:
            packet['study']=study_volume(case,kit)
            packet['volume']=validation_volume(case,kit,Plan.model_validate(packet['plan']))
            if case.calculation_revision=='lot-planning-v3':
                from .planning import scope_costs
                a,scope=scope_costs(case,kit,packet['volume'],CostAssumptions.model_validate(packet['cost_assumptions']))
                if s.get('review_configuration',{}).get('confirm_cost_scope'):
                    a.overrides_confirmed_for=scope;s['review_configuration']['confirm_cost_scope']=False
                r['cost']=a.model_dump();packet['cost_assumptions']=a.model_dump();packet['cost_scope']=scope
            packet['cost']=cost_estimate(case,kit,packet['volume'],CostAssumptions.model_validate(packet['cost_assumptions']))
            if case.calculation_revision=='lot-planning-v3' and a.overrides and a.overrides_confirmed_for!=scope:
                packet['cost']['incomplete']=True;packet['cost']['unresolved'].append('Retained cost overrides require confirmation for the changed scope.')
        packet['research_scope']=copy.deepcopy(r.get('researcher',{}).get('research_scope',{'deep_kit_limit':None,'exhaustive':False,'method':'Historical research scope retained; no new four-kit search performed.'}))
        from .selection import refresh_recommendation
        from .source_mapping import map_packet
        links=map_packet(packet)
        if links:self.store.event(s['run_id'],'kit_field_sources_linked','source mapping',{'method':'Retained sources only; interpretation unverified','links':links,'model_calls':0})
        platform.setdefault('original_agent_recommended_kit',platform.get('recommended_kit',selected))
        packet['original_agent_recommended_kit']=platform['original_agent_recommended_kit']
        refreshed=refresh_recommendation(packet,packet.get('recommended_kit'))
        packet['recommendation_refresh']=refreshed
        packet['recommended_kit']=refreshed['recommended_kit']
        platform['recommended_kit']=refreshed['recommended_kit']
        if digest(refreshed)!=digest(s.get('packet',{}).get('recommendation_refresh',{})):
            self.store.event(s['run_id'],'recommendation_refreshed','comparison rules',{'previous':s.get('packet',{}).get('recommended_kit'),'current':refreshed['recommended_kit'],'status':refreshed['status'],'contenders':refreshed['contenders'],'method':refreshed['method'],'metrics':refreshed['metrics'],'scientist_selected_kit':selected,'model_calls':0})
        packet['screened_candidates']=copy.deepcopy(r.get('researcher',{}).get('screened_candidates',[]))
        packet['report_details']=copy.deepcopy(s.get('report_details',{}))
        packet['supporting_documents']=copy.deepcopy(s.get('supporting_documents',[]))
        packet['intake_application']=copy.deepcopy(s.get('intake_application',{}))
        packet['recommendation_reasons']=platform.get('selection_reasons',[])
        packet['planning_revision']=s.get('planning_revision',1)
        packet['findings']=[dict(f,origin='deterministic') for f in quality(case,packet)]
        from .schemas import Findings
        packet['findings'] += [dict(Findings.model_validate(f).model_dump(),origin='agent') for f in r.get('quality',{}).get('findings',[])]
        from .findings import reconcile_findings,scoped_finding,blocking_findings
        packet['findings']=[scoped_finding(f,packet) for f in packet['findings']]
        if r.get('quality'):
            # Bind kit references once, so a later kit switch cannot retarget an old finding.
            r['quality']['findings']=[{key:value for key,value in f.items() if key in Findings.model_fields} for f in packet['findings'] if f.get('origin')=='agent']
        config=s.get('review_configuration',{})
        packet['findings'],packet['finding_history']=reconcile_findings(packet['findings'],s.get('packet',{}),s.get('finding_dispositions',{}),config.get('affected_sections',bool(config)),packet)
        from .names import name_checks,VERSION
        packet['name_matching']={'version':VERSION,'candidates':{k['id']:name_checks(s['case'],k) for k in candidates}}
        self.store.event(s['run_id'],'quality_gate','quality',{'findings':packet['findings'],'packet_hash':packet_hash(packet)})
        # Automatic peer repair is a genuine conditional graph branch; bounded to two iterations.
        updates={'packet':packet,'status':'awaiting_scientific'}
        peer=[scoped_finding(f,packet) for f in packet.get('findings',[]) if f.get('origin')=='agent' and scoped_finding(f,packet).get('requires_attention')]
        needs_human=(not selected or packet.get('cost',{}).get('incomplete',True) or any(
            any(term in f.get('message','').casefold() for term in ['pilot','manager must','scientific reviewer','human approval','laboratory data','experimental data','measured losses'])
            for f in peer))
        if peer and needs_human:
            self.store.event(s['run_id'],'quality_escalated_to_human','quality',{'reason':'Missing selection/cost evidence or human/laboratory prerequisites cannot be resolved by repeating the full agent workflow.','findings':peer})
        if peer and not needs_human and not s.get('continuation') and not s.get('review_configuration') and s.get('iteration',0)<2:
            updates.update(status='peer_rework',iteration=s.get('iteration',0)+1,feedback=s.get('feedback',[])+[{'from':'quality','findings':peer}])
        return self.persist(s,updates)
    def scientific(self,s):
        feedback=interrupt({'stage':'scientific','packet_hash':packet_hash(s['packet']),'sections':['recommendation','validation','volume','cost','evidence']})
        if feedback.get('action')=='return':
            if s.get('continuation'):return self.targeted_return(s,feedback)
            return self.persist(s,{'status':'rework','feedback':s.get('feedback',[])+[feedback],'iteration':s.get('iteration',0)+1})
        if feedback.get('action')=='reject': return self.persist(s,{'status':'rejected'})
        if not scientific_complete(self.store,s['run_id']): raise ValueError('All current scientific sections must be explicitly approved.')
        return self.persist(s,{'status':'scientific_approved'})
    def director(self,s):
        self.persist(s,{'status':'awaiting_director'})
        feedback=interrupt({'stage':'director','packet_hash':packet_hash(s['packet'])})
        if feedback.get('action')=='return':
            if s.get('continuation'):return self.targeted_return(s,feedback)
            return self.persist(s,{'status':'rework','feedback':s.get('feedback',[])+[feedback],'iteration':s.get('iteration',0)+1})
        if feedback.get('action')=='reject': return self.persist(s,{'status':'rejected'})
        d=current_decisions(self.store,s['run_id'],packet_hash(s['packet'])).get(('director','project'),{})
        if d.get('action')!='approve' or not scientific_complete(self.store,s['run_id']): raise ValueError('Recorded director and scientific decisions required.')
        return self.persist(s,{'status':'authorized'})
    def targeted_return(self,s,feedback):
        section=feedback.get('section','recommendation')
        roles={'cost':['cost','author','quality'],'validation':['planner','cost','author','quality'],
            'volume':['planner','cost','author','quality']}.get(section,['platform','planner','cost','author','quality'])
        return self.persist(s,{'status':'targeted_rework','iteration':s.get('iteration',0)+1,
            'feedback':s.get('feedback',[])+[feedback],
            'queue':[{'role':r,'objective':'Address returned section '+section+' using the saved finalists and evidence.'} for r in roles]})
    def start(self,cid,mode,settings):
        if mode!='fixture':
            from .sandbox import forbid_live
            forbid_live(self.store)
        rid=self.store.create_run(cid,mode)
        state=State(run_id=rid,case=self.store.case(cid)['data'],mode=mode,settings=settings,iteration=0,results={},feedback=[])
        state['applied_intake']=copy.deepcopy(state['case'])
        if settings.get('planning_version')=='lot-planning-v3':
            state['case']['calculation_revision']='lot-planning-v3';state['case']['parallel_start_from_kit']=True
        self.store.save_run(rid,state)
        self.run_graph(rid,state)
        return rid
    def run_graph(self,rid,value):
        try: return self.graph.invoke(value,{'configurable':{'thread_id':rid},'recursion_limit':100})
        except Exception as exc:
            self.store.event(rid,'run_error','system',{'type':type(exc).__name__,'message':str(exc)[:500]})
            self.store.stop(rid,'system')
            raise
    def resume(self,rid,feedback):
        self.store.ensure_active(rid)
        return self.run_graph(rid,Command(resume=feedback))
    def repair_operation_collision(self,rid):
        """Recover an accepted handoff from its retained response, without a model call."""
        run=self.store.run(rid)
        events=self.store.events(rid)
        errors=[e for e in events if e['data']['event']=='run_error']
        if not run['stopped'] or not errors or errors[-1]['data']['data'].get('message')!='UNIQUE constraint failed: operations.key':
            raise ValueError('This recovery requires the saved operation-key collision.')
        if not self.store.verify(rid):raise ValueError('Audit chain invalid; intervention required.')
        if self.store.case(run['case_id'])['version']!=run['case_version']:raise ValueError('Intake changed. Retained response must be reviewed against the saved intake first.')
        checkpoint=self.graph.get_state({'configurable':{'thread_id':rid}})
        state=checkpoint.values
        queue=state.get('queue',[])
        if not queue or queue[0]['role'] not in ('researcher','platform'):raise ValueError('Checkpoint does not match the affected research/platform step.')
        task=queue[0];role=task['role']
        responses=[e for e in events if e['seq']<errors[-1]['seq'] and e['data']['event']=='model_response' and e['data']['actor']==role]
        if not responses:raise ValueError('No retained model response is available; no retry was sent.')
        response=responses[-1];payload=response['data']['data']
        if payload.get('response_status','completed')!='completed':raise ValueError('Retained response was incomplete; no retry was sent.')
        handoff=json.loads(payload['text'])
        if handoff.get('action')!='finish' or not isinstance(handoff.get('result'),dict):raise ValueError('Retained response is not a completed handoff.')
        output=copy.deepcopy(handoff['result'])
        output['candidates']=[Candidate.model_validate(c).model_dump() for c in output.get('candidates',[])]
        if not output['candidates']:raise ValueError('Retained handoff has no validated candidates.')
        if role=='platform':
            if output.get('selected_kit') not in {c['id'] for c in output['candidates']}:raise ValueError('Retained kit selection does not match its candidates.')
            output.setdefault('recommended_kit',output['selected_kit'])
        else:
            sources=dict(state.get('results',{}).get('researcher',{}).get('sources',{}))
            for event in events:
                if event['data']['event']=='source_read':
                    source=event['data']['data'];sources[source['id']]=source
            output['sources']=sources
        operation_key=digest([rid,state.get('iteration',0),role,task['objective']])
        with self.store.connect() as c:
            c.execute('INSERT OR IGNORE INTO operations VALUES(?,?)',(operation_key,json.dumps(output)))
            self.store._event(c,rid,'operation_collision_repaired','system',{'role':role,'operation_key':operation_key,'retained_response_seq':response['seq'],'model_calls':0,'legacy_records':'preserved'})
        return operation_key

    def resume_operation_collision(self,rid):
        self.repair_operation_collision(rid)
        with self.store.connect() as c:
            c.execute('UPDATE runs SET stopped=0 WHERE id=?',(rid,))
            self.store._event(c,rid,'operation_collision_resumed','local project owner',{'policy':'Reuse recovered handoff; subsequent unfinished agents retain existing call/spend limits.'})
        return self.run_graph(rid,None)

    def retry_research_step(self,rid):
        run=self.store.run(rid)
        errors=[e['data']['data'] for e in self.store.events(rid) if e['data']['event']=='run_error']
        if not run['stopped'] or not errors or errors[-1].get('message')!='Agent reached its six-step tool limit; human intervention required.':
            raise ValueError('This recovery is only for the earlier six-step research-limit failure.')
        if not self.store.verify(rid):raise ValueError('Audit chain invalid; intervention required.')
        if self.store.case(run['case_id'])['version']!=run['case_version']:raise ValueError('Intake changed. Start a new run to use the new inputs.')
        with self.store.connect() as c:
            c.execute('UPDATE runs SET stopped=0 WHERE id=?',(rid,))
            self.store._event(c,rid,'human_research_recovery','local project owner',{'reason':'Earlier tool-loop boundary stopped before final handoff. Resume the failed checkpoint using retained sources; original usage and limits remain.'})
        return self.run_graph(rid,None)
    def retry_planner_step(self,rid):
        run=self.store.run(rid)
        errors=[e['data']['data'] for e in self.store.events(rid) if e['data']['event']=='run_error']
        if not run['stopped'] or not errors or not errors[-1].get('message','').startswith('Planner omitted requested parameters:'):
            raise ValueError('This recovery requires a saved planner omission failure.')
        if not self.store.verify(rid):raise ValueError('Audit chain invalid; intervention required.')
        if self.store.case(run['case_id'])['version']!=run['case_version']:raise ValueError('Intake changed. Start a new run to use the new inputs.')
        checkpoint=self.graph.get_state({'configurable':{'thread_id':rid}})
        queue=checkpoint.values.get('queue',[])
        if not queue or queue[0].get('role')!='planner':raise ValueError('Saved checkpoint is not awaiting the planner.')
        with self.store.connect() as c:
            c.execute('UPDATE runs SET stopped=0 WHERE id=?',(rid,))
            self.store._event(c,rid,'human_planner_recovery','local project owner',{'reason':'Resume failed planner with bounded design correction; retain completed tasks, evidence, usage and original spending/call limits.'})
        return self.run_graph(rid,None)
    def recover_completed_draft(self,rid):
        """Finish a budget-stopped revision using the last complete reviewed packet, without API calls."""
        run=self.store.run(rid);s=run['data']
        errors=[e['data']['data'] for e in self.store.events(rid) if e['data']['event']=='run_error']
        if not run['stopped'] or not errors or not errors[-1].get('message','').endswith('-call limit reached.'):
            raise ValueError('This recovery is only for a call-limited revision with a complete saved draft.')
        if not s.get('packet') or not all(role in s.get('results',{}) for role in WORKER_ORDER):
            raise ValueError('No complete reviewed draft is available. Partial output cannot be released.')
        if not self.store.verify(rid):raise ValueError('Audit chain invalid; intervention required.')
        if self.store.case(run['case_id'])['version']!=run['case_version']:raise ValueError('Intake changed; the earlier draft cannot be approved as current.')
        s['status']='awaiting_scientific'
        s['queue']=[]
        tasks=self.store.tasks(rid)
        with self.store.connect() as c:
            c.execute('UPDATE runs SET stopped=0,data=? WHERE id=?',(json.dumps(s),rid))
            for task in tasks:
                if task['status'] in ('ready','running'):
                    c.execute('UPDATE tasks SET status=? WHERE id=?',('cancelled',task['id']))
            self.store._event(c,rid,'human_budget_recovery','local project owner',{'action':'Route the last completed quality-reviewed packet to scientific review; cancel unfinished revision tasks.',
                'packet_hash':packet_hash(s['packet']),'additional_api_calls':0,'limits':'Existing call and spending limits are unchanged.','remaining_findings':len(s['packet'].get('findings',[]))})
        self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='assemble')
        return self.run_graph(rid,None)

    def continue_with_finalists(self,rid,finalist_ids,working_kit,actor,decisions):
        run=self.store.run(rid);s=run['data'];case=Intake.model_validate(s['case'])
        if s.get('status') not in ('awaiting_scientific','awaiting_director') or run['stopped']:
            raise ValueError('Recover the saved draft to a review stage before continuing.')
        if not actor.strip() or actor.strip().casefold()!=case.scientific_reviewer.strip().casefold():raise ValueError('Use the named scientific reviewer identity.')
        if not decisions.strip():raise ValueError('Record the reviewer direction or unresolved decisions.')
        if not 1<=len(set(finalist_ids))<=2 or working_kit not in finalist_ids:raise ValueError('Choose one or two finalists and a working kit from them.')
        if not self.store.verify(rid):raise ValueError('Audit chain invalid; intervention required.')
        if self.store.case(run['case_id'])['version']!=run['case_version']:raise ValueError('Intake changed; start a new run to incorporate it.')
        usage=self.store.usage(rid)
        if len(usage)>=80:raise ValueError('The overall 80-call continuation ceiling is reached; no further calls can be authorized on this run.')
        spent=sum(u.get('cost') if u.get('cost') is not None else u.get('reserved',0) for u in usage)
        if spent>=10:raise ValueError('The original $10 budget is exhausted. Continuation cannot bypass it.')
        registry={c['id']:{k:v for k,v in c.items() if k in Candidate.model_fields} for c in s['packet']['candidates']}
        if any(cid not in registry for cid in finalist_ids):raise ValueError('Finalists must come from the saved candidate registry.')
        selection=dict(finalist_ids=list(dict.fromkeys(finalist_ids)),working_kit=working_kit,reviewer=actor,decisions=decisions,
            meaning='Development/planning selection only; not kit suitability approval or project authorization.',prior_packet_hash=packet_hash(s['packet']))
        s['continuation']=selection;s['other_candidates']=[c for cid,c in registry.items() if cid not in finalist_ids]
        sources=Tools(self.store,rid,actor).sources
        s['results']['researcher']={'sources':sources,'candidates':[registry[cid] for cid in finalist_ids]}
        s['results']['platform']['candidates']=[registry[cid] for cid in finalist_ids]
        s['results']['platform']['selected_kit']=working_kit
        s['settings']['model_call_limit']=min(80,len(usage)+16)
        s['iteration']=s.get('iteration',0)+1
        s['feedback']=[{'from':actor,'action':'targeted revision','decisions':decisions,'finalist_ids':finalist_ids}]
        s['queue']=[{'role':role,'objective':'Targeted finalist revision using saved evidence and reviewer decisions: '+role} for role in ['platform','planner','cost','author','quality']]
        s['status']='running'
        for task in s['queue']:self.store.task(rid,task['role'],task['objective'],'ready',{'iteration':s['iteration']})
        self.store.event(rid,'reviewer_continuation',actor,{**selection,'prior_calls':len(usage),'additional_call_allowance':min(16,80-len(usage)),'original_budget_usd':10,'spent_or_reserved_usd':spent,'remaining_budget_usd':10-spent})
        self.store.save_run(rid,s)
        self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='orchestrate')
        return self.run_graph(rid,None)
    def select(self,rid,kit_id):
        """Evaluate a reviewed alternative and invalidate every old approval by packet hash."""
        self.store.ensure_active(rid)
        s=self.store.run(rid)['data']
        if s.get('status') not in ('awaiting_scientific','awaiting_director'): raise ValueError('Kit selection requires a review stage.')
        if kit_id not in [c['id'] for c in s['packet']['candidates']]: raise ValueError('Unknown kit')
        s['results']['platform'].setdefault('recommended_kit',s['packet'].get('recommended_kit',s['packet'].get('selected_kit')))
        s['results']['platform']['selected_kit']=kit_id
        updates=self.assemble(s); s.update(updates)
        self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='assemble')
        self.store.event(rid,'kit_selection_recalculated','scientific_reviewer',{'kit':kit_id,'packet_hash':packet_hash(s['packet'])})
        # Enter a new scientific interrupt after update_state moved execution past assemble.
        self.run_graph(rid,None)

    def refresh_review_flags(self,rid):
        """Re-evaluate saved planning checks without research or model calls."""
        self.store.ensure_active(rid);old=self.store.run(rid)['data'];s=copy.deepcopy(old)
        if s.get('status') not in ('awaiting_scientific','awaiting_director','authorized'):
            raise ValueError('Wait for a completed planning packet before refreshing flags.')
        calls=len(self.store.usage(rid));before=packet_hash(s['packet'])
        s['planning_revision']=self.store.archive_revision(rid,old,'review flag refresh')
        s['review_configuration']={'actor':'review flag refresh','affected_sections':[]}
        s.update(self.assemble(s))
        self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='assemble')
        self.store.event(rid,'review_flags_refreshed','system',{'previous_packet_hash':before,
            'packet_hash':packet_hash(s['packet']),'additional_model_calls':len(self.store.usage(rid))-calls,
            'basis':'Current deterministic checks and scope rules. Agent claims without a deterministic resolution remain for scientist review.'})
        return self.run_graph(rid,None)

    def acknowledge_findings(self,rid,actor,entries):
        """Version explicit scientist corrections/accepted assumptions, never fabricate evidence."""
        from .findings import scoped_findings,reconcile_findings
        self.store.ensure_active(rid);old=self.store.run(rid)['data'];s=copy.deepcopy(old)
        if actor.strip().casefold()!=s['case']['scientific_reviewer'].strip().casefold():raise ValueError('Enter the named scientific reviewer.')
        if s.get('status') not in ('awaiting_scientific','awaiting_director','authorized'):raise ValueError('Wait for a review stage.')
        current={f['id']:f for f in scoped_findings(s['packet'])}
        if not entries:raise ValueError('Check at least one flag to record a review.')
        actual=quality(Intake.model_validate(s['case']),copy.deepcopy(s['packet']))
        for fid,entry in entries.items():
            if fid not in current:raise ValueError('Flag changed; refresh before recording the review.')
            if entry.get('action') not in ('corrected','accepted') or not entry.get('reason','').strip():raise ValueError('Choose corrected or accepted and provide a reason for every checked flag.')
            f=current[fid]
            if entry['action']=='corrected' and f.get('origin')=='deterministic' and any(x['section']==f['section'] and x['message']==f['message'] for x in actual):
                raise ValueError('This check still applies. Correct the input and refresh, or choose Accepted for planning.')
        s['planning_revision']=self.store.archive_revision(rid,old,actor)
        for fid,entry in entries.items():
            s.setdefault('finding_dispositions',{})[fid]={'actor':actor,'action':entry['action'],'reason':entry['reason'].strip(),
                'evidence':entry.get('evidence','').strip(),'timestamp':now(),
                'basis':'Scientist-reported correction' if entry['action']=='corrected' else 'Accepted planning assumption; not a passed check or verified evidence'}
        p=s['packet'];p['planning_revision']=s['planning_revision']
        p['findings'],p['finding_history']=reconcile_findings(p['findings'],p,s['finding_dispositions'],False,p)
        s['status']='awaiting_scientific'
        self.store.save_run(rid,s);self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='assemble')
        self.store.event(rid,'scientist_flag_review',actor,{'reviews':entries,'packet_hash':packet_hash(p)})
        return self.run_graph(rid,None)

    def refresh_finding_scope(self,rid):
        """Archive obsolete scope findings without changing calculations or using a model."""
        from .findings import reconcile_findings,scoped_finding,SCOPE_POLICY
        self.store.ensure_active(rid)
        old=self.store.run(rid)['data'];s=copy.deepcopy(old)
        if s.get('status') not in ('awaiting_scientific','awaiting_director','authorized'):
            raise ValueError('Scope refresh requires a completed planning packet.')
        p=s['packet'];before=packet_hash(p)
        current,history=reconcile_findings(p.get('findings',[]),p,s.get('finding_dispositions',{}),False,p)
        if len(current)==len(p.get('findings',[])):return {'archived':0}
        count=len(p['findings'])-len(current)
        s['planning_revision']=self.store.archive_revision(rid,old,'intake planning scope correction')
        p['planning_revision']=s['planning_revision']
        p['findings']=[scoped_finding(f,p) for f in current];p['finding_history']=history
        s['status']='awaiting_scientific'
        self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='assemble')
        self.store.save_run(rid,s)
        self.store.event(rid,'finding_scope_corrected','system',{'policy':SCOPE_POLICY,'archived':count,
            'previous_packet_hash':before,'packet_hash':packet_hash(p),'additional_model_calls':0,
            'basis':'User-directed intake-defined planning scope. Calculations, source records and original agent messages preserved.'})
        self.run_graph(rid,None)
        return {'archived':count}

    def reassess_saved_run(self,rid):
        """System-only deterministic reassessment. No model calls, new sources or human decisions."""
        self.store.ensure_active(rid);old=self.store.run(rid)['data'];s=copy.deepcopy(old)
        if s.get('status') not in ('awaiting_scientific','awaiting_director','authorized'):raise ValueError('Reassessment requires a completed planning packet at a review stage.')
        p=s.get('packet',{})
        if not p or not p.get('plan') or not p.get('cost_assumptions'):raise ValueError('No complete saved planning inputs are available for reassessment.')
        before_calls=len(self.store.usage(rid));before_hash=packet_hash(p)
        case=Intake.model_validate(s['case']);case.calculation_revision='lot-planning-v3';case.long_term_material_type='lots'
        plan=enforce_design(case,Plan.model_validate(p['plan']))
        for experiment in plan.experiments:
            experiment.material_type='lots';experiment.handling_ul_per_lot=0
            if experiment.parameter!='Parallelism':experiment.dilution_factors=[case.parallel_start_dilution]*len(experiment.conditions)
        candidates=[{key:value for key,value in kit.items() if key in Candidate.model_fields} for kit in p.get('candidates',[])]
        if p.get('selected_kit') not in [kit['id'] for kit in candidates]:raise ValueError('The saved selected kit cannot be identified.')
        for kit in candidates:Candidate.model_validate(kit)
        CostAssumptions.model_validate(p['cost_assumptions'])
        s['planning_revision']=self.store.archive_revision(rid,old,'system rules reassessment')
        s['case']=case.model_dump();s['results']['planner']=plan.model_dump();s['results']['cost']=copy.deepcopy(p['cost_assumptions'])
        s['results']['platform']['candidates']=candidates;s['results']['platform']['selected_kit']=p['selected_kit']
        s['results']['platform'].setdefault('recommended_kit',p.get('recommended_kit'))
        s['finding_dispositions']={}
        s['review_configuration']={'actor':'system rules reassessment','affected_sections':['recommendation','validation','volume','cost','evidence'],'calculation_revision':'lot-planning-v3','confirm_cost_scope':False}
        s.update(self.assemble(s));self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='assemble')
        from .findings import SCOPE_POLICY,blocking_findings
        self.store.event(rid,'saved_run_reassessed','system rules reassessment',{'previous_packet_hash':before_hash,'packet_hash':packet_hash(s['packet']),'planning_revision':s['planning_revision'],
            'scope_policy':SCOPE_POLICY,'additional_model_calls':len(self.store.usage(rid))-before_calls,'new_sources_retrieved':0,'approvals_created':0,
            'remaining_blockers':[{'id':f.get('id'),'section':f['section'],'message':f['message']} for f in blocking_findings(s['packet'])],
            'basis':'Original saved intake, selected kit, retained evidence and planned scope. Updated deterministic rules/calculators; old agent findings retained for recheck.'})
        return self.run_graph(rid,None)

    def retain_kit_manual(self,rid,actor,candidate_id,url,raw=None,version='',refresh=False):
        from . import manuals
        s=self.store.run(rid)['data']
        if actor.strip().casefold()!=s['case']['scientific_reviewer'].strip().casefold():raise ValueError('Enter the named scientific reviewer.')
        if s.get('status') not in ('awaiting_scientific','awaiting_director','authorized'):raise ValueError('Wait for a review-stage packet before changing its retained manual.')
        kit=next(c for c in s['packet']['candidates'] if c['id']==candidate_id)
        record=manuals.retain(self.store,raw,url,version=version,catalog=kit['catalog'],method='upload') if raw is not None else manuals.fetch(self.store,url,refresh=refresh,version=version,catalog=kit['catalog'])
        previous=kit.get('retained_manual',{})
        if previous.get('sha256')==record['sha256'] and previous.get('version')==record['version'] and previous.get('requested_url')==url:
            self.store.event(rid,'manual_update_checked',actor,{'candidate_id':candidate_id,'changed':False,'record':record})
            return False
        self.configure_review(rid,actor,manual_update={'candidate_id':candidate_id,'record':record,'source':manuals.source(self.store,record,actor)})
        self.store.event(rid,'manual_version_selected',actor,{'candidate_id':candidate_id,'previous':previous,'current':record,'facts_reextracted':False})
        return True

    def apply_estimate_defaults(self,rid):
        s=self.store.run(rid)['data'];a=s.get('packet',{}).get('cost_assumptions',{})
        if a.get('estimate_rules_version',0)>=2:return False
        updates={'shipping_policy':'per_kit_plus_matrix','shipping_per_kit':20,'matrix_shipment_usd':200,'class_estimate_mode':True,'estimate_rules_version':2,'confirm_scope':True}
        if a.get('reviewer_estimates',{}).get('labor_hours_per_plate',{}).get('origin')!='cost_table':updates['labor_hours_per_plate']=3.5
        self.configure_review(rid,s['case']['scientific_reviewer'],cost_settings=updates,estimate_origin='system_default')
        self.store.event(rid,'estimate_defaults_applied','system',{'rules_version':2,'shipping_per_kit':20,'matrix_shipping':200,'fallback_hours_per_plate':3.5,'prior_revision_preserved':True})
        return True

    def add_supporting_document(self,rid,actor,raw,filename,metadata):
        from .supporting_documents import retain
        self.store.ensure_active(rid);s=self.store.run(rid)['data']
        if s.get('status') not in ('awaiting_scientific','awaiting_director','authorized'):raise ValueError('Wait for a review-stage packet before adding evidence.')
        if actor.strip().casefold()!=s['case']['scientific_reviewer'].strip().casefold():raise ValueError('Enter the named scientific reviewer.')
        if metadata.get('candidate_id') and metadata['candidate_id'] not in [k['id'] for k in s['packet']['candidates']]:raise ValueError('Choose a kit from this run.')
        record,source=retain(self.store,raw,filename,metadata,actor)
        from .document_extraction import extract_suggestions
        record['extraction']=extract_suggestions(source['text'],s['packet']['candidates'])
        if any(r['id']==record['id'] for r in s.get('supporting_documents',[])):return False
        self.configure_review(rid,actor,supporting_update={'record':record,'source':source})
        self.store.event(rid,'supporting_document_uploaded',actor,record)
        return True

    def review_supporting_metadata(self,rid,actor,document_id,document_date='',expires_on='',candidate_id=''):
        from datetime import date
        s=self.store.run(rid)['data'];record=next((r for r in s.get('supporting_documents',[]) if r['id']==document_id),None)
        if not record:raise ValueError('Supporting document not found.')
        for value in (document_date,expires_on):
            if value:date.fromisoformat(value)
        if document_date and expires_on and expires_on<document_date:raise ValueError('Expiration cannot precede the document date.')
        if candidate_id and candidate_id not in [k['id'] for k in s['packet']['candidates']]:raise ValueError('Choose a kit in this run.')
        if record.get('uses') and candidate_id!=record['candidate_id']:raise ValueError('This document already has recorded uses. Keep its kit association or upload a separately associated copy.')
        record=copy.deepcopy(record);record.update(document_date=document_date,expires_on=expires_on,candidate_id=candidate_id,metadata_reviewed_by=actor,metadata_reviewed_at=now())
        self.configure_review(rid,actor,supporting_update={'record':record})
        self.store.event(rid,'supporting_document_metadata_reviewed',actor,{'document_id':document_id,'document_date':document_date,'expires_on':expires_on,'candidate_id':candidate_id})

    def adopt_supporting_value(self,rid,actor,document_id,candidate_id,field,value,quote,locator,confirmed=False):
        import math
        from .supporting_documents import load
        if not confirmed:raise ValueError('Confirm that you are recording a scientist-reviewed value and have considered the document date and validity.')
        s=self.store.run(rid)['data'];record=next((r for r in s.get('supporting_documents',[]) if r['id']==document_id),None)
        if not record:raise ValueError('Supporting document not found in this run.')
        if record['candidate_id'] and record['candidate_id']!=candidate_id:raise ValueError('This document is linked to a different kit.')
        load(self.store,record)
        if field not in ('kit_price','reviewer_lead_time'):raise ValueError('Choose kit price or lead time.')
        if field=='kit_price':
            if value is None:raise ValueError('Enter the reviewed USD price per kit.')
            value=float(value)
            if not math.isfinite(value) or value<=0:raise ValueError('Enter a positive USD price per kit; do not substitute a different currency or total order amount.')
        else:
            value=str(value).strip()
            if not value:raise ValueError('Enter the documented lead time.')
        quote=quote.strip();locator=locator.strip()
        if locator and not quote:raise ValueError('Enter a passage for this location, or leave both optional citation fields blank.')
        if quote and not locator:raise ValueError('Enter a location for the optional supporting passage.')
        basis='Source passage verified' if quote else 'Reviewer estimate; document attached without a verified passage'
        record=copy.deepcopy(record);record['uses'].append({'candidate_id':candidate_id,'field':field,'value':value,'quote':quote,'locator':locator,'basis':basis,'reviewed_by':actor,'reviewed_at':now()})
        entry={'source_id':record['source_id'] if quote else None,'quote':quote,'locator':locator,'notes':basis+'; document '+record['filename']+'; date and validity considered.','reference_url':'upload://supporting-documents/'+record['id'],'supporting_document_id':record['id']}
        self.configure_review(rid,actor,candidate_updates={candidate_id:{field:value}},supporting_update={'record':record},evidence_update={'kit_id':candidate_id,'field':field,'entry':entry})
        self.store.event(rid,'supporting_value_adopted',actor,{'document_id':document_id,**record['uses'][-1]})

    def apply_updated_intake(self,rid,actor,scope_confirmed=False,scope_reason='',expected_version=None):
        from .intake_updates import preview
        self.store.ensure_active(rid);update=preview(self.store,rid)
        if expected_version is not None and update['current_version']!=expected_version:raise ValueError('Intake changed again. Refresh and review the latest changes before applying them.')
        if not update['version_changed']:return False
        if update['review_fields'] and (not scope_confirmed or not scope_reason.strip()):raise ValueError('Review the retained evidence for changed scientific/equipment inputs, confirm reuse and record a reason; or start a new research run.')
        case=Intake.model_validate(update['current_intake'])
        if not case.scientific_reviewer.strip() or not case.director.strip():raise ValueError('Complete the named scientific reviewer and director in intake before applying it to this run.')
        update.update(actor=actor,scope_confirmed=scope_confirmed,scope_reason=scope_reason.strip(),applied_at=now())
        before=len(self.store.usage(rid))
        self.configure_review(rid,actor,intake_update=update)
        self.store.bind_intake_version(rid,update['current_version'],actor,{'from_version':update['saved_version'],'to_version':update['current_version'],'changed_fields':list(update['changes']),'scope_review_fields':update['review_fields'],'scope_confirmed':scope_confirmed,'scope_reason':scope_reason,'new_model_calls':len(self.store.usage(rid))-before,'intake':update['current_intake']})
        return True

    def configure_review(self,rid,actor,kit_id=None,kit_price=None,matrix_price=None,start=None,factor=None,metadata=None,study_settings=None,cost_settings=None,experiment_settings=None,candidate_updates=None,report_details=None,evidence_update=None,use_kit_minimum=None,manual_update=None,estimate_origin='review_input',supporting_update=None,intake_update=None,public_source_update=None):
        """Version a scientist's planning changes without new model calls or altering saved intake."""
        self.store.ensure_active(rid)
        s=self.store.run(rid)['data'];case=Intake.model_validate(s['case'])
        if s.get('status') not in ('awaiting_scientific','awaiting_director','authorized'):raise ValueError('Wait for this run to reach scientific review before changing its calculations.')
        if not actor.strip() or actor.strip().casefold()!=case.scientific_reviewer.strip().casefold():raise ValueError('Enter the named scientific reviewer.')
        previous=packet_hash(s['packet']);s=copy.deepcopy(s)
        old_case=case.model_copy(deep=True)
        if intake_update:
            # Only changed saved-intake fields replace run inputs. Keep unchanged workspace overrides.
            values=case.model_dump()
            for field,change in intake_update['changes'].items():values[field]=copy.deepcopy(change['current'])
            case=Intake.model_validate(values)
            s['applied_intake']=copy.deepcopy(intake_update['current_intake'])
            s['intake_application']={key:copy.deepcopy(intake_update[key]) for key in ('actor','saved_version','current_version','review_fields','scope_confirmed','scope_reason','applied_at')}
            s['intake_application']['changed_fields']=list(intake_update['changes'])
            s['intake_application']['new_model_calls']=0
        if report_details is not None:
            s['report_details']={k:str(v).strip() for k,v in report_details.items() if k in ('client_name','project_reference')}
        if supporting_update:
            record=supporting_update['record']
            documents=copy.deepcopy(s.get('supporting_documents',[]))
            s['supporting_documents']=[r for r in documents if r['id']!=record['id']]+[record]
            if supporting_update.get('source'):
                src=supporting_update['source']
                s['results'].setdefault('researcher',{}).setdefault('sources',{})[src['id']]=src
                self.store.event(rid,'source_read',actor,src)

        if public_source_update:
            src=public_source_update['source'];quote=public_source_update['quote']
            if src.get('content_hash')!=digest(src.get('text','')) or quote not in src.get('text','') or not src.get('url','').startswith('https://'):
                raise ValueError('Public price requires a retained HTTPS source and exact price passage.')
            target=public_source_update['candidate_id']
            if target not in (candidate_updates or {}) or 'kit_price' not in candidate_updates[target]:raise ValueError('Public source must accompany its candidate price update.')
            s['results'].setdefault('researcher',{}).setdefault('sources',{})[src['id']]=src
            self.store.event(rid,'source_read','public vendor page',src)

        target_id=kit_id or s['packet'].get('selected_kit')
        chosen=next((c for c in s['packet']['candidates'] if c['id']==target_id),{})
        minimum=(candidate_updates or {}).get(target_id,{}).get('dilution_factor',(metadata or {}).get('dilution_factor',chosen.get('dilution_factor')))
        if use_kit_minimum is not None:case.parallel_start_from_kit=bool(use_kit_minimum)
        elif start is not None:case.parallel_start_from_kit=False
        elif kit_id is not None and kit_id!=s['packet'].get('selected_kit'):case.parallel_start_from_kit=minimum is not None
        if case.parallel_start_from_kit and minimum is not None and (start is not None or minimum!=case.parallel_start_dilution):start=minimum
        if case.parallel_start_from_kit and minimum is None:case.parallel_start_from_kit=False
        if start is not None:case.parallel_start_dilution=start
        if factor is not None:case.parallel_serial_factor=factor
        if study_settings is not None:
            case.study_dilution=study_settings.get('dilution');case.study_dilution_override_reason=study_settings.get('reason','')
            if case.study_dilution is not None and not case.study_dilution_override_reason.strip():raise ValueError('Explain the study dilution override.')
        case.calculation_revision='lot-planning-v3';case.long_term_material_type='lots'
        case=Intake.model_validate(case.model_dump());s['case']=case.model_dump()
        if intake_update:
            from .intake_updates import reconcile_plan
            plan=reconcile_plan(old_case,case,Plan.model_validate(s['results']['planner']))
        else:plan=enforce_design(case,Plan.model_validate(s['results']['planner']))
        for experiment in plan.experiments:
            experiment.material_type='lots';experiment.handling_ul_per_lot=0
            if experiment.parameter!='Parallelism':experiment.dilution_factors=[case.parallel_start_dilution]*len(experiment.conditions)
            if experiment_settings and experiment.parameter in experiment_settings:
                values=experiment_settings[experiment.parameter]
                experiment.independent_runs=values['independent_runs'];experiment.separate_conditions=values['separate_conditions']
        plan=Plan.model_validate(plan.model_dump())
        s['results']['planner']=plan.model_dump()
        selected=kit_id or s['packet'].get('selected_kit')
        candidates=[{k:v for k,v in c.items() if k in Candidate.model_fields} for c in s['packet']['candidates']]
        if selected not in [c['id'] for c in candidates]:raise ValueError('Select a kit to calculate its volumes.')
        if candidate_updates:
            allowed={'kit_price','vendor_url','manual_url','manual_checked_at','assay_duration','curve_range','required_equipment','reviewer_lead_time','reviewer_notes','well_input_ul','dilution_factor','vendor_instruments','handling_ul','analyte','species','species_strain','wavelength','detection_mode','matrix'}
            for candidate in candidates:
                updates=candidate_updates.get(candidate['id'],{})
                for key,value in updates.items():
                    if key not in allowed or value==candidate.get(key):continue
                    history=candidate.setdefault('reviewer_edits',{})
                    prior_edit=history.get(key,{})
                    history[key]={'original':copy.deepcopy(prior_edit.get('original',candidate.get(key))),
                                  'previous':copy.deepcopy(candidate.get(key)),'value':copy.deepcopy(value),
                                  'actor':actor,'timestamp':now()}
                    candidate[key]=value
                    if key=='manual_url':candidate['retained_manual']={}
                if 'kit_price' in updates:candidate['price_source']='reviewer:'+actor
                if public_source_update and candidate['id']==public_source_update['candidate_id']:
                    candidate['price_source']=public_source_update['source']['id']
                    candidate.setdefault('auto_evidence',{})['kit_price']={'source_id':candidate['price_source'],'quote':public_source_update['quote'],'locator':public_source_update['locator'],'value_at_review':candidate['kit_price'],'method':'Observed public product price; not a vendor quote or guaranteed price'}
                Candidate.model_validate(candidate)
        kit=next(c for c in candidates if c['id']==selected)
        if manual_update:
            target=next(c for c in candidates if c['id']==manual_update['candidate_id'])
            target['retained_manual']=manual_update['record']
            target['manual_url']=manual_update['record']['requested_url']
            target['manual_checked_at']=manual_update['record']['retrieved_at']
            src=manual_update['source']
            s['results'].setdefault('researcher',{}).setdefault('sources',{})[src['id']]=src
            self.store.event(rid,'source_read',actor,src)
        if evidence_update:
            from .evidence_details import verified_cell_record,FIELD_GATES
            target=next((c for c in candidates if c['id']==evidence_update.get('kit_id',selected)),None)
            if not target:raise ValueError('Evidence kit not found.')
            field=evidence_update['field'];entry=copy.deepcopy(evidence_update['entry'])
            evidence_packet=copy.deepcopy(s['packet'])
            if entry.get('source_url'):
                source=Tools(self.store,rid,actor).read(entry['source_url'])
                s['results'].setdefault('researcher',{}).setdefault('sources',{})[source['id']]=source
                evidence_packet.setdefault('sources',{})[source['id']]=source
                entry['source_id']=source['id']
            record=verified_cell_record(evidence_packet,target,field,entry,actor,now())
            target.setdefault('cell_evidence',{})[field]=record
            gate=FIELD_GATES.get(field)
            if record.get('source_id') and gate and (gate!='identity' or entry.get('supports_identity')):
                target.setdefault('evidence',{})[gate]={key:record[key] for key in ('source_id','locator','quote','claim')}
        if kit_price is not None:
            if kit_price<=0:raise ValueError('Kit estimate must be positive.')
            kit.update(kit_price=kit_price,price_source='reviewer:'+actor)
        if metadata:
            if metadata.get('manual_url') is not None and metadata['manual_url']!=kit.get('manual_url'):kit['retained_manual']={}
            kit.update({k:v for k,v in metadata.items() if k in ('vendor_url','manual_url','manual_checked_at','assay_duration','curve_range','required_equipment','reviewer_lead_time','reviewer_notes','well_input_ul','dilution_factor','required_model','vendor_instruments','handling_ul') and v is not None})
        Candidate.model_validate(kit)
        s['results']['platform']['candidates']=candidates
        s['results']['platform']['selected_kit']=selected
        s['results']['platform'].setdefault('recommended_kit',s['packet'].get('recommended_kit'))
        if matrix_price is not None:
            if matrix_price<0:raise ValueError('Matrix estimate cannot be negative.')
            if matrix_price!=s['results']['cost'].get('pooled_material'):
                s['results']['cost'].setdefault('reviewer_estimates',{})['pooled_material']={'actor':actor,'timestamp':now(),'value':matrix_price,'origin':estimate_origin}
            s['results']['cost']['pooled_material']=matrix_price
        if cost_settings:
            recorded=copy.deepcopy(s['results']['cost'].get('reviewer_estimates',{}))
            for key,value in cost_settings.items():
                if key in CostAssumptions.model_fields and key not in ('reviewer_estimates','overrides','overrides_confirmed_for') and value!=s['results']['cost'].get(key):
                    recorded[key]={'actor':actor,'timestamp':now(),'value':value,'origin':estimate_origin}
            s['results']['cost']['reviewer_estimates']=recorded
            a=CostAssumptions.model_validate({**s['results']['cost'],**{k:v for k,v in cost_settings.items() if k in CostAssumptions.model_fields}})
            if a.class_estimate_mode:
                for key in ('shipping','consumables','validation_hours'):a.overrides.pop(key,None)
            s['results']['cost']=a.model_dump()
        if kit_price is not None and estimate_origin=='cost_table':
            s['results']['cost'].setdefault('reviewer_estimates',{})['kit_price']={'actor':actor,'timestamp':now(),'value':kit_price,'origin':'cost_table'}
        s['planning_revision']=self.store.archive_revision(rid,self.store.run(rid)['data'],actor)
        old_case=s['packet'].get('case',{})
        affected=set()
        if old_case.get('calculation_revision')!='lot-planning-v3' or selected!=s['packet'].get('selected_kit') or start is not None or factor is not None or study_settings is not None or experiment_settings or candidate_updates:
            affected.update(['recommendation','validation','volume','cost','evidence'])
        if kit_price is not None or matrix_price is not None or cost_settings:affected.add('cost')
        changed_metadata={k for k,v in (metadata or {}).items() if v is not None and v!=next(c for c in s['packet']['candidates'] if c['id']==selected).get(k)}
        if evidence_update:affected.update(['recommendation','evidence'])
        if intake_update:affected.update(['recommendation','validation','volume','cost','evidence'])
        if supporting_update:affected.update(['recommendation','evidence'])
        if manual_update:affected.update(['recommendation','validation','volume','cost','evidence'])
        if changed_metadata:affected.update(['recommendation','evidence'])
        if changed_metadata & {'well_input_ul','dilution_factor','handling_ul'}:affected.update(['validation','volume','cost'])
        if 'assay_duration' in changed_metadata:affected.add('cost')
        known={f.get('id'):f for f in s['packet'].get('findings',[])+s['packet'].get('finding_history',[])}
        s['finding_dispositions']={fid:d for fid,d in s.get('finding_dispositions',{}).items() if known.get(fid,{}).get('section') not in affected}
        s['review_configuration']={'actor':actor,'calculation_revision':'lot-planning-v3','selected_kit':selected,'affected_sections':sorted(affected),'confirm_cost_scope':bool(cost_settings and cost_settings.get('confirm_scope'))}
        s.update(self.assemble(s))
        self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='assemble')
        self.store.event(rid,'review_configuration_updated',actor,{'previous_packet_hash':previous,'packet_hash':packet_hash(s['packet']),
            'kit':selected,'kit_price':kit_price,'matrix_price':matrix_price,'start':case.parallel_start_dilution,'start_from_kit':case.parallel_start_from_kit,'factor':case.parallel_serial_factor,'metadata':metadata or {},'candidate_updates':candidate_updates or {},'report_details':report_details or {},'evidence_update':evidence_update or {},
            'handling_ul_per_lot':0,'approval':'Planning selection only; prior approvals remain in history and require review of the changed packet.'})
        return self.run_graph(rid,None)

    def resolve_finding(self,rid,actor,finding_id,reason,evidence):
        self.store.ensure_active(rid);s=copy.deepcopy(self.store.run(rid)['data'])
        case=Intake.model_validate(s['case'])
        if actor.strip().casefold()!=case.scientific_reviewer.strip().casefold() or not reason.strip() or not evidence.strip():raise ValueError('Named reviewer, resolution reason and evidence reference are required.')
        if s.get('status') not in ('awaiting_scientific','awaiting_director'):raise ValueError('Open a planning revision before resolving findings.')
        finding=next((f for f in s['packet']['findings'] if f.get('id')==finding_id),None)
        if not finding:raise ValueError('Current finding not found.')
        deterministic=quality(case,copy.deepcopy(s['packet']))
        if any(f['section']==finding['section'] and f['message']==finding['message'] for f in deterministic):raise ValueError('This calculation/evidence check still fails. Correct its inputs first; a comment cannot clear it.')
        s['planning_revision']=self.store.archive_revision(rid,s,actor)
        s.setdefault('finding_dispositions',{})[finding_id]={'actor':actor,'reason':reason,'evidence':evidence}
        s.update(self.assemble(s));self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='assemble')
        self.store.event(rid,'finding_resolved_by_reviewer',actor,{'id':finding_id,'reason':reason,'evidence':evidence,'packet_hash':packet_hash(s['packet'])})
        return self.run_graph(rid,None)

    def classify_finding(self,rid,actor,finding_id,scope,candidate_ids,affects_selection_rationale,reason,evidence,category=None,instrument_model='',required_configuration=''):
        """Named reviewer classification; selected/project evidence failures cannot be hidden."""
        from .findings import scoped_finding,finding_key
        self.store.ensure_active(rid);s=copy.deepcopy(self.store.run(rid)['data']);p=s['packet']
        if actor.strip().casefold()!=s['case']['scientific_reviewer'].strip().casefold() or not reason.strip() or not evidence.strip():raise ValueError('Named reviewer, classification reason and evidence reference are required.')
        if s.get('status') not in ('awaiting_scientific','awaiting_director','authorized'):raise ValueError('Wait for a review stage before classifying findings.')
        finding=next((f for f in p.get('findings',[]) if f.get('id')==finding_id),None)
        if not finding or finding.get('origin')!='agent':raise ValueError('Only agent findings can be manually classified; deterministic checks retain their enforced scope.')
        known={k['id'] for k in p.get('candidates',[])}
        if scope not in ('project','selected_kit','alternative_only') or any(cid not in known for cid in candidate_ids):raise ValueError('Invalid scope or kit reference.')
        if scope!='project' and not candidate_ids:raise ValueError('Choose the kit(s) this finding concerns.')
        if scope=='alternative_only' and p.get('selected_kit') in candidate_ids:raise ValueError('An issue about the selected kit cannot be alternative-only.')
        if scope=='selected_kit' and p.get('selected_kit') not in candidate_ids:raise ValueError('Selected-kit scope must include the selected kit.')
        if scope=='alternative_only' and affects_selection_rationale:raise ValueError('A concern affecting the selection rationale must remain project-wide.')
        if category=='essential_configuration' and not required_configuration.strip():raise ValueError('Identify the specific essential configuration that is missing or unconfirmed.')
        matching=[];target=scoped_finding(finding,p)
        for raw in s['results'].get('quality',{}).get('findings',[]):
            classified=scoped_finding(raw,p)
            if finding_key(classified)==finding_id or (classified['section']==target['section'] and classified['message']==target['message'] and set(classified['candidate_ids'])==set(target['candidate_ids'])):matching.append(raw)
        if len(matching)!=1:raise ValueError('Finding is missing or ambiguous in the current agent record; refresh and review its kit references first.')
        s['planning_revision']=self.store.archive_revision(rid,s,actor)
        matching[0].update(scope=scope,candidate_ids=list(dict.fromkeys(candidate_ids)),affects_selection_rationale=bool(affects_selection_rationale),scope_basis=f'Reviewer {actor}: {reason}. Evidence: {evidence}')
        if category is not None:
            matching[0].update(category=category,instrument_model=instrument_model,required_configuration=required_configuration,evidence_reference=evidence)
            Findings.model_validate(matching[0])
        s.setdefault('finding_dispositions',{}).pop(finding_id,None)
        s['review_configuration']={**s.get('review_configuration',{}),'actor':actor,'affected_sections':[finding['section']]}
        s.update(self.assemble(s));self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='assemble')
        self.store.event(rid,'finding_scope_reviewed',actor,{'previous_id':finding_id,'scope':scope,'candidate_ids':candidate_ids,'affects_selection_rationale':affects_selection_rationale,'reason':reason,'evidence':evidence,'packet_hash':packet_hash(s['packet'])})
        return self.run_graph(rid,None)

    def recalculate(self,rid):
        """Refresh saved calculations without model calls; preserve prior approvals as stale history."""
        self.store.ensure_active(rid)
        run=self.store.run(rid);s=run['data']
        if self.store.case(run['case_id'])['version']!=run['case_version']:
            raise ValueError('Intake changed since this run. Use Apply updated intake and recalculate to include those changes without new model calls.')
        old=s.get('packet',{})
        candidates=[{k:v for k,v in c.items() if k in Candidate.model_fields} for c in old.get('candidates',[])]
        s['results']['platform']['candidates']=candidates
        s['results']['platform']['selected_kit']=old.get('selected_kit')
        plan=Plan.model_validate(s['results']['planner'])
        plan.additional_work=pending_work(plan.model_dump())
        for e in plan.experiments:
            if e.parameter!='Long-term stability' and e.sharing_group=='review_required':e.sharing_group='core_validation'
            if e.controls_per_run is not None and e.control_layout_basis.startswith('Unresolved'):
                e.control_layout_basis='Retained prior planning count; user confirmed 24 control wells for the TSH case.'
        s['results']['planner']=plan.model_dump()
        s.update(self.assemble(s))
        self.graph.update_state({'configurable':{'thread_id':rid}},s,as_node='assemble')
        self.store.event(rid,'calculations_refreshed','requester',{'previous_packet_hash':packet_hash(old),'new_packet_hash':packet_hash(s['packet']),'reason':'Whole-microliter matrix withdrawals and current serial preparation table; prior decisions retained as history.'})
        self.run_graph(rid,None)
