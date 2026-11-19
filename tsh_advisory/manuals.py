"""Content-addressed PDF retention. Run packets pin versions; updates never overwrite PDFs."""
import io,json,re,hashlib
from urllib.parse import urlparse
from pypdf import PdfReader
from .store import canonical,digest,now

def folder(store):
    path=store.root/'retained-manuals';path.mkdir(exist_ok=True);return path

def load(store,record):
    key=record.get('sha256','')
    if not re.fullmatch(r'[0-9a-f]{64}',key):raise ValueError('Invalid retained manual identifier.')
    root=folder(store);raw=(root/(key+'.pdf')).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=key:raise ValueError('Retained manual failed its file hash check.')
    data=json.loads((root/(key+'.json')).read_text(encoding='utf-8'))
    if digest(data['text'])!=data['text_hash']:raise ValueError('Retained manual text failed its hash check.')
    if record.get('text_hash') and record['text_hash']!=data['text_hash']:raise ValueError('Retained text differs from the version pinned in this run.')
    return raw,data

def cached(store,url):
    path=folder(store)/(digest(url)+'.index.json')
    if not path.exists():
        # Reuse PDFs previously retained by the report exporter, without a download.
        for old in (store.root/'manual-attachments').glob('*.json'):
            metadata=json.loads(old.read_text(encoding='utf-8'))
            if metadata.get('requested_url')!=url:continue
            pdf=old.with_suffix('.pdf')
            if not pdf.exists():continue
            raw=pdf.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=metadata.get('sha256'):raise ValueError('Previously saved manual failed its file hash check.')
            record=retain(store,raw,url,metadata.get('source_url'),catalog=metadata.get('catalog',''),method='previous export cache')
            record['retrieved_at']=metadata.get('retrieved_at',record['retrieved_at'])
            path.write_text(canonical(record),encoding='utf-8');return record
        return None
    record=json.loads(path.read_text(encoding='utf-8'));load(store,record);return record

def retain(store,raw,url,final_url=None,version='',catalog='',method='download'):
    if len(raw)>25*1024*1024:raise ValueError('Manual exceeds the 25 MB limit.')
    if not raw.lstrip().startswith(b'%PDF-'):raise ValueError('Provide a PDF manual, not a vendor HTML page.')
    reader=PdfReader(io.BytesIO(raw))
    if reader.is_encrypted or not reader.pages:raise ValueError('Manual is encrypted or empty.')
    pages=[p.extract_text() or '' for p in reader.pages]
    if not ''.join(pages).strip():raise ValueError('No readable text found. Provide a searchable PDF; scanned manuals require OCR.')
    normalize=lambda x:re.sub(r'[^A-Z0-9]','',x.upper())
    if catalog and normalize(catalog) not in normalize(' '.join(pages[:2])):raise ValueError('Opening pages do not identify this kit catalog; check the PDF and kit selection.')
    text='\n'.join(f'Page {i+1}: {page}' for i,page in enumerate(pages));key=hashlib.sha256(raw).hexdigest();root=folder(store)
    data={'text':text,'text_hash':digest(text),'pages':len(pages)}
    if not (root/(key+'.pdf')).exists():
        (root/(key+'.pdf')).write_bytes(raw);(root/(key+'.json')).write_text(canonical(data),encoding='utf-8')
    detected=re.search(r'\b(?:Rev(?:ision)?\.?|Version)\s*[:.]?\s*[A-Za-z0-9][A-Za-z0-9.\-]*', '\n'.join(pages[:2]),re.I)
    record={'sha256':key,'text_hash':data['text_hash'],'source_url':final_url or url,'requested_url':url,'retrieved_at':now(),'pages':len(pages),'version':version.strip() or (detected.group(0) if detected else 'Not stated / not identified'),'version_basis':'Reviewer supplied' if version.strip() else 'Opening-page extraction; confirm against PDF','method':method}
    (root/(digest(url)+'.index.json')).write_text(canonical(record),encoding='utf-8');return record

def source(store,record,owner):
    _,data=load(store,record);url=record['source_url']
    return dict(id=digest([url,record['sha256']])[:16],title='Retained kit manual',url=url,owner=owner,publisher=urlparse(url).hostname or 'Reviewer supplied',retrieved_at=record['retrieved_at'],content_hash=data['text_hash'],text=data['text'],allowed_use='Kit-manual planning facts; cite page and passage.',forbidden_use='Not evidence of completed validation or a binding quote.',synthetic=False)

def fetch(store,url,*,refresh=False,version='',catalog=''):
    record=None if refresh else cached(store,url)
    if record:
        raw,_=load(store,record)
        if catalog:validate_catalog(raw,catalog)
        return record
    from .agents import public_get
    final,_,raw=public_get(url)
    return retain(store,raw,url,final,version,catalog)

def attachment(store,kit,record):
    raw,_=load(store,record)
    validate_catalog(raw,kit['catalog'])
    filename=re.sub(r'[^A-Za-z0-9._-]','_',kit['catalog'])+'-manual.pdf'
    return {'bytes':raw,'metadata':{**record,'kit_id':kit['id'],'catalog':kit['catalog'],'filename':filename}}

def validate_catalog(raw,catalog):
    reader=PdfReader(io.BytesIO(raw))
    text=' '.join(reader.pages[i].extract_text() or '' for i in range(min(2,len(reader.pages))))
    normalize=lambda value:re.sub(r'[^A-Z0-9]','',value.upper())
    if normalize(catalog) not in normalize(text):raise ValueError('Opening pages do not identify this kit catalog; check the retained PDF.')
