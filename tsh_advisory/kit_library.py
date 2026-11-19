"""Manual-indexed examples. No price, local qualification or approval is inferred."""
from copy import deepcopy

KITS={
 'EEL110':dict(name='Invitrogen Mouse Thyroid Stimulating Hormone ELISA Kit',catalog='EEL110',species='mouse',manufacturer='Thermo Fisher Scientific / Invitrogen',platform='SpectraMax',
    vendor_url='https://www.thermofisher.com/elisa/product/Mouse-Thyroid-Stimulating-Hormone-ELISA-Kit/EEL110',
    manual_url='https://documents.thermofisher.com/TFS-Assets%2FBID%2Fmanuals%2FEEL110-manual.pdf',
    manual_checked_at='2026-11-14 UTC',documentation_version='Rev 2.1',well_input_ul=100,dilution_factor=None,
    curve_range='1.25–80 ng/mL',assay_duration='Manual: 3.5 hours total assay time. Product page: 1 hour 20 minutes hands-on. Sample preparation and any extra dilution must also be scheduled.',
    attended_minutes_per_plate=80,labor_timing_source='https://www.thermofisher.com/elisa/product/Mouse-Thyroid-Stimulating-Hormone-ELISA-Kit/EEL110 (product specifications: Hands-on time; checked 2026-11-17)',
    vendor_instruments=['Absorbance microplate reader capable of measurement at or near 450 nm'],
    required_equipment=['450 nm absorbance microplate reader and analysis software','Automatic plate washer OR manual washing equipment','37 °C incubator','Calibrated adjustable pipettes and dilution tubes','Centrifuge','Cold storage','40 °C water bath only if wash-buffer crystals need dissolving']),
 'MPTMAG49K':dict(name='MILLIPLEX Mouse Pituitary Magnetic Bead Panel',catalog='MPTMAG-49K',species='mouse',
    vendor_url='https://www.sigmaaldrich.com/US/en/product/mm/mptmag49k',
    manual_url='https://www.sigmaaldrich.com/deepweb/assets/sigmaaldrich/product/documents/237/974/protocol-mptmag49k-ms.pdf',
    manual_checked_at='2026-11-14 UTC',documentation_version='00003798MAN Rev 11/25',
    well_input_ul=10,dilution_factor=1,
    curve_range='12.2–50,000 pg/mL (TSH)',assay_duration='Primary incubation: 2 hours at 20–25 °C OR 16–18 hours at 4 °C. Additional detection/reporter incubations, washing, preparation and acquisition extend total elapsed time.',
    vendor_instruments=['Luminex 200 / HTS','FLEXMAP 3D','MAGPIX with xPONENT software','xMAP INTELLIFLEX with INTELLIFLEX software'],
    required_equipment=['Compatible Luminex reader','Plate shaker','Sonicator','Vortex mixer','Magnetic plate washer OR handheld magnetic separation block (filter/vacuum route is an alternative)','Pipettes and multichannel pipettes','Centrifuge','Cold storage; controlled 4 °C incubation for overnight route'])
}

def kit_metadata(kit):
    key=kit.get('catalog','').replace('-','').upper()
    return deepcopy(KITS.get(key,{}))

def display_kit(kit):
    result=deepcopy(kit);metadata=kit_metadata(kit)
    for field in ('vendor_url','manual_url','manual_checked_at','assay_duration','required_equipment','curve_range','vendor_instruments','attended_minutes_per_plate','labor_timing_source'):
        if not result.get(field) and metadata.get(field):result[field]=metadata[field]
    return result

def manual_demo(case):
    from .agents import fixture
    from .store import digest
    result=fixture(case);result['candidates']=[]
    for i,metadata in enumerate(sorted(KITS.values(),key=lambda k:k['catalog'],reverse=True),1):
        source_id=f'manual-demo-{i}'
        text=f"Manual-indexed test data: {metadata['catalog']}; {metadata['well_input_ul']} µL sample input; dilution {metadata['dilution_factor']}. Financial assumptions are synthetic; local readiness is unverified."
        result['sources'][source_id]=dict(result['sources']['fixture-source'],id=source_id,title=metadata['name']+' manual-indexed test record',url=metadata['manual_url'],retrieved_at=metadata['manual_checked_at'],text=text,content_hash=digest(text))
        species=case.species if case.species.casefold() in metadata['species'] else metadata['species']
        candidate=dict(id=f'manual-demo-{i}',manufacturer='MilliporeSigma',platform='Bio-Plex',analyte='TSH',matrix='serum',
            required_model='',handling_ul=15,kit_price=None,price_source='',wells_per_kit=96,
            gates={g:'unresolved' for g in ('identity','matrix','instrument','range','volume')},evidence={},limitations=['Manual-indexed demonstration; local compatibility and suitability require review.'])
        candidate.update(metadata);candidate['species']=species
        result['candidates'].append(candidate)
    return result
