"""Bounded deterministic extraction from retained procedure text; no model requests."""
import re
from .source_mapping import _url
from .store import digest

def _record(text,start,end,sid,value):
    left=max(0,start-60);right=min(len(text),max(end+90,left+200))
    pages=list(re.finditer(r'Page\s+(\d+)\s*:',text[:start+1],re.I))
    return {'value':value,'source_id':sid,'quote':text[left:min(right,left+390)],'locator':('Page '+pages[-1].group(1) if pages else 'Retained text')+f'; characters {left+1}–{min(right,left+390)}','method':'Local manual extraction; scientific interpretation unverified'}

def extract(kit,sources):
    proposals={}
    for sid,src in sources.items():
        if _url(src.get('url'))!=_url(kit.get('manual_url')) or src.get('content_hash')!=digest(src.get('text','')):continue
        text=src.get('text','')
        headings=list(re.finditer(r'(?im)^\s*(?:\d+\.?\s*)?(?:Detailed\s+)?ASSAY\s+PROCEDURE[^\n]*',text))
        detailed=[h for h in headings if 'detailed' in h.group().casefold()]
        eligible=[h for h in headings if h.start()>1000 and 'summary' not in h.group().casefold()]
        head=(detailed or eligible)
        if not head:continue
        start=head[0].start();stop=re.search(r'(?im)^\s*(?:DATA ANALYSIS|CALCULATION OF RESULTS|\d+\.?\s*CALCULATIONS)',text[start+head[0].end()-head[0].start():])
        end=start+(head[0].end()-head[0].start())+stop.start() if stop else min(len(text),start+7000)
        section=text[start:end]
        volumes=[]
        for m in re.finditer(r'\b(?:Add|Pipette)\s+(\d+(?:\.\d+)?)\s*(?:µ|μ|u|�)\s*l\b[^.;\n]{0,65}\bsamples?\b',section,re.I):
            volumes.append(_record(text,start+m.start(),start+m.end(),sid,float(m.group(1))))
        if volumes and len({p['value'] for p in volumes})==1:proposals['well_input_ul']=volumes[0]
        # Require a sample-oriented recommendation, not standard/buffer dilution.
        patterns=[r'(?:single step determination[^.]{0,30})?\bdilution of\s+1\s*[:/]\s*([\d,]+)\s+is appropriate[^.]{0,90}(?:serum|plasma|sample)',r'Dilutions? of about\s+(\d+(?:\.\d+)?)(k)?[ -]fold\s+are appropriate[^.]{0,100}(?:sera|serum|samples?)']
        for pattern in patterns:
            m=re.search(pattern,text,re.I)
            if m:
                value=float(m.group(1).replace(',',''))*(1000 if len(m.groups())>1 and m.group(2) else 1)
                proposals['dilution_factor']=_record(text,m.start(),m.end(),sid,value);break
        steps=[]
        pattern=r'\bincubat(?:e|ion)\b[^.;]{0,150}?\b(?:for|within)\s+(?:[a-z]+\s+){0,3}\(?(\d+)(?:\s*[-–]\s*(\d+))?(?:\s*±\s*\d+)?\)?\s*(minutes?|mins?|hours?|hrs?)\b'
        for m in re.finditer(pattern,section,re.I):
            scale=60 if m.group(3).lower().startswith(('hour','hr')) else 1
            low=int(m.group(1))*scale;high=int(m.group(2) or m.group(1))*scale
            record=_record(text,start+m.start(),start+m.end(),sid,low);record['minutes_low']=low;record['minutes_high']=high
            steps.append(record)
        if steps:
            low=sum(s['minutes_low'] for s in steps);high=sum(s['minutes_high'] for s in steps)
            total=str(low) if low==high else f'{low}–{high}'
            detail=' + '.join(str(s['minutes_low']) if s['minutes_low']==s['minutes_high'] else f"{s['minutes_low']}–{s['minutes_high']}" for s in steps)
            proposals['assay_duration']={'value':f'{total} min timed incubation/development ({detail} min); excludes untimed setup, preparation, washing and reading','steps':steps,'source_id':sid,'method':'Sum of explicit timed assay-procedure steps; nominal times where tolerances are given'}
        break
    return proposals

def vendor_dispatch(kit,sources):
    for sid,source in sources.items():
        if _url(source.get('url'))!=_url(kit.get('vendor_url')) or source.get('content_hash')!=digest(source.get('text','')):continue
        match=re.search(r'\bDispatch\s+Time\s*:\s*(?:About\s+)?\d+(?:\s*[-–]\s*\d+)?\s*(?:(?:working|business|calendar)\s+)?(?:days?|weeks?)\b',source.get('text',''),re.I)
        if match:return {'value':match.group(),'quote':match.group(),'source_id':sid,'checked_at':source.get('retrieved_at',''),'locator':f'Product-page dispatch statement; characters {match.start()+1}–{match.end()}'}
    return None
