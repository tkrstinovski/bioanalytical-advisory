"""Bounded candidate research; full source snapshots remain in the audit store."""
import copy,re
from .schemas import Candidate

MAX_DEEP_KITS=4


def validate_research(result):
    candidates=result.get('candidates',[])
    if not candidates or len(candidates)>MAX_DEEP_KITS:raise ValueError('Deeply assess 1–4 kits only. Keep additional screened candidates as brief entries in screened_candidates; do not claim an exhaustive market search.')
    result=copy.deepcopy(result);result['candidates']=[Candidate.model_validate(c).model_dump() for c in candidates]
    if len({c['id'] for c in result['candidates']})!=len(candidates):raise ValueError('Candidate IDs must be distinct.')
    for c in result['candidates']:c['cell_evidence']={};c['reviewer_edits']={}
    screened=result.get('screened_candidates',[])
    if not isinstance(screened,list):raise ValueError('screened_candidates must be a list.')
    result['screened_candidates']=[{key:str(item.get(key,''))[:500] for key in ('name','platform','reason','manual_url')} for item in screened[:20] if isinstance(item,dict)]
    result['research_scope']={'deep_kit_limit':4,'deep_kits_assessed':len(candidates),'exhaustive':False,
        'method':'Lightweight candidate search; up to four deeply assessed kits. Additional screened candidates are not equally researched.'}
    return result


def compact_prompt(value):
    if isinstance(value,list):return [compact_prompt(v) for v in value]
    if not isinstance(value,dict):return value
    result={k:compact_prompt(v) for k,v in value.items()}
    if isinstance(value.get('text'),str) and len(value['text'])>8000:
        text=value['text'];parts=[text[:2200]];budget=5500
        for match in re.finditer(r'(?i)TSH|thyroid|sample volume|serum|standard curve|assay range|incubat|equipment|dilut|shipping|lead time',text):
            if budget<=0:break
            chunk=text[max(0,match.start()-100):match.start()+450]
            if any(chunk in p for p in parts):continue
            chunk=chunk[:budget];parts.append(chunk);budget-=len(chunk)
        result['text']='\n[EXCERPT]\n'.join(parts)[:8000]
        result['prompt_excerpt_notice']='Selected excerpts only; full retained snapshot is preserved in evidence. Do not infer facts absent from these excerpts.'
    return result


def validate_platform(result,research_candidates):
    result=copy.deepcopy(result);allowed={k['id'] for k in research_candidates}
    candidates=result.get('candidates',[])
    if not candidates or len(candidates)>4 or any(k.get('id') not in allowed for k in candidates):
        raise ValueError('Compare only the up-to-four deeply researched kit IDs; do not introduce unresearched candidates. Preserve other discoveries in screened_candidates.')
    result['candidates']=[Candidate.model_validate(c).model_dump() for c in candidates]
    if result.get('selected_kit') not in {c['id'] for c in candidates}:raise ValueError('Select one of the researched candidates.')
    return result
