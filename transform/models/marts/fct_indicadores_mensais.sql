-- Uma linha por mês com os principais indicadores consolidados.
-- A espinha de meses vem de todas as séries: um mês aparece assim que qualquer
-- indicador tiver observação (ex.: mês corrente com Selic e dólar, antes do IPCA sair).
with stg as (
    select * from {{ ref('stg_bcb__sgs') }}
),

meses as (
    select distinct mes_referencia
    from stg
),

-- Séries diárias: Selic meta = último valor do mês; dólar = média do mês
selic as (
    select
        mes_referencia,
        arg_max(valor, data_referencia) as selic_meta_aa
    from stg
    where serie_nome = 'selic_meta'
    group by 1
),

dolar as (
    select
        mes_referencia,
        avg(valor) as dolar_ptax_medio,
        arg_max(valor, data_referencia) as dolar_ptax_fim_mes
    from stg
    where serie_nome = 'dolar_ptax_venda'
    group by 1
),

-- Séries mensais: já vêm com uma observação por mês
ipca as (
    select
        mes_referencia,
        max(case when serie_nome = 'ipca_mensal' then valor end) as ipca_mensal,
        max(case when serie_nome = 'ipca_12m' then valor end)    as ipca_12m
    from stg
    where serie_nome in ('ipca_mensal', 'ipca_12m')
    group by 1
)

select
    meses.mes_referencia,
    selic.selic_meta_aa,
    ipca.ipca_mensal,
    ipca.ipca_12m,
    -- Juro real ex-post (Fisher): (1 + selic) / (1 + ipca 12m) - 1; nulo se faltar insumo
    round(((1 + selic.selic_meta_aa / 100) / (1 + ipca.ipca_12m / 100) - 1) * 100, 4)
        as juro_real_ex_post_aa,
    dolar.dolar_ptax_medio,
    dolar.dolar_ptax_fim_mes
from meses
left join selic using (mes_referencia)
left join ipca using (mes_referencia)
left join dolar using (mes_referencia)
order by meses.mes_referencia
