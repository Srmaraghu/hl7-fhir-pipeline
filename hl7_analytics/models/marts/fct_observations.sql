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
-- inner join: observations without a valid patient are not analytically useful
-- this also aligns with the not_null + relationships tests on patient_id
inner join {{ ref('stg_patients') }} p
    on o.patient_id = p.patient_id
