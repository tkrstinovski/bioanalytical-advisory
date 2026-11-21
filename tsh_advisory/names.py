"""Versioned, conservative equivalence rules. Aliases never establish assay suitability."""
import re,unicodedata
VERSION='names-v2-optional-strain-primate-aliases'

def clean(value):
    value=unicodedata.normalize('NFKC',str(value)).casefold()
    return re.sub(r'[^a-z0-9]+',' ',value).strip()

def canonical(value,kind):
    original=str(value)
    if '(' in original and ')' in original:
        parts=[p.strip() for p in re.split(r'[()]',original) if p.strip()]
        values={canonical(p,kind) for p in parts}
        if len(values)==1:return values.pop()
    value=clean(value);compact=value.replace(' ','')
    registry={
      'species':{'mouse':['mouse','mice','murine','mus musculus','mouse mus musculus'],'rat':['rat','rats','rattus norvegicus','rat rattus norvegicus'],'human':['human','humans','homo sapiens','human homo sapiens'],
                 'nhp':['nhp','nhps','monkey','monkeys','non-human primate','nonhuman primate','non human primates','nonhuman primates'],
                 'cynomolgus':['cynomolgus','cyno','cynomolgus monkey','cynomolgus macaque','macaca fascicularis','crab-eating macaque'],
                 'rhesus':['rhesus','rhesus monkey','rhesus macaque','macaca mulatta']},
      'platform':{'xmap':['bio plex','bioplex','bio rad bio plex','luminex','luminex xmap','xmap','luminex xmap magnetic bead assay','luminex xmap magnetic bead based assay'],
                  'spectramax':['spectramax','molecular devices spectramax','absorbance microplate reader','microplate reader','microtitre plate reader','microtiter plate reader','microtitre reader','microtiter reader','colorimetric elisa','elisa'],'msd':['msd','meso scale discovery']},
      'analyte':{'tsh':['tsh','thyroid stimulating hormone','thyrotropin','thyrotrophin','TSH thyroid stimulating hormone','thyroid stimulating hormone TSH']},
      'matrix':{'serum':['serum','sera','mouse serum','rat serum','human serum'],'plasma':['plasma']}}
    for target,aliases in registry.get(kind,{}).items():
        if compact in [clean(a).replace(' ','') for a in aliases]:return target
    return compact

def matches(requested,supported,kind):
    target=canonical(requested,kind)
    if not target:return False
    if target==canonical(supported,kind):return True
    if kind=='species' and target=='nhp' and canonical(supported,kind) in ('cynomolgus','rhesus'):return True
    return any(target==canonical(value,kind) for value in re.split(r'[,;/|]|\band\b',str(supported),flags=re.I))

def model_name(value):
    value=clean(value)
    for vendor in ('molecular devices','bio rad','biorad'):value=value.replace(vendor,'')
    return value.replace(' ','').replace('spectramax','')

def strain_check(case,kit):
    requested=str(case.get('species_strain') or '').strip()
    reported=str(kit.get('species_strain') or '').strip()
    if not requested:return {'status':'not_requested','requested':'','reported':reported,'mismatch':False}
    if not reported:return {'status':'not_reported','requested':requested,'reported':'','mismatch':False}
    supported=clean(reported) in ('all','any','all strains','any strain','not strain specific')
    supported=supported or any(canonical(requested,'strain')==canonical(part,'strain') for part in re.split(r'[,;|]|\band\b',reported,flags=re.I))
    return {'status':'match' if supported else 'mismatch','requested':requested,'reported':reported,'mismatch':not supported}

def instrument_match(instruments,kit):
    required=model_name(kit.get('required_model',''))
    generic={'microplate reader','microtitre plate reader','microtiter plate reader','microtitre reader','microtiter reader','absorbance microplate reader'}
    reported=[kit.get('required_model','')]+list(kit.get('vendor_instruments',[]))
    if any(clean(value) in generic for value in reported):
        return any(matches(platform,'SpectraMax','platform') for platform in instruments)
    if not required:return False
    family=kit.get('platform','')
    return any(model_name(model)==required and (not family or matches(family,platform,'platform'))
               for platform,model in instruments.items() if str(model).strip())

def name_checks(case,kit):
    checks={field:{'requested':case.get(field,''),'reported':kit.get(field,''),'canonical_requested':canonical(case.get(field,''),field),'canonical_reported':canonical(kit.get(field,''),field),'match':matches(case.get(field,''),kit.get(field,''),field)} for field in ('species','analyte','matrix')}
    checks['strain']=strain_check(case,kit)
    checks['instrument']={'reported':kit.get('required_model',''),'available':case.get('instruments',{}),'match':instrument_match(case.get('instruments',{}),kit)}
    checks['platform']={'reported':kit.get('platform',''),'available':list(case.get('instruments',{})),'match':any(matches(kit.get('platform',''),p,'platform') for p in case.get('instruments',{}))}
    return checks
