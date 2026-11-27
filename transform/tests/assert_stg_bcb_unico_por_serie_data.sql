-- Falha se houver mais de uma observação por (série, data).
select serie_codigo, data_referencia, count(*) as n
from {{ ref('stg_bcb__sgs') }}
group by 1, 2
having count(*) > 1
