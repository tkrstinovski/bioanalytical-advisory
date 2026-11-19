"""Local, conservative document suggestions. Never applies values or executes document instructions."""
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

VERSION='document-rules-v1'

def extract_suggestions(text,kits):
    suggestions=[]
    def location(offset):
        pages=list(re.finditer(r'\bPage (\d+):',text[:offset+1]))
        return 'Page '+pages[-1].group(1) if pages else 'Email/text line '+str(text[:offset].count('\n')+1)
    identities=[]
    for kit in kits:
        catalog=kit.get('catalog','')
        chars=re.sub('[^A-Za-z0-9]','',catalog)
        if not chars:continue
        pattern=r'(?<![A-Za-z0-9])'+r'[-\s]*'.join(re.escape(c) for c in chars)+r'(?![A-Za-z0-9])'
        for match in re.finditer(pattern,text,re.I):identities.append((match.start(),kit['id'],catalog))
    def candidate(offset,segment):
        local=[x for x in identities if offset<=x[0]<=offset+len(segment)]
        previous=[x for x in identities if 0<=offset-x[0]<500]
        found=local or sorted(previous,reverse=True)[:1]
        if not found and len({x[1] for x in identities})==1:found=identities[:1]
        unique={x[1] for x in found}
        return (found[0][1],found[0][2]) if len(unique)==1 else ('','Not established')
    def add(field,value,segment,offset,anchor=0,**extra):
        cid,catalog=candidate(offset,segment)
        start=max(0,min(anchor-100,len(segment)-400))
        suggestions.append({'field':field,'value':value,'candidate_id':cid,'catalog':catalog,'quote':segment[start:start+400],'locator':location(offset+start),'method':VERSION,**extra})
    for offset,cid,catalog in identities:
        add('catalog',catalog,catalog,offset,candidate_id=cid,catalog=catalog)
    global_usd=bool(re.search(r'(?:currency\s*[:=]\s*USD|all prices (?:are )?in USD)',text,re.I))
    for match in re.finditer(r'[^\n;]+',text):
        segment=match.group().strip();offset=match.start()+len(match.group())-len(match.group().lstrip())
        if not segment:continue
        # Incubation/assay duration is deliberately excluded from commercial lead time.
        lead=re.search(r'\b(?:lead[ -]?time|ships?(?:\s+within)?|delivery(?:\s+time)?|availability)\s*(?::|is|of|in|approximately|about|within)?\s*((?:\d+(?:\.\d+)?\s*(?:[-–]\s*\d+(?:\.\d+)?)?\s*(?:business\s+days?|days?|weeks?))|in stock)',segment,re.I)
        if lead:add('lead_time',lead.group(1),segment,offset,anchor=lead.start(),review_note='Confirm whether this is dispatch or delivery time and any order conditions.')
        pack=re.search(r'\b(\d+)\s*(kits?|wells?|tests?)\s*(?:/\s*pack|per\s+pack)?\b',segment,re.I)
        if pack:add('pack_size',pack.group(0),segment,offset,review_note='Wells/tests are not a count of kits.')
        for money in re.finditer(r'(USD|US\$|EUR|GBP|\$|€|£)\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)',segment,re.I):
            currency=money.group(1).upper();currency={'US$':'USD','€':'EUR','£':'GBP','$':'USD' if global_usd else 'Unconfirmed ($)'}.get(currency,currency)
            amount=float(money.group(2).replace(',',''))
            excluded=bool(re.search(r'\b(?:total|subtotal|shipping|freight|tax)\b',segment,re.I))
            per_kit=bool(re.search(r'(?:per\s+kit|/\s*kit|each\s+kit)',segment,re.I))
            per_pack=bool(re.search(r'(?:per\s+pack|/\s*pack)',segment,re.I))
            kit_pack=re.search(r'\b(\d+)\s*kits?\s*(?:/\s*pack|per\s+pack)\b',segment,re.I)
            normalized=amount if per_kit and currency=='USD' and not excluded else amount/int(kit_pack.group(1)) if per_pack and kit_pack and int(kit_pack.group(1))>0 and currency=='USD' and not excluded else None
            if per_kit and per_pack:normalized=None
            unit='order/other charge' if excluded else 'per kit' if per_kit else 'per pack' if per_pack else 'unit not established'
            note='Not proposed as a kit unit price: confirm currency, unit and total/charges.' if normalized is None else f'Derived USD/kit: {amount:g} ÷ {kit_pack.group(1)} kits/pack = {normalized:g}; confirm pack count.' if per_pack and kit_pack else 'Proposed USD/kit value requires scientist confirmation.'
            add('price',amount,segment,offset,anchor=money.start(),currency=currency,unit=unit,usd_per_kit=normalized,review_note=note)
        for date_match in re.finditer(r'\b(quote date|quotation date|date|valid until|valid through|expires?(?: on)?|expiration date)\s*:\s*(.+)',segment,re.I):
            raw=date_match.group(2).strip();iso=None
            token=re.match(r'\d{4}-\d{2}-\d{2}',raw)
            try:
                if token:iso=datetime.strptime(token.group(),'%Y-%m-%d').date().isoformat()
                else:
                    try:iso=parsedate_to_datetime(raw).date().isoformat()
                    except (ValueError,TypeError):
                        for fmt in ('%B %d, %Y','%b %d, %Y','%d %B %Y','%d %b %Y'):
                            try:iso=datetime.strptime(raw,fmt).date().isoformat();break
                            except ValueError:pass
            except ValueError:pass
            field='expires_on' if date_match.group(1).lower().startswith(('valid','expir')) else 'document_date'
            add(field,iso or raw,segment,offset,iso_date=iso,review_note='Confirm document date/validity.' if iso else 'Date format is ambiguous or unsupported; enter it manually.')
    # Avoid repeatedly suggesting the same fact from duplicated headers/footers.
    result=[];seen=set()
    for item in suggestions:
        key=(item['field'],str(item['value']),item.get('candidate_id'),item.get('currency'),item.get('unit'))
        if key not in seen:result.append(item);seen.add(key)
    return {'version':VERSION,'suggestions':result[:100],'notice':'Local extraction suggestions only; scientist confirmation required. Multiple items, unconfirmed currency/units and unsupported formats remain explicit. No model API call.'}
