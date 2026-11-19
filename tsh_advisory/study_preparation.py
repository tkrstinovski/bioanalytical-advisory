"""Backward mass balance for a pipettable study aliquot, never a dilution-suitability claim."""
from math import ceil,isclose,isfinite


def study_recipe(dilution,plate_ul,reserve_ul,minimum_ul=10):
    if not all(isfinite(x) for x in (dilution,plate_ul,reserve_ul)) or dilution<1:raise ValueError('Study preparation inputs must be finite and dilution at least 1.')
    if isclose(dilution,1):
        required=ceil(plate_ul+reserve_ul)
        return [{'dilution':'1:1','source':'Neat matrix','source_ul':max(minimum_ul,required),
                 'diluent_ul':0,'prepared_ul':max(minimum_ul,required),'transfer_next_ul':0,
                 'retained_ul':max(minimum_ul,required),'plate_ul':plate_ul,'reserve_ul':reserve_ul}]
    ratios=[];remaining=float(dilution)
    while remaining>10 and not isclose(remaining,10):ratios.append(10.0);remaining/=10
    if not isclose(remaining,1):ratios.append(remaining)
    factors=[];factor=1
    for ratio in ratios:factor*=ratio;factors.append(factor)
    result=[];next_transfer=0
    for index in reversed(range(len(ratios))):
        ratio=ratios[index];last=index==len(ratios)-1
        needed=next_transfer+(plate_ul+reserve_ul if last else 0)
        source=max(minimum_ul,ceil(needed/ratio),ceil(minimum_ul/(ratio-1)))
        prepared=source*ratio
        result.insert(0,{'dilution':f'1:{factors[index]:g}','source':'Neat matrix' if index==0 else f'Previous dilution 1:{factors[index-1]:g}',
            'source_ul':source,'diluent_ul':prepared-source,'prepared_ul':prepared,'transfer_next_ul':next_transfer,
            'retained_ul':prepared-next_transfer,'plate_ul':plate_ul if last else 0,'reserve_ul':reserve_ul if last else 0})
        next_transfer=source
    return result
