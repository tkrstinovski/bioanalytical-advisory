from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class AdditionalParameter(Strict):
    name: str = Field(min_length=1,max_length=100)
    conditions: list[str] = Field(default_factory=lambda:['1 assessment'],min_length=1)
    lot_count: int = Field(default=3,ge=1,le=20)
    wells_per_lot_per_condition: int = Field(default=3,ge=1)
    separate_conditions: bool = False

class Intake(Strict):
    title: str = Field(min_length=1)
    analyte: str = ''
    species: str = ''
    species_strain: str = ''
    matrix: str = ''
    intended_use: str = ''
    instruments: dict[str, str] = Field(default_factory=dict)
    long_term_storage_conditions: list[str] = Field(default_factory=list)
    calculation_revision: str = 'legacy'
    available_ul: float | None = Field(default=None, gt=0)
    volume_basis: str = 'per lot sample'
    initial_wells: int = Field(default=2, ge=1)
    complete_repeats: int = Field(default=1, ge=0, le=3)
    study_count: int | None = Field(default=None, ge=1)
    lot_count: int = Field(default=3, ge=1, le=20)
    day0_wells_per_lot: int = Field(default=6, ge=1)
    stability_wells_per_lot: int = Field(default=3, ge=1)
    parallel_wells_per_dilution: int = Field(default=2, ge=1)
    freeze_wells_per_endpoint: int = Field(default=3, ge=1)
    short_term_conditions: list[str] = Field(default_factory=lambda:['4 °C · 4 hours','4 °C · 24 hours','Room temperature · 4 hours','Room temperature · 24 hours'])
    long_term_assessments: int = Field(default=0, ge=0, le=100)
    long_term_material_type: Literal['lots','animals'] = 'lots'
    long_term_material_count: int = Field(default=3, ge=3, le=3)
    long_term_wells_per_assessment: int = Field(default=3, ge=3, le=3)
    freeze_thaw_cycles: int = Field(default=3, ge=3, le=20)
    parallel_dilution_count: int = Field(default=4, ge=1, le=20)
    parallel_start_from_kit: bool = False
    parallel_start_dilution: float = Field(default=1, ge=1, le=1000000)
    parallel_serial_factor: float = Field(default=2, gt=1, le=100)
    study_dilution: float | None = Field(default=None,ge=1)
    study_dilution_override_reason: str = ''
    include_tqc_eqc: bool = False
    additional_parameters: list[AdditionalParameter] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_parameters(self):
        names={'day 0','short-term stability','parallelism','freeze-thaw','long-term stability','tqc/eqc','precision and accuracy'}
        for parameter in self.additional_parameters:
            parameter.name=parameter.name.strip()
            name=parameter.name.casefold()
            if not name or name in names:raise ValueError('Additional parameter names must be nonblank and unique, including built-in parameters.')
            names.add(name)
            parameter.conditions=[c.strip() for c in parameter.conditions if c.strip()]
            if not parameter.conditions:raise ValueError('Each additional parameter needs at least one condition or assessment.')
        return self
    assay_control_wells_per_run: int = Field(default=24,ge=0)
    precision_accuracy_plates: int = Field(default=6,ge=1)
    qc_levels: int = Field(default=5,ge=1)
    qc_wells_per_level: int = Field(default=6,ge=1)
    pa_blank_wells: int = Field(default=2,ge=0)
    pa_standard_levels: int = Field(default=7,ge=1)
    pa_standard_replicates: int = Field(default=2,ge=1)
    nonpa_blank_wells: int = Field(default=2,ge=0)
    nonpa_standard_levels: int = Field(default=7,ge=1)
    nonpa_standard_replicates: int = Field(default=2,ge=1)
    nonpa_qc_levels: int = Field(default=4,ge=1)
    nonpa_qc_replicates: int = Field(default=2,ge=1)
    preparation_leeway_ul: int = Field(default=20,ge=10,le=20)

    @property
    def nonpa_controls(self):
        return self.nonpa_blank_wells+self.nonpa_standard_levels*self.nonpa_standard_replicates+self.nonpa_qc_levels*self.nonpa_qc_replicates
    labor_rate: float = Field(default=35, gt=0)
    scientific_reviewer: str = ''
    director: str = ''
    regulatory_use: str = 'Reviewer decision required'
    deadline: str = '2026-12-06'
    budget_ceiling: float | None = Field(default=None, gt=0)
    budget_basis: Literal['internal_cost','client_price'] = 'internal_cost'
    notes: str = ''
    field_status: dict[str,str] = Field(default_factory=dict)

class Source(Strict):
    id: str
    title: str
    url: str
    owner: str
    publisher: str
    retrieved_at: str
    content_hash: str
    text: str
    allowed_use: str
    forbidden_use: str
    synthetic: bool = False

class Evidence(Strict):
    source_id: str
    locator: str
    quote: str = Field(min_length=1, max_length=400)
    claim: str

