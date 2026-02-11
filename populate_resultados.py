"""
Script para popular a tabela resultados com dados da API PNCP
"""
import os
import sys
import requests
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import time

# Adicionar o diretório do app ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import Config

# Configuração do banco de dados
DATABASE_URL = Config.SQLALCHEMY_DATABASE_URI
engine = create_engine(DATABASE_URL)

def get_resultados_from_api(cnpj, ano, sequencial, numero_item):
    """Busca resultados de um item específico na API PNCP"""
    url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numero_item}/resultados"
    print(f"Buscando: {url}")  # Debug
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Erro {response.status_code} para item {numero_item}: {url}")
            return []
    except Exception as e:
        print(f"Erro ao buscar resultados para item {numero_item}: {e}")
        return []

def parse_numero_controle(numero_controle):
    """Extrai CNPJ, ano e sequencial do numeroControlePNCPCompra"""
    # Formato esperado: 10091502000129-1-000007/2025-000001
    # Outro formato: 12075748000132-1-000010/2023
    try:
        # Split por '/' para separar ano
        parts = numero_controle.split('/')
        if len(parts) != 2:
            return None, None, None
            
        ano_part = parts[1]  # '2025-000001' ou '2023'
        # Extrair apenas o ano (primeiros 4 dígitos)
        ano = ano_part.split('-')[0] if '-' in ano_part else ano_part
        
        # Split da primeira parte por '-'
        before_slash = parts[0]  # '10091502000129-1-000007'
        dash_parts = before_slash.split('-')
        
        if len(dash_parts) < 3:
            return None, None, None
        
        cnpj = dash_parts[0]  # '10091502000129'
        sequencial = dash_parts[2]  # '000007'
        
        print(f"Parsed: CNPJ={cnpj}, Ano={ano}, Seq={sequencial}")  # Debug
        return cnpj, ano, sequencial
    except Exception as e:
        print(f"Erro ao parsear '{numero_controle}': {e}")
        return None, None, None

