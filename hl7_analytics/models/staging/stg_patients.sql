select
    id                                        as patient_id,
    resource->'identifier'->0->>'value'       as mrn,
    resource->'name'->0->>'family'            as family_name,
    resource->'name'->0->'given'->>0          as given_name,
    resource->>'gender'                       as gender,
    nullif(resource->>'birthDate', '')::date  as birth_date,
    resource->'address'->0->>'city'           as city,
    resource->'address'->0->>'state'          as state,
    resource->'address'->0->>'postalCode'     as postal_code,
    resource->'telecom'->0->>'value'          as phone
from {{ source('fhirdb', 'patients') }}