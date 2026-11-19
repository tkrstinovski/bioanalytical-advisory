"""User-provided internal costing rules; not vendor price claims."""
from .names import canonical,clean

OVERHEAD_RATE=.15

def instrument_plate_rate(platform):
    family=canonical(platform,'platform')
    value=clean(platform).replace(' ','')
    if family=='spectramax' or value.startswith('spectramax'):return 10.0
    if family in ('xmap','msd') or value.startswith(('bioplex','bioradbioplex','msd','mesoscale')):return 35.0
    return None
