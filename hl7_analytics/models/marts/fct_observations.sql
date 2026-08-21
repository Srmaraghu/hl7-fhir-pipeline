select
    o.observation_id,
    o.patient_id,
    p.mrn,
    p.family_name,
    p.gender,
    p.birth_date,
    o.loinc_code,
    o.description,
    o.value,
    o.unit,
    o.status,
    o.reference_range

from {{ ref('stg_observations') }} o
-- left join: retain all observations including those with unmatched patient_id
-- so analysts can detect orphaned observations rather than losing them silently
left join {{ ref('stg_patients') }} p
    on o.patient_id = p.patient_id