class Candidate(Strict):
    id: str
    manufacturer: str
    name: str
    catalog: str
    platform: str
    analyte: str
    species: str
    species_strain: str = ''
    matrix: str
    documentation_version: str = 'unresolved'
    required_model: str = ''
    wavelength: str = ''
    detection_mode: str = ''
    vendor_instruments: list[str] = Field(default_factory=list)
    gates: dict[str,Literal['pass','fail','unresolved']] = Field(default_factory=dict)
    evidence: dict[str,Evidence] = Field(default_factory=dict)
    well_input_ul: float | None = Field(default=None, gt=0)
    dilution_factor: float | None = Field(default=None, ge=1)
    handling_ul: float | None = Field(default=None, ge=0)
    kit_price: float | None = Field(default=None, gt=0)
    price_source: str = ''
    wells_per_kit: int = Field(default=96, ge=1)
    limitations: list[str] = Field(default_factory=list)
    lead_time: str | None = None
    lead_time_source_id: str = ''
    lead_time_checked_at: str = ''
    vendor_url: str = ''
    manual_url: str = ''
    manual_checked_at: str = ''
    retained_manual: dict = Field(default_factory=dict)
    assay_duration: str = ''
    attended_minutes_per_plate: float | None = Field(default=None,gt=0)
    labor_timing_source: str = ''
    rejection_reason: str = ''
    required_equipment: list[str] = Field(default_factory=list)
    curve_range: str = ''
    reviewer_lead_time: str = ''
    reviewer_notes: str = ''
    reviewer_edits: dict[str,dict] = Field(default_factory=dict)
    cell_evidence: dict[str,dict] = Field(default_factory=dict)

class Experiment(Strict):
    parameter: str
    conditions: list[str] = Field(min_length=1)
    wells_per_lot_per_condition: int = Field(ge=1)
    dilution_factors: list[float] = Field(min_length=1)
    handling_ul_per_lot: float = Field(ge=0)
    controls_per_run: int | None = Field(default=None,ge=0)
    control_breakdown: dict[str,int] = Field(default_factory=dict)
    control_layout_basis: str = 'Unresolved; requires kit-specific standards, QCs and blanks.'
    dilution_dead_ul: float = Field(default=0,ge=0)
    sharing_group: str = 'review_required'
    independent_runs: int = Field(ge=1)
    timing: str
    rationale: str
    material_count: int | None = Field(default=None,ge=1)
    material_type: Literal['lots','animals'] = 'lots'
    separate_conditions: bool = False

class Plan(Strict):
    experiments: list[Experiment]
    proposed_conditions: bool = True
    guidance_rationale: str = ''
    additional_work: list[str]
    freeze_endpoint_plan: str = ''
    acceptance_criteria: dict[str,str] = Field(default_factory=dict)
    parameter_decisions: dict[str,str] = Field(default_factory=dict)
    qc_matrix_dilution: float | None = Field(default=None,ge=1)

class CostAssumptions(Strict):
    development_hours: float = Field(ge=0)
    validation_hours: float = Field(ge=0)
    instrument_hours: float = Field(ge=0)
    instrument_rate: float = Field(ge=0)
    shipping: float = Field(ge=0)
    consumables: float = Field(ge=0)
    pooled_material: float | None = Field(default=None, ge=0)
    overhead_rate: float = Field(ge=0, le=2)
    contingency_rate: float = Field(ge=0, le=1)
    gross_margin: float = Field(ge=0, lt=1)
    rationale: str
    currency: str = 'USD'
    labor_hours_per_plate: float | None = Field(default=None,ge=0)
    reader_hours_per_plate: float | None = Field(default=None,ge=0)
    consumables_per_plate: float | None = Field(default=None,ge=0)
    shipping_per_kit: float | None = Field(default=None,ge=0)
    class_estimate_mode: bool = False
    shipping_policy: Literal['legacy','per_kit_plus_matrix'] = 'legacy'
    estimate_rules_version: int = 0
    kit_shipment_usd: float | None = Field(default=None,ge=0)
    matrix_shipment_usd: float | None = Field(default=None,ge=0)
    shipping_basis: str = ''
    shipping_source: str = 'https://www.fedex.com/en-us/shipping/rate-changes.html'
    setup_minutes_per_plate: float = Field(default=15,ge=0)
    review_minutes_per_plate: float = Field(default=30,ge=0)
    labor_timing_basis: str = ''
    reviewer_estimates: dict[str,dict] = Field(default_factory=dict)
    costing_basis: str = 'legacy fixed totals'
    overrides: dict[str,float] = Field(default_factory=dict)
    overrides_confirmed_for: str = ''

class Findings(Strict):
    section: str
    severity: Literal['critical','major','minor']
    message: str
    owner: str
    scope: Literal['project','selected_kit','alternative_only'] = 'project'
    candidate_ids: list[str] = Field(default_factory=list)
    affects_selection_rationale: bool = False
    scope_basis: str = ''
    category: Literal['planning','instrument_availability','instrument_execution','instrument_compatibility','essential_configuration','expected_concentration_unknown','range_coverage_mismatch'] = 'planning'
    instrument_model: str = ''
    required_configuration: str = ''
    evidence_reference: str = ''
    issue_code: str = ''
    scope_class: Literal['planning','execution_detail','out_of_scope','technical_record'] = 'planning'

def tsh_case():
    return Intake(title='Mouse serum TSH preclinical safety assessment', analyte='TSH', species='mouse', matrix='serum',
        intended_use='Detect treatment-related changes versus controls', available_ul=100,
        instruments={'SpectraMax':'','Bio-Plex':'','MSD':''})
