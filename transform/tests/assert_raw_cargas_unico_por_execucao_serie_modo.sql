-- Falha se a auditoria tiver mais de uma linha por (execução, série, modo).
-- Na reconciliação, a mesma execução tem uma linha `incremental` e uma `full` por série.
select execucao_id, serie_nome, modo, count(*) as n
from {{ source('raw', 'cargas') }}
group by 1, 2, 3
having count(*) > 1
