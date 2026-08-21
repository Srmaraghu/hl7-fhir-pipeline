select
    id                                                              as observation_id,
    patient_id,
    resource -> 'code' ->> 'text'                                   as description,
    resource -> 'code' -> 'coding' -> 0 ->> 'code'                  as loinc_code,
    resource ->> 'status'                                           as status,

    -- guard against non-numeric free-text values including exponent notation (e.g. 5.4e-3)
    case
        when resource -> 'valueQuantity' ->> 'value'
            ~ '^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$'
        then (resource -> 'valueQuantity' ->> 'value')::numeric
        else null
    end                                                             as value,

    resource -> 'valueQuantity' ->> 'unit'                          as unit,
    resource -> 'referenceRange' -> 0 ->> 'text'                    as reference_range

from {{ source('fhirdb', 'observations') }}
