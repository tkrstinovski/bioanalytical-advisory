"""Conservative local linkage of saved kit values to retained, kit-specific passages."""
import re
from urllib.parse import unquote
from .store import digest
from .names import species_parts

VERSION='kit-field-passages-v1'
FIELDS=('analyte','species','matrix','well_input_ul','dilution_factor','curve_range')

def _url(value):return unquote(str(value or '')).rstrip('/').casefold()

def _patterns(field,value):
    if value is None or value=='':return []
    if field=='analyte':
        if re.search(r'\bigg\b|immunoglobulin\s*g',str(value),re.I):return [r'\b(?:IgG|immunoglobulin\s+G)\b']
        if re.search(r'\btsh\b|thyroid stimulating hormone',str(value),re.I):return [r'\b(?:TSH|thyroid[ -]stimulating\s+hormone|thyrotropin)\b']
        return [r'\b'+re.escape(str(value))+r'\b']
    if field=='species':
        label=species_parts(value)[0].split(';')[0].strip()
        aliases={'monkey':r'\b(?:monkey|monkeys)\b','mouse':r'\b(?:mouse|mice|murine|Mus\s+musculus)\b','rat':r'\b(?:rat|rats|Rattus\s+norvegicus)\b','nhp':r'\b(?:monkey|non[ -]?human\s+primate|NHP)\b'}
        return [aliases.get(label.casefold(),r'\b'+re.escape(label)+r'\b')]
    if field=='matrix':
        parts=[p.strip() for p in re.split(r'[,;/]|\band\b',str(value),flags=re.I) if p.strip()]
        return [r'\b'+r'\s+'.join(re.escape(t) for t in p.split())+r'\b' for p in parts]
    if field=='well_input_ul':
        n=re.escape(f'{float(value):g}')
        volume=rf'\b{n}(?:\.0+)?\s*(?:µ|μ|u|�)\s*[lL]\b'
        return [rf'(?:\bsamples?\b[^.;]{{0,70}}{volume}|{volume}[^.;]{{0,70}}\bsamples?\b)']
    if field=='dilution_factor':
        n=re.escape(f'{float(value):g}')
        return [rf'\b1\s*[:/]\s*{n}\b']
    numbers=re.findall(r'\d+(?:\.\d+)?',str(value))
    units=re.search(r'(?:[munpµμ]?g|[munpµμ]?IU)\s*/\s*m[lL]',str(value),re.I)
    if len(numbers)!=2 or not units:return []
    return [r'\b'+re.escape(numbers[0])+r'\s*(?:-|–|—|�|to|~)\s*'+re.escape(numbers[1])+r'\s*'+re.escape(units.group()).replace(r'\ ',r'\s*')]

def _find(text,patterns):
    if not patterns:return None
    for match in re.finditer(patterns[0],text,re.I):
        start=max(0,match.start()-65);end=min(len(text),max(match.end()+100,start+200))
        if end-start>390:end=start+390
        quote=text[start:end]
        if all(re.search(pattern,quote,re.I) for pattern in patterns):
            page=list(re.finditer(r'Page\s+(\d+)\s*:',text[:match.start()+1],re.I))
            return quote,('Page '+page[-1].group(1) if page else 'Retained text')+f'; characters {start+1}–{end}'
    return None

def map_packet(packet):
    """Never changes a saved fact, reviewer entry, or original source snapshot."""
    linked=[]
    for kit in packet.get('candidates',[]):
        urls={_url(kit.get('manual_url')),_url(kit.get('vendor_url'))}-{''}
        associated=[(sid,source) for sid,source in packet.get('sources',{}).items() if _url(source.get('url')) in urls and source.get('content_hash')==digest(source.get('text','')) and not (source.get('synthetic') and packet.get('mode')!='fixture')]
        for field in FIELDS:
            if kit.get('cell_evidence',{}).get(field,{}).get('source_id'):continue
            existing=kit.get('auto_evidence',{}).get(field,{})
            if existing and existing.get('value_at_review')==kit.get(field):continue
            kit.setdefault('auto_evidence',{}).pop(field,None)
            patterns=_patterns(field,kit.get(field))
            for sid,source in associated:
                result=_find(source.get('text',''),patterns)
                if not result:continue
                quote,locator=result
                kit['auto_evidence'][field]={'source_id':sid,'quote':quote,'locator':locator,'value_at_review':kit[field],'mapping_version':VERSION,'method':'Local matching to retained kit-specific source; scientific interpretation unverified'}
                linked.append({'candidate_id':kit['id'],'field':field,'source_id':sid,'locator':locator})
                break
    packet['source_mapping']={'version':VERSION,'method':'Retained kit-specific text only; no model calls; no invented or overwritten facts','new_links':linked}
    return linked