def populate_resultados_from_itens(limit=1000, batch_size=100):
    """
    Popula a tabela resultados buscando itens que têm temResultado=True
    """
    print(f"Buscando itens com resultados (limit={limit})...")
    
    # Buscar itens que têm resultados
    query = text("""
        SELECT DISTINCT 
            "parent_cnpj",
            "parent_numeroControlePNCPAta" as "numeroControlePNCPCompra",
            "numeroItem"
        FROM itens 
        WHERE "temResultado" = TRUE
        LIMIT :limit
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, {"limit": limit})
        itens_com_resultado = result.fetchall()
    
    print(f"Encontrados {len(itens_com_resultado)} itens com resultados")
    
    total_resultados = 0
    total_processados = 0
    
    for item in itens_com_resultado:
        parent_cnpj, numero_controle, numero_item = item
        
        # Parse do número de controle
        cnpj, ano, sequencial = parse_numero_controle(numero_controle)
        
        if not cnpj or not ano or not sequencial:
            print(f"Não foi possível parsear: {numero_controle}")
            continue
        
        # Buscar resultados da API
        resultados = get_resultados_from_api(cnpj, ano, sequencial, numero_item)
        
        if resultados:
            # Preparar dados para inserção
            for resultado in resultados:
                try:
                    # Converter datas
                    data_resultado = resultado.get('dataResultado')
                    data_inclusao = resultado.get('dataInclusao')
                    data_atualizacao = resultado.get('dataAtualizacao')
                    data_cancelamento = resultado.get('dataCancelamento')
                    data_cotacao = resultado.get('dataCotacaoMoedaEstrangeira')
                    
                    insert_query = text("""
                        INSERT INTO resultados (
                            numeroControlePNCPCompra, numeroItem, sequencialResultado,
                            niFornecedor, nomeRazaoSocialFornecedor, tipoPessoa,
                            porteFornecedorId, porteFornecedorNome,
                            valorUnitarioHomologado, quantidadeHomologada, valorTotalHomologado,
                            percentualDesconto, situacaoCompraItemResultadoId, situacaoCompraItemResultadoNome,
                            dataResultado, dataInclusao, dataAtualizacao,
                            ordemClassificacaoSrp, indicadorSubcontratacao,
                            aplicacaoMargemPreferencia, aplicacaoBeneficioMeEpp, aplicacaoCriterioDesempate,
                            motivoCancelamento, dataCancelamento, codigoPais, paisOrigemProdutoServico,
                            naturezaJuridicaId, naturezaJuridicaNome,
                            amparoLegalMargemPreferencia, amparoLegalCriterioDesempate,
                            moedaEstrangeira, valorNominalMoedaEstrangeira, dataCotacaoMoedaEstrangeira,
                            timezoneCotacaoMoedaEstrangeira
                        ) VALUES (
                            :numeroControlePNCPCompra, :numeroItem, :sequencialResultado,
                            :niFornecedor, :nomeRazaoSocialFornecedor, :tipoPessoa,
                            :porteFornecedorId, :porteFornecedorNome,
                            :valorUnitarioHomologado, :quantidadeHomologada, :valorTotalHomologado,
                            :percentualDesconto, :situacaoCompraItemResultadoId, :situacaoCompraItemResultadoNome,
                            :dataResultado, :dataInclusao, :dataAtualizacao,
                            :ordemClassificacaoSrp, :indicadorSubcontratacao,
                            :aplicacaoMargemPreferencia, :aplicacaoBeneficioMeEpp, :aplicacaoCriterioDesempate,
                            :motivoCancelamento, :dataCancelamento, :codigoPais, :paisOrigemProdutoServico,
                            :naturezaJuridicaId, :naturezaJuridicaNome,
                            :amparoLegalMargemPreferencia, :amparoLegalCriterioDesempate,
                            :moedaEstrangeira, :valorNominalMoedaEstrangeira, :dataCotacaoMoedaEstrangeira,
                            :timezoneCotacaoMoedaEstrangeira
                        )
                        ON CONFLICT (numeroControlePNCPCompra, numeroItem, sequencialResultado) 
                        DO UPDATE SET
                            nomeRazaoSocialFornecedor = EXCLUDED.nomeRazaoSocialFornecedor,
                            valorUnitarioHomologado = EXCLUDED.valorUnitarioHomologado,
                            valorTotalHomologado = EXCLUDED.valorTotalHomologado,
                            dataAtualizacao = EXCLUDED.dataAtualizacao
                    """)
                    
                    with engine.connect() as conn:
                        conn.execute(insert_query, {
                            'numeroControlePNCPCompra': numero_controle,
                            'numeroItem': resultado.get('numeroItem'),
                            'sequencialResultado': resultado.get('sequencialResultado'),
                            'niFornecedor': resultado.get('niFornecedor'),
                            'nomeRazaoSocialFornecedor': resultado.get('nomeRazaoSocialFornecedor'),
                            'tipoPessoa': resultado.get('tipoPessoa'),
                            'porteFornecedorId': resultado.get('porteFornecedorId'),
                            'porteFornecedorNome': resultado.get('porteFornecedorNome'),
                            'valorUnitarioHomologado': resultado.get('valorUnitarioHomologado'),
                            'quantidadeHomologada': resultado.get('quantidadeHomologada'),
                            'valorTotalHomologado': resultado.get('valorTotalHomologado'),
                            'percentualDesconto': resultado.get('percentualDesconto'),
                            'situacaoCompraItemResultadoId': resultado.get('situacaoCompraItemResultadoId'),
                            'situacaoCompraItemResultadoNome': resultado.get('situacaoCompraItemResultadoNome'),
                            'dataResultado': data_resultado,
                            'dataInclusao': data_inclusao,
                            'dataAtualizacao': data_atualizacao,
                            'ordemClassificacaoSrp': resultado.get('ordemClassificacaoSrp'),
                            'indicadorSubcontratacao': resultado.get('indicadorSubcontratacao'),
                            'aplicacaoMargemPreferencia': resultado.get('aplicacaoMargemPreferencia'),
                            'aplicacaoBeneficioMeEpp': resultado.get('aplicacaoBeneficioMeEpp'),
                            'aplicacaoCriterioDesempate': resultado.get('aplicacaoCriterioDesempate'),
                            'motivoCancelamento': resultado.get('motivoCancelamento'),
                            'dataCancelamento': data_cancelamento,
                            'codigoPais': resultado.get('codigoPais'),
                            'paisOrigemProdutoServico': resultado.get('paisOrigemProdutoServico'),
                            'naturezaJuridicaId': resultado.get('naturezaJuridicaId'),
                            'naturezaJuridicaNome': resultado.get('naturezaJuridicaNome'),
                            'amparoLegalMargemPreferencia': resultado.get('amparoLegalMargemPreferencia'),
                            'amparoLegalCriterioDesempate': resultado.get('amparoLegalCriterioDesempate'),
                            'moedaEstrangeira': resultado.get('moedaEstrangeira'),
                            'valorNominalMoedaEstrangeira': resultado.get('valorNominalMoedaEstrangeira'),
                            'dataCotacaoMoedaEstrangeira': data_cotacao,
                            'timezoneCotacaoMoedaEstrangeira': resultado.get('timezoneCotacaoMoedaEstrangeira')
                        })
                        conn.commit()
                    
                    total_resultados += 1
                    
                except Exception as e:
                    print(f"Erro ao inserir resultado: {e}")
                    continue
        
        total_processados += 1
        
        if total_processados % 10 == 0:
            print(f"Processados {total_processados}/{len(itens_com_resultado)} itens, {total_resultados} resultados inseridos")
        
        # Rate limiting - evitar sobrecarga na API
        time.sleep(0.5)
    
    print(f"\n✅ Finalizado! Total de resultados inseridos: {total_resultados}")

if __name__ == "__main__":
    print("Criando tabela resultados...")
    with engine.connect() as conn:
        with open('create_resultados_table.sql', 'r') as f:
            sql = f.read()
            conn.execute(text(sql))
            conn.commit()
    
    print("Tabela criada com sucesso!")
    
    # Popula com os primeiros 1000 itens
    populate_resultados_from_itens(limit=1000)
