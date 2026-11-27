with fonte as (
    select * from {{ source('raw', 'bcb_sgs') }}
)

select
    serie_codigo,
    serie_nome,
    cast(data as date)                         as data_referencia,
    cast(date_trunc('month', data) as date)    as mes_referencia,
    cast(valor as double)                      as valor,
    extraido_em
from fonte
