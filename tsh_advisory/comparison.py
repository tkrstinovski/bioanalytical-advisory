"""Concise review presentation; full findings stay in the audit record."""
import re
from urllib.parse import quote
from .names import matches,instrument_match as canonical_instrument_match

def species_match(requested,supported):
    return matches(requested,supported,'species')

def instrument_match(instruments,kit):
    return canonical_instrument_match(instruments,kit)

def manual_reference(packet,kit):
    if kit.get('manual_url'):return kit['manual_url'],kit.get('manual_checked_at','')
    sources=packet.get('sources',{})
    for evidence in kit.get('evidence',{}).values():
        source=sources.get(evidence.get('source_id'),{})
        url=source.get('url','')
        if '.pdf' in url.casefold() or any(w in source.get('title','').casefold() for w in ('manual','instructions for use','protocol')):
            return url,source.get('retrieved_at','')
    return '', ''

def comparison_sources(packet,kit):
    urls=[]
    manual,_=manual_reference(packet,kit)
    for url in (manual,kit.get('vendor_url','')):
        if url.startswith(('https://','http://')):urls.append(url)
    ids={e.get('source_id') for e in kit.get('evidence',{}).values()}
    ids.update([kit.get('price_source'),kit.get('lead_time_source_id')])
    # Overall recommendation citations may describe OTHER kits. Keep these in
    # the audit register rather than presenting them as this kit's evidence.
    ids.update(entry.get('source_id') for entry in kit.get('cell_evidence',{}).values())
    for entry in kit.get('cell_evidence',{}).values():
        url=entry.get('reference_url','')
        if url.startswith(('https://','http://')):urls.append(url)
    for sid in sorted(x for x in ids if x):
        url=packet.get('sources',{}).get(sid,{}).get('url','')
        if url.startswith(('https://','http://')):urls.append(url)
    return list(dict.fromkeys(urls))

def recommendation_reasons(packet,kit):
    from .selection import selection_analysis
    return selection_analysis(packet,kit)['reasons']


def concise_concerns(kit,instruments):
    concerns=[r for r in kit.get('eligibility',{}).get('reasons',[]) if 'instrument' not in r.casefold()]
    if kit.get('species','').casefold()=='mouse' and any('species mismatch' in r for r in kit.get('eligibility',{}).get('reasons',[])):concerns.append('Mouse-only documentation does not support rat use')
    if kit.get('well_input_ul') is None:concerns.append('Sample input per well missing')
    if kit.get('dilution_factor') is None:concerns.append('Manual dilution needs confirmation')
    # Never paraphrase arbitrary old narratives into new scientific claims.
    compact=[]
    if any('source support' in c or 'gate not passed' in c for c in concerns):compact.append('Supporting evidence review incomplete')
    compact += [c for c in concerns if 'source support' not in c and 'gate not passed' not in c]
    return '; '.join(dict.fromkeys(compact)) or 'No open eligibility findings'

def normalized_curve(value):
    numbers=re.findall(r'\d[\d,]*(?:\.\d+)?',value or '')
    if len(numbers)<2:return 'Range or units not documented'
    factor=.001 if re.search(r'pg\s*/\s*ml',value,re.I) else 1 if re.search(r'ng\s*/\s*ml',value,re.I) else None
    if factor is None:return 'Units require review'
    low,high=[float(n.replace(',',''))*factor for n in numbers[:2]]
    return f'{low:g}–{high:g} ng/mL (manufacturer curve; not dilution-adjusted)'

def vendor_instrument_text(packet,kit):
    if kit.get('vendor_instruments'):return '; '.join(kit['vendor_instruments'])
    e=kit.get('evidence',{}).get('instrument',{});source=packet.get('sources',{}).get(e.get('source_id'),{})
    quote=e.get('quote','')
    if quote and quote in source.get('text','') and any(term in quote.casefold() for term in ('luminex','magpix','flexmap','intelliflex','reader','instrument','spectramax','bio-plex','bioplex')):return 'Recorded manual/vendor passage: '+quote
    return 'Not documented in saved kit evidence; scientist to confirm.'

def comparison_rows(packet,candidates,lead_time):
    """One comparison dataset for UI, HTML and PDF."""
    output={}
    for k in candidates:
        manual,checked=manual_reference(packet,k)
        link=lambda title,url:f'[{title}]({quote(url,safe=":/?=&%#@+;,~.-_")})' if url else 'Not provided'
        output[k['name']+' · '+k['catalog']]={
          'Manufacturer':k['manufacturer'],'Platform':k['platform'],'Instrument (kit manual/vendor)':vendor_instrument_text(packet,k),
          'Instrument availability (intake)':'; '.join(f'{platform}: {model}' for platform,model in packet.get('case',{}).get('instruments',{}).items() if str(model).strip()) or 'No instruments listed in intake',
          'Execution readiness':'Routine setup, calibration/qualification and scheduling checked before laboratory execution; not a planning approval requirement.',
          'Analyte':k['analyte'],'Species':k['species'],'Species strain (kit documentation)':k.get('species_strain') or 'Not specified',
          'Requested strain (intake)':packet.get('case',{}).get('species_strain') or 'Not specified — no strain restriction',
          'Matrix':k['matrix'],'Kit curve range':k.get('curve_range') or 'Reviewer input required',
          'Expected study concentrations':'Unknown at planning; not required for approval. Manufacturer range is listed separately.',
          'Common-unit curve range':normalized_curve(k.get('curve_range','')),'Assay input (µL/well)':k.get('well_input_ul') if k.get('well_input_ul') is not None else 'Not documented','Manual dilution factor':k.get('dilution_factor') if k.get('dilution_factor') is not None else 'Not documented',
          'Kit price (USD)':k.get('kit_price') if k.get('kit_price') is not None else 'Not available publicly',
          'Price basis':'Reviewer estimate' if k.get('price_source','').startswith('reviewer:') else 'Public source' if k.get('kit_price') is not None else 'Reviewer estimate required',
          'Wells per kit':k.get('wells_per_kit'),'Review concerns':concise_concerns(k,packet.get('case',{}).get('instruments',{})),
          'Vendor website':link('Vendor website',k.get('vendor_url','')),'Kit manual':link('Kit manual',manual)+(' · checked '+checked if checked else ''),
          'Assay duration (manual)':k.get('assay_duration') or 'Not documented yet','Required supporting equipment':'; '.join(k.get('required_equipment',[])) or 'Not documented yet',
          'Lead time':lead_time(packet,k),'Evidence sources':'\n'.join(link('Kit manual' if url==manual else 'Vendor website' if url==k.get('vendor_url') else 'Kit-specific source '+str(i+1),url) for i,url in enumerate(comparison_sources(packet,k))) or 'Not recorded'}
        if not str(packet.get('case',{}).get('species_strain') or '').strip():
            output[k['name']+' · '+k['catalog']].pop('Species strain (kit documentation)',None)
            output[k['name']+' · '+k['catalog']].pop('Requested strain (intake)',None)
    return output
