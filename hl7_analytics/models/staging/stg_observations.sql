select 
    id as observation_id, 
    patient_id, 
    resource -> 'code' ->>'text' as description, 
    resource -> 'code' -> 'coding' -> 0 ->> 'code' as loinc_code,
    resource ->> 'status' as status,
    nullif(resource->'valueQuantity'->>'value', '')::numeric  as value,
    resource -> 'valueQuantity' ->> 'unit' as unit, 
    resource ->'referenceRange'->0 ->> 'text' as  reference_range

from {{ source ('fhirdb', 'observations')}}





