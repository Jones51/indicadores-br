-- Uma linha por mudança da meta Selic (SGS 432, série diária).
-- A data é a do primeiro dia em que a série mostra a meta nova (vigência), que costuma ser
-- o dia seguinte à reunião do Copom: não é a data da reunião (ADR 0008).
with stg as (
    select * from {{ ref('stg_bcb__sgs') }}
),

selic_diaria as (
    select
        data_referencia,
        valor as selic_meta_aa
    from stg
    where serie_nome = 'selic_meta'
),

com_anterior as (
    select
        data_referencia,
        selic_meta_aa,
        lag(selic_meta_aa) over (order by data_referencia) as selic_anterior_aa
    from selic_diaria
)

-- O primeiro dia da série não tem anterior e não é decisão: fica de fora pelo filtro.
select
    data_referencia                                                       as data_vigencia,
    selic_anterior_aa,
    selic_meta_aa                                                         as selic_nova_aa,
    cast(round((selic_meta_aa - selic_anterior_aa) * 100) as integer)     as variacao_bp
from com_anterior
where selic_meta_aa <> selic_anterior_aa
order by data_vigencia
