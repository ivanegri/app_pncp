"""
utils_embeddings.py — Match Semântico via Google Gemini Embeddings + BigQuery Vector Search

Implementa a Camada 2 de linkagem Passado ↔ Futuro:
- Gera embeddings vetoriais de descrições de itens via Gemini text-embedding-004
- Persiste os embeddings na coluna `embedding` das tabelas BigQuery
- Busca itens históricos similares via VECTOR_SEARCH() do BigQuery

Arquitetura:
    Texto → Gemini text-embedding-004 → ARRAY<FLOAT64> (768 dims)
    → Armazenado na coluna `embedding` em `itens` e `compras_abertas`
    → VECTOR_SEARCH() retorna os N vizinhos mais próximos por cosseno

IMPORTANTE:
    Para usar VECTOR_SEARCH no BigQuery, a tabela precisa ter um Vector Index:
    CREATE VECTOR INDEX idx_itens_embedding ON `dataset.itens`(embedding)
    OPTIONS(distance_type='COSINE', index_type='IVF')

    ATENÇÃO — migração de dims:
    O Gemini text-embedding-004 gera vetores de 768 dimensões (vs 1536 do OpenAI).
    Se a coluna `embedding` já existia com 1536 dims, recrie-a ou crie uma nova coluna
    antes de re-indexar os registros existentes.
"""

import os
import json
from typing import Optional
import google.generativeai as genai

EMBEDDING_MODEL = "text-embedding-004"  # 768 dims, baixo custo, alta qualidade
EMBEDDING_DIMS = 768


