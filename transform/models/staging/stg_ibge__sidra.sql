with fonte as (
    select * from {{ source('raw', 'ibge_sidra') }}
)

select
    serie_nome,
    cast(tabela as integer)                    as tabela_codigo,
    cast(variavel as integer)                  as variavel_codigo,
    cast(periodo_codigo as varchar)            as periodo_codigo,
    cast(periodo_nome as varchar)              as periodo_nome,
    cast(data as date)                         as data_referencia,
    cast(valor as double)                      as valor,
    cast(unidade as varchar)                   as unidade,
    extraido_em
from fonte
