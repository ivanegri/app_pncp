# Migração da Tabela Resultados para BigQuery

Este documento descreve o processo completo de população e migração da tabela `resultados` para o BigQuery.

## 📊 Visão Geral

- **Total de itens com resultados**: ~4,4 milhões
- **Estratégia**: Popular PostgreSQL primeiro, depois migrar para BigQuery
- **Benefício**: Usuários Full terão acesso instantâneo aos dados de fornecedores e valores vencedores

## 🚀 Passo a Passo

### 1. Popular a Tabela Resultados (PostgreSQL)

O script otimizado processa em lotes com:
- ✅ Processamento paralelo (5 threads)
- ✅ Checkpoint automático (retoma de onde parou)
- ✅ Rate limiting (100ms entre requisições)
- ✅ Tratamento de erros

**Executar:**
```bash
# Em background (recomendado)
nohup python populate_resultados_optimized.py > populate_optimized.log 2>&1 &

# Acompanhar progresso
tail -f populate_optimized.log

# Ver checkpoint atual
cat populate_checkpoint.json
```

**Tempo estimado**: 
- Com 5 threads e 100ms de delay: ~24-48 horas para 4,4 milhões de itens
- O script pode ser interrompido e retomado a qualquer momento

**Verificar progresso:**
```bash
python -c "from app import create_app; from app.models import db, Base; app = create_app(); app.app_context().push(); Base.prepare(db.engine, reflect=True); Resultados = Base.classes.resultados; print(f'Total inserido: {db.session.query(Resultados).count():,}')"
```

### 2. Migrar para BigQuery

Após popular a tabela no PostgreSQL:

```bash
python migrate_resultados_to_bigquery.py
```

**O que faz:**
- ✅ Cria a tabela `resultados` no BigQuery
- ✅ Migra dados em lotes de 10.000 registros
- ✅ Remove timezone de timestamps automaticamente
- ✅ Mostra progresso em tempo real

**Tempo estimado**: ~30-60 minutos para 4,4 milhões de registros

### 3. Verificar Migração

**No BigQuery:**
```sql
SELECT COUNT(*) as total 
FROM `pncp-466018.pncp_data.resultados`;

-- Testar JOIN
SELECT 
    i.descricao,
    r.nomeRazaoSocialFornecedor as fornecedor,
    r.valorUnitarioHomologado as valorVencedor
FROM `pncp-466018.pncp_data.itens` i
LEFT JOIN `pncp-466018.pncp_data.resultados` r
    ON i.parent_numeroControlePNCPAta = r.numeroControlePNCPCompra
    AND i.numeroItem = r.numeroItem
WHERE SEARCH(i.descricao, 'curativo')
LIMIT 10;
```

## 📁 Arquivos Criados

1. **`populate_resultados_optimized.py`** - Script otimizado de população
2. **`migrate_resultados_to_bigquery.py`** - Script de migração para BigQuery
3. **`populate_checkpoint.json`** - Checkpoint automático (criado durante execução)
4. **`populate_optimized.log`** - Log de execução

## 🔧 Funcionalidades Implementadas

### Exportação Excel (Usuários Full)
- ✅ JOIN automático com tabela `resultados` no BigQuery
- ✅ Colunas: descricao, valorUnitarioEstimado, quantidade, unidadeMedida, situacaoCompraItemNome, dataAtualizacao, orgaoNome, **fornecedor**, **valorVencedor**

### Exportação Excel (Usuários Free/Starter)
- ✅ JOIN automático com tabela `resultados` no PostgreSQL (se existir)
- ✅ Mesmas colunas, com fallback gracioso se tabela não existir

## ⚡ Otimizações

### Script de População
- **Paralelo**: 5 threads simultâneas
- **Checkpoint**: Salva progresso a cada lote
- **Rate Limiting**: 100ms entre requisições (evita sobrecarga na API)
- **Batch Size**: 100 itens por lote

### Migração BigQuery
- **Batch Size**: 10.000 registros por lote
- **Streaming**: Usa pandas + BigQuery client para upload eficiente
- **Append Mode**: Permite executar múltiplas vezes sem duplicar

## 🐛 Troubleshooting

### Script travou
```bash
# Verificar se está rodando
ps aux | grep populate_resultados

# Matar processo se necessário
kill <PID>

# Retomar (usa checkpoint automaticamente)
python populate_resultados_optimized.py
```

### Erro de conexão com API
- O script trata erros 404 (sem resultados) automaticamente
- Outros erros são logados e o item é pulado
- Checkpoint permite retomar sem perder progresso

### Verificar integridade
```sql
-- PostgreSQL
SELECT COUNT(*) FROM resultados;

-- BigQuery
SELECT COUNT(*) FROM `pncp-466018.pncp_data.resultados`;
```

## 📈 Monitoramento

### Durante População
```bash
# Ver últimas 50 linhas do log
tail -50 populate_optimized.log

# Ver checkpoint
cat populate_checkpoint.json

# Contar registros inseridos
python -c "from app import create_app; from app.models import db, Base; app = create_app(); app.app_context().push(); Base.prepare(db.engine, reflect=True); Resultados = Base.classes.resultados; print(f'{db.session.query(Resultados).count():,}')"
```

### Durante Migração
- O script mostra progresso em tempo real
- Percentual de conclusão é exibido a cada lote

## 🎯 Próximos Passos (Opcional)

1. **Criar índices no BigQuery** para otimizar JOINs
2. **Agendar atualização periódica** dos resultados
3. **Implementar cache** para queries frequentes
4. **Dashboard de monitoramento** do processo de população

## ✅ Checklist de Execução

- [ ] Executar `populate_resultados_optimized.py`
- [ ] Aguardar conclusão (verificar log e checkpoint)
- [ ] Executar `migrate_resultados_to_bigquery.py`
- [ ] Verificar contagem no BigQuery
- [ ] Testar exportação Excel como usuário Full
- [ ] Verificar dados de fornecedor e valorVencedor no Excel

## 💡 Dicas

- **Não interrompa** a migração para BigQuery (é rápida)
- **Pode interromper** a população PostgreSQL (usa checkpoint)
- **Execute em horários de baixo uso** da API PNCP (madrugada)
- **Monitore o espaço em disco** do PostgreSQL durante população
