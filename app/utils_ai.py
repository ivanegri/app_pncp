"""
utils_ai.py — Agente Analisador de Licitações via Google Gemini

Funções:
- analyze_search_results(): análise de resultados de pesquisa histórica
- analyze_oportunidade(): análise de um edital futuro com balizamento histórico
- get_gemini_client(): retorna o cliente Gemini configurado
"""

import os
import json
from typing import Generator
from google import genai
from google.genai import types


def _get_model_name() -> str:
    """Retorna o modelo Gemini configurado. Padrão: gemini-2.0-flash (custo-benefício)."""
    return os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


def get_gemini_client() -> genai.Client:
    """
    Configura e retorna um cliente Gemini (novo SDK google-genai).
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY não configurada no ambiente.")
    return genai.Client(api_key=api_key)


def analyze_search_results(query: str, results: list) -> Generator[str, None, None]:
    """
    Analisa resultados de uma pesquisa histórica de itens/atas do PNCP.
    Retorna um generator de chunks de texto (streaming SSE).

    Args:
        query: Termo de busca do usuário
        results: Lista de dicts com os itens/atas retornados pelo BigQuery
    """
    items_summary = []
    for r in results[:100]:  # Limitar a 20 itens para controle de tokens
        items_summary.append({
            "descricao": r.get("descricaoItem") or r.get("objetoContratacao") or "",
            "unidade": r.get("unidadeMedida") or "",
            "preco_unitario": r.get("valorUnitario") or r.get("precoUnitario") or 0,
            "quantidade": r.get("quantidadeHomologada") or r.get("quantidade") or 0,
            "orgao": r.get("nomeOrgao") or r.get("nomeUnidadeOrgao") or "",
            "uf": r.get("state") or r.get("uf") or "",
            "data": str(r.get("vigenciaInicio") or r.get("dataHomologacao") or ""),
            "fornecedor": r.get("fornecedor") or "",
            "preco_vencedor": r.get("valorVencedor") or r.get("precoVencedor") or 0,
        })

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

    client = get_gemini_client()
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.3,
        max_output_tokens=8000,
    )
    for chunk in client.models.generate_content_stream(
        model=_get_model_name(),
        contents=user_prompt,
        config=config,
    ):
        if chunk.text:
            yield chunk.text


def analyze_oportunidade(edital: dict, historico: list) -> Generator[str, None, None]:
    """
    Analisa um edital futuro comparando com o histórico de preços similares.
    Ideal para balizamento e decisão de participar ou não.

    Args:
        edital: Dict com dados do edital/compra aberta
        historico: Lista de itens históricos similares (via match exato ou semântico)
    """
    edital_summary = {
        "objeto": edital.get("objetoCompra") or edital.get("objetoContratacao") or "",
        "orgao": edital.get("nomeUnidadeOrgao") or edital.get("nomeOrgao") or "",
        "uf": edital.get("uf") or edital.get("ufNome") or "",
        "valor_estimado": edital.get("valorTotalEstimado") or 0,
        "data_encerramento": str(edital.get("dataEncerramentoProposta") or ""),
        "modalidade": edital.get("modalidadeNome") or "",
    }

    historico_summary = []
    for h in historico[:50]:   #LIMITAÇÃO DO HISTÓRICO DE OPORTUNIDADES
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

    client = get_gemini_client()
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.3,
        max_output_tokens=8000,
    )
    for chunk in client.models.generate_content_stream(
        model=_get_model_name(),
        contents=user_prompt,
        config=config,
    ):
        if chunk.text:
            yield chunk.text
