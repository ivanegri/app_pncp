"""
Script otimizado para popular a tabela resultados em lotes
Com suporte a retomada e processamento paralelo
"""
import os
import sys
import requests
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import Config

DATABASE_URL = Config.SQLALCHEMY_DATABASE_URI
engine = create_engine(DATABASE_URL)

# Configurações
BATCH_SIZE = 100
MAX_WORKERS = 5  # Número de threads paralelas
RATE_LIMIT_DELAY = 0.1  # Delay entre requisições (100ms)
CHECKPOINT_FILE = 'populate_checkpoint.json'

def load_checkpoint():
    """Carrega o checkpoint do último processamento"""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    return {'last_processed_id': 0, 'total_inserted': 0}

def save_checkpoint(last_id, total_inserted):
    """Salva o checkpoint atual"""
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump({
            'last_processed_id': last_id,
            'total_inserted': total_inserted,
            'timestamp': datetime.now().isoformat()
        }, f)

def get_resultados_from_api(cnpj, ano, sequencial, numero_item):
    """Busca resultados de um item específico na API PNCP"""
    url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numero_item}/resultados"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return []  # Sem resultados
        else:
            return None  # Erro - tentar novamente
    except Exception as e:
        return None  # Erro - tentar novamente

def parse_numero_controle(numero_controle):
    """Extrai CNPJ, ano e sequencial do numeroControlePNCPCompra"""
    try:
        parts = numero_controle.split('/')
        if len(parts) != 2:
            return None, None, None
            
        ano_part = parts[1]
        ano = ano_part.split('-')[0] if '-' in ano_part else ano_part
        
        before_slash = parts[0]
        dash_parts = before_slash.split('-')
        
        if len(dash_parts) < 3:
            return None, None, None
        
        cnpj = dash_parts[0]
        sequencial = dash_parts[2]
        
        return cnpj, ano, sequencial
    except Exception as e:
        return None, None, None

def process_item(item_data):
    """Processa um único item e retorna os resultados"""
    item_id, parent_cnpj, numero_controle, numero_item = item_data
    
    cnpj, ano, sequencial = parse_numero_controle(numero_controle)
    if not cnpj or not ano or not sequencial:
        return item_id, []
    
    time.sleep(RATE_LIMIT_DELAY)  # Rate limiting
    resultados = get_resultados_from_api(cnpj, ano, sequencial, numero_item)
    
    if resultados is None:
        return item_id, None  # Erro - tentar novamente
    
    return item_id, resultados

def insert_resultados_batch(resultados_list):
    """Insere um lote de resultados no banco"""
    if not resultados_list:
        return 0
    
    inserted = 0
    with engine.connect() as conn:
        for numero_controle, numero_item, resultado in resultados_list:
            try:
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
                    'dataResultado': resultado.get('dataResultado'),
                    'dataInclusao': resultado.get('dataInclusao'),
                    'dataAtualizacao': resultado.get('dataAtualizacao'),
                    'ordemClassificacaoSrp': resultado.get('ordemClassificacaoSrp'),
                    'indicadorSubcontratacao': resultado.get('indicadorSubcontratacao'),
                    'aplicacaoMargemPreferencia': resultado.get('aplicacaoMargemPreferencia'),
                    'aplicacaoBeneficioMeEpp': resultado.get('aplicacaoBeneficioMeEpp'),
                    'aplicacaoCriterioDesempate': resultado.get('aplicacaoCriterioDesempate'),
                    'motivoCancelamento': resultado.get('motivoCancelamento'),
                    'dataCancelamento': resultado.get('dataCancelamento'),
                    'codigoPais': resultado.get('codigoPais'),
                    'paisOrigemProdutoServico': resultado.get('paisOrigemProdutoServico'),
                    'naturezaJuridicaId': resultado.get('naturezaJuridicaId'),
                    'naturezaJuridicaNome': resultado.get('naturezaJuridicaNome'),
                    'amparoLegalMargemPreferencia': resultado.get('amparoLegalMargemPreferencia'),
                    'amparoLegalCriterioDesempate': resultado.get('amparoLegalCriterioDesempate'),
                    'moedaEstrangeira': resultado.get('moedaEstrangeira'),
                    'valorNominalMoedaEstrangeira': resultado.get('valorNominalMoedaEstrangeira'),
                    'dataCotacaoMoedaEstrangeira': resultado.get('dataCotacaoMoedaEstrangeira'),
                    'timezoneCotacaoMoedaEstrangeira': resultado.get('timezoneCotacaoMoedaEstrangeira')
                })
                conn.commit()
                inserted += 1
            except Exception as e:
                print(f"Erro ao inserir resultado: {e}")
                continue
    
    return inserted

def populate_all_resultados():
    """Popula todos os resultados em lotes com processamento paralelo"""
    checkpoint = load_checkpoint()
    last_id = checkpoint['last_processed_id']
    total_inserted = checkpoint['total_inserted']
    
    print(f"Iniciando população a partir do ID {last_id}")
    print(f"Total já inserido: {total_inserted}")
    
    while True:
        # Buscar próximo lote
        query = text("""
            SELECT DISTINCT 
                i.id,
                i."parent_cnpj",
                i."parent_numeroControlePNCPAta" as numeroControlePNCPCompra,
                i."numeroItem"
            FROM itens i
            WHERE i."temResultado" = TRUE
            AND i.id > :last_id
            ORDER BY i.id
            LIMIT :batch_size
        """)
        
        with engine.connect() as conn:
            result = conn.execute(query, {"last_id": last_id, "batch_size": BATCH_SIZE})
            batch = result.fetchall()
        
        if not batch:
            print("✅ Todos os itens foram processados!")
            break
        
        print(f"\nProcessando lote de {len(batch)} itens (ID {batch[0][0]} a {batch[-1][0]})...")
        
        # Processar em paralelo
        resultados_to_insert = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_item, item): item for item in batch}
            
            for future in as_completed(futures):
                item_id, resultados = future.result()
                
                if resultados is not None and resultados:
                    item_data = futures[future]
                    numero_controle = item_data[2]
                    numero_item = item_data[3]
                    
                    for resultado in resultados:
                        resultados_to_insert.append((numero_controle, numero_item, resultado))
        
        # Inserir lote
        inserted_count = insert_resultados_batch(resultados_to_insert)
        total_inserted += inserted_count
        last_id = batch[-1][0]
        
        # Salvar checkpoint
        save_checkpoint(last_id, total_inserted)
        
        print(f"✅ Lote processado: {inserted_count} resultados inseridos")
        print(f"📊 Total acumulado: {total_inserted} resultados")
        print(f"🔖 Checkpoint salvo: último ID = {last_id}")
    
    print(f"\n🎉 Finalizado! Total de resultados inseridos: {total_inserted}")

if __name__ == "__main__":
    populate_all_resultados()
