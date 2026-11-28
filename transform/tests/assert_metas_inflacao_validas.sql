-- Metas de inflação (seed): valores plausíveis e anos contíguos.
-- Falha (retorna linhas) se:
--   * a meta ou a tolerância estiver fora de uma faixa plausível (pega erro de digitação,
--     ex.: 45 em vez de 4.5, ou escala 0-1 em vez de 0-100);
--   * o piso da banda (meta - tolerância) não for positivo;
--   * faltar algum ano entre o primeiro e o último: o mart pega a meta mais recente com
--     ano <= ano do mês, então um buraco repetiria a meta do ano anterior sem avisar.
with metas as (
    select * from {{ ref('metas_inflacao') }}
),

fora_da_faixa as (
    select ano, 'meta ou tolerância fora da faixa' as problema
    from metas
    where meta not between 1 and 10
        or tolerancia not between 0.5 and 3
        or meta - tolerancia <= 0
),

-- anos contíguos: cada ano é o anterior + 1 (lag evita gerar a série esperada)
anos_faltando as (
    select ano, 'ano faltando no seed antes deste' as problema
    from (
        select ano, ano - lag(ano) over (order by ano) as salto
        from metas
    )
    where salto <> 1
)

select * from fora_da_faixa
union all
select * from anos_faltando
