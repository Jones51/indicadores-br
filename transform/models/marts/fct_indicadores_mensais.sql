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
),

-- Metas de inflação do CMN (seed). Vale a linha mais recente com ano <= ano do mês: até 2024
-- há uma linha por ano; a de 2025 (meta contínua) segue valendo nos anos seguintes (ADR 0007).
metas as (
    select * from {{ ref('metas_inflacao') }}
),

meta_vigente as (
    select
        meses.mes_referencia,
        arg_max(metas.meta, metas.ano)       as meta,
        arg_max(metas.tolerancia, metas.ano) as tolerancia
    from meses
    inner join metas on metas.ano <= year(meses.mes_referencia)
    group by 1
),

-- Posição do IPCA 12m em relação à banda (limites inclusivos: no teto ainda está dentro).
-- O IPCA vem com 2 casas; arredondar evita que ruído de float tire um valor do limite.
status_meta as (
    select
        ipca.mes_referencia,
        case
            when round(ipca.ipca_12m, 2) > meta_vigente.meta + meta_vigente.tolerancia then 'acima'
            when round(ipca.ipca_12m, 2) < meta_vigente.meta - meta_vigente.tolerancia then 'abaixo'
            else 'dentro'
        end as status_meta_inflacao
    from ipca
    inner join meta_vigente using (mes_referencia)
    where ipca.ipca_12m is not null
),

-- Sequência de meses consecutivos com o mesmo status (ilhas): a diferença entre a numeração
-- geral e a numeração dentro do status é constante enquanto o status não muda.
ilhas_status as (
    select
        mes_referencia,
        status_meta_inflacao,
        row_number() over (order by mes_referencia)
            - row_number() over (partition by status_meta_inflacao order by mes_referencia)
            as ilha
    from status_meta
),

sequencia_status as (
    select
        mes_referencia,
        status_meta_inflacao,
        row_number() over (
            partition by status_meta_inflacao, ilha order by mes_referencia
        ) as meses_seguidos_status_meta
    from ilhas_status
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
    dolar.dolar_ptax_fim_mes,
    cast(meta_vigente.meta as double)                           as meta_inflacao,
    cast(meta_vigente.meta - meta_vigente.tolerancia as double) as meta_inflacao_inferior,
    cast(meta_vigente.meta + meta_vigente.tolerancia as double) as meta_inflacao_superior,
    sequencia_status.status_meta_inflacao,
    sequencia_status.meses_seguidos_status_meta
from meses
left join selic using (mes_referencia)
left join ipca using (mes_referencia)
left join dolar using (mes_referencia)
left join meta_vigente using (mes_referencia)
left join sequencia_status using (mes_referencia)
order by meses.mes_referencia
