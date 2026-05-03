"""
utils_ai.py — Agente Analisador de Licitações via OpenAI

Funções:
- analyze_search_results(): análise de resultados de pesquisa histórica
- analyze_oportunidade(): análise de um edital futuro com balizamento histórico
- get_client(): retorna o cliente OpenAI configurado
"""

import os
import json
from typing import Generator

def get_openai_client():
    """Retorna o cliente OpenAI configurado via variável de ambiente."""
    try:
        from openai import OpenAI
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY não configurada no ambiente.")
        return OpenAI(api_key=api_key)
    except ImportError:
        raise ImportError("Pacote 'openai' não instalado. Execute: pip install openai")


def _get_model() -> str:
    """Retorna o modelo OpenAI configurado. Padrão: gpt-4o-mini (custo-benefício)."""
    return os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')


def analyze_search_results(query: str, results: list) -> Generator[str, None, None]:
    """
    Analisa resultados de uma pesquisa histórica de itens/atas do PNCP.
    Retorna um generator de chunks de texto (streaming SSE).

    Args:
        query: Termo de busca do usuário
        results: Lista de dicts com os itens/atas retornados pelo BigQuery
    """
    client = get_openai_client()

    # Preparar dados resumidos para poupar tokens
    items_summary = []
    for r in results[:20]:  # Limitar a 20 itens para controle de tokens
        item = {
            "descricao": r.get("descricaoItem") or r.get("objetoContratacao") or "",
            "unidade": r.get("unidadeMedida") or "",
            "preco_unitario": r.get("valorUnitario") or r.get("precoUnitario") or 0,
            "quantidade": r.get("quantidadeHomologada") or r.get("quantidade") or 0,
            "orgao": r.get("nomeOrgao") or r.get("nomeUnidadeOrgao") or "",
            "uf": r.get("state") or r.get("uf") or "",
            "data": str(r.get("vigenciaInicio") or r.get("dataHomologacao") or ""),
        }
        items_summary.append(item)

    prompt_data = json.dumps(items_summary, ensure_ascii=False, indent=2)

    system_prompt = """Você é um analista especialista em compras públicas brasileiras e licitações do PNCP (Portal Nacional de Contratações Públicas).
Sua função é analisar conjuntos de dados de atas de registro de preços e itens licitados, extraindo insights valiosos para fornecedores e gestores públicos.
Responda SEMPRE em Markdown formatado, com títulos, bullets e números em negrito.
Seja direto, objetivo e preciso. Priorize insights acionáveis."""

    user_prompt = f"""Analise os seguintes {len(items_summary)} registros do PNCP relacionados a "{query}":

```json
{prompt_data}
```

Forneça uma análise completa com as seguintes seções:

## 📊 Resumo Geral
- Volume de registros analisados
- Período abrangido

## 💰 Análise de Preços
- Preço médio, mínimo e máximo (calcule a partir dos dados)
- Variações relevantes e possíveis outliers
- Tendência de preços observada

## 🏢 Principais Compradores
- Top órgãos/entidades que mais compraram
- Estados com maior concentração de compras

## 🏭 Fornecedores & Mercado
- Padrões observados na descrição dos itens
- Unidades de medida mais comuns
- Observações sobre padronização

## ⚠️ Alertas & Riscos
- Variações de preço suspeitas ou atípicas
- Qualquer sinal de superfaturamento ou subprecificação

## 💡 Recomendação
- Qual seria um preço competitivo para fornecimento de "{query}"?
- O que um fornecedor deve saber antes de participar?"""

    stream = client.chat.completions.create(
        model=_get_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=True,
        temperature=0.3,
        max_tokens=1500,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


def analyze_oportunidade(edital: dict, historico: list) -> Generator[str, None, None]:
    """
    Analisa um edital futuro comparando com o histórico de preços similares.
    Ideal para balizamento e decisão de participar ou não.

    Args:
        edital: Dict com dados do edital/compra aberta
        historico: Lista de itens históricos similares (via match exato ou semântico)
    """
    client = get_openai_client()

    edital_summary = {
        "objeto": edital.get("objetoCompra") or edital.get("objetoContratacao") or "",
        "orgao": edital.get("nomeUnidadeOrgao") or edital.get("nomeOrgao") or "",
        "uf": edital.get("uf") or edital.get("ufNome") or "",
        "valor_estimado": edital.get("valorTotalEstimado") or 0,
        "data_encerramento": str(edital.get("dataEncerramentoProposta") or ""),
        "modalidade": edital.get("modalidadeNome") or "",
    }

    historico_summary = []
    for h in historico[:15]:
        historico_summary.append({
            "descricao": h.get("descricaoItem") or "",
            "preco": h.get("valorUnitario") or 0,
            "quantidade": h.get("quantidadeHomologada") or 0,
            "orgao": h.get("nomeOrgao") or "",
            "data": str(h.get("vigenciaInicio") or ""),
        })

    system_prompt = """Você é um consultor especialista em licitações públicas brasileiras.
Analise editais futuros comparando com dados históricos do PNCP para ajudar fornecedores a tomar decisões estratégicas.
Responda em Markdown estruturado, com foco em informações acionáveis."""

    user_prompt = f"""Analise o seguinte edital aberto e compare com o histórico de preços similares:

**EDITAL ABERTO:**
```json
{json.dumps(edital_summary, ensure_ascii=False, indent=2)}
```

**HISTÓRICO DE PREÇOS SIMILARES ({len(historico_summary)} registros):**
```json
{json.dumps(historico_summary, ensure_ascii=False, indent=2)}
```

Forneça:

## 🎯 Sobre o Edital
- Resumo do que está sendo licitado
- Órgão comprador e localização

## 📈 Balizamento de Preços
- Preço médio histórico para item similar
- Faixa de preços observada (mín - máx)
- Compare com o valor estimado do edital

## 🚦 Parecer Estratégico
- Vale a pena participar? Por quê?
- Qual seria um preço competitivo para proposta?
- Riscos ou pontos de atenção

## 📋 Checklist do Fornecedor
- Documentos típicos exigidos neste tipo de licitação
- Prazo e próximos passos"""

    stream = client.chat.completions.create(
        model=_get_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=True,
        temperature=0.3,
        max_tokens=1500,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