def _configure_genai():
    """Configura a SDK do Gemini com a API key do ambiente."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY não configurada no ambiente.")
    genai.configure(api_key=api_key)


def generate_embedding(text: str) -> list[float]:
    """
    Gera um vetor de embedding para o texto fornecido via Gemini.

    Args:
        text: Descrição do item a ser vetorizado

    Returns:
        Lista de 768 floats representando o embedding

    Notas sobre task_type:
        "RETRIEVAL_DOCUMENT"  → para textos que serão indexados/armazenados
        "RETRIEVAL_QUERY"     → para textos de consulta (busca)
        Usar task_type correto melhora a qualidade do match semântico.
    """
    _configure_genai()

    # Limpar e truncar texto (limite seguro para o modelo)
    text = text.strip().replace("\n", " ")[:2000]

    result = genai.embed_content(
        model=f"models/{EMBEDDING_MODEL}",
        content=text,
        task_type="RETRIEVAL_QUERY",  # usado para buscas pontuais
    )
    return result["embedding"]


def generate_embedding_for_storage(text: str) -> list[float]:
    """
    Variante de generate_embedding com task_type=RETRIEVAL_DOCUMENT.
    Use esta função ao gerar e persistir embeddings em lote no BigQuery.

    Args:
        text: Descrição do item a ser indexado

    Returns:
        Lista de 768 floats
    """
    _configure_genai()

    text = text.strip().replace("\n", " ")[:2000]

    result = genai.embed_content(
        model=f"models/{EMBEDDING_MODEL}",
        content=text,
        task_type="RETRIEVAL_DOCUMENT",
    )
    return result["embedding"]


def find_similar_items(
    description: str,
    top_n: int = 10,
    min_similarity: float = 0.6,
    project_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
) -> list[dict]:
    """
    Encontra os N itens históricos mais similares à descrição fornecida
    usando BigQuery VECTOR_SEARCH (busca por similaridade de cosseno).

    Args:
        description: Descrição textual do item futuro
        top_n: Número de vizinhos a retornar
        min_similarity: Similaridade mínima (0 a 1) para incluir no resultado
        project_id: GCP Project ID (usa env GCP_PROJECT_ID se omitido)
        dataset_id: BigQuery Dataset ID (usa env GCP_DATASET_ID se omitido)

    Returns:
        Lista de dicts com colunas do item + `similarity_score`
    """
    from google.cloud import bigquery as bq_module

    pid = project_id or os.environ.get("GCP_PROJECT_ID", "pncp-466018")
    did = dataset_id or os.environ.get("GCP_DATASET_ID", "pncp_data")

    embedding = generate_embedding(description)
    embedding_str = json.dumps(embedding)

    client = bq_module.Client(project=pid)

    sql = f"""
        SELECT
            base.descricaoItem,
            base.valorUnitario,
            base.quantidadeHomologada,
            base.unidadeMedida,
            base.nomeOrgao,
            base.parent_numeroControlePNCPAta,
            base.numeroItem,
            1 - distance AS similarity_score
        FROM
            VECTOR_SEARCH(
                TABLE `{pid}.{did}.itens`,
                'embedding',
                (SELECT {embedding_str} AS embedding),
                top_k => @top_n,
                distance_type => 'COSINE'
            )
        WHERE
            1 - distance >= @min_similarity
            AND base.valorUnitario IS NOT NULL
            AND base.valorUnitario > 0
        ORDER BY
            similarity_score DESC
    """

    job_config = bq_module.QueryJobConfig(
        query_parameters=[
            bq_module.ScalarQueryParameter("top_n", "INT64", top_n),
            bq_module.ScalarQueryParameter("min_similarity", "FLOAT64", min_similarity),
        ]
    )

    results = list(client.query(sql, job_config=job_config).result())
    return [dict(row) for row in results]


def find_similar_by_exact_match(
    codigo_item: Optional[str] = None,
    cnpj_orgao: Optional[str] = None,
    limit: int = 20,
    project_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
) -> list[dict]:
    """
    Camada 1: Match exato por CATMAT/CATSER ou CNPJ do órgão.
    Mais rápido que o semântico; usado como primeira abordagem.

    Args:
        codigo_item: Código CATMAT ou CATSER do item
        cnpj_orgao: CNPJ do órgão comprador (para ver histórico do mesmo órgão)
        limit: Número máximo de resultados

    Returns:
        Lista de dicts com itens históricos correspondentes
    """
    from google.cloud import bigquery as bq_module

    pid = project_id or os.environ.get("GCP_PROJECT_ID", "pncp-466018")
    did = dataset_id or os.environ.get("GCP_DATASET_ID", "pncp_data")

    if not codigo_item and not cnpj_orgao:
        return []

    client = bq_module.Client(project=pid)

    conditions = []
    params = []

    if codigo_item:
        conditions.append("i.codigoItem = @codigo_item")
        params.append(bq_module.ScalarQueryParameter("codigo_item", "STRING", str(codigo_item)))

    if cnpj_orgao:
        conditions.append("CAST(i.parent_cnpj AS STRING) = @cnpj_orgao")
        params.append(bq_module.ScalarQueryParameter("cnpj_orgao", "STRING", str(cnpj_orgao)))

    where_clause = " OR ".join(conditions)

    sql = f"""
        SELECT
            i.descricaoItem,
            i.valorUnitario,
            i.quantidadeHomologada,
            i.unidadeMedida,
            i.nomeOrgao,
            i.parent_numeroControlePNCPAta,
            i.numeroItem,
            a.vigenciaInicio,
            a.vigenciaFim,
            'exact_match' AS match_type
        FROM `{pid}.{did}.itens` i
        LEFT JOIN `{pid}.{did}.atas` a
            ON i.parent_numeroControlePNCPAta = a.numeroControlePNCPAta
        WHERE {where_clause}
            AND i.valorUnitario IS NOT NULL
            AND i.valorUnitario > 0
        ORDER BY a.vigenciaInicio DESC
        LIMIT @limit
    """

    job_config = bq_module.QueryJobConfig(
        query_parameters=params + [
            bq_module.ScalarQueryParameter("limit", "INT64", limit)
        ]
    )

    results = list(client.query(sql, job_config=job_config).result())
    return [dict(row) for row in results]


def get_price_benchmark(
    description: str,
    codigo_item: Optional[str] = None,
    cnpj_orgao: Optional[str] = None,
) -> dict:
    """
    Retorna um balizador de preços completo, combinando match exato + semântico.

    Returns:
        {
            "exact_matches": [...],
            "semantic_matches": [...],
            "benchmark": {
                "min": float,
                "max": float,
                "avg": float,
                "count": int,
                "source": "exact|semantic|exact+semantic"
            }
        }
    """
    exact = find_similar_by_exact_match(codigo_item=codigo_item, cnpj_orgao=cnpj_orgao)
    semantic = find_similar_items(description)

    all_prices = []
    source_parts = []

    if exact:
        prices_exact = [r["valorUnitario"] for r in exact if r.get("valorUnitario")]
        all_prices.extend(prices_exact)
        source_parts.append("exact")

    if semantic:
        prices_semantic = [r["valorUnitario"] for r in semantic if r.get("valorUnitario")]
        all_prices.extend(prices_semantic)
        source_parts.append("semantic")

    benchmark = {}
    if all_prices:
        benchmark = {
            "min": min(all_prices),
            "max": max(all_prices),
            "avg": sum(all_prices) / len(all_prices),
            "count": len(all_prices),
            "source": "+".join(source_parts) if source_parts else "none",
        }

    return {
        "exact_matches": exact,
        "semantic_matches": semantic,
        "benchmark": benchmark,
    }
