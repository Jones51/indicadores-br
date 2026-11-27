-- Falha se houver mais de uma observação por (série, data).
select serie_nome, data_referencia, count(*) as n
from {{ ref('stg_ibge__sidra') }}
group by 1, 2
having count(*) > 1
