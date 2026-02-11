-- Tabela de resultados (fornecedores e valores vencedores)
CREATE TABLE IF NOT EXISTS resultados (
    id SERIAL PRIMARY KEY,
    numeroControlePNCPCompra VARCHAR(100),
    numeroItem INTEGER,
    sequencialResultado INTEGER,
    niFornecedor VARCHAR(20),
    nomeRazaoSocialFornecedor TEXT,
    tipoPessoa VARCHAR(10),
    porteFornecedorId INTEGER,
    porteFornecedorNome VARCHAR(50),
    valorUnitarioHomologado NUMERIC(15, 2),
    quantidadeHomologada NUMERIC(15, 2),
    valorTotalHomologado NUMERIC(15, 2),
    percentualDesconto NUMERIC(5, 2),
    situacaoCompraItemResultadoId INTEGER,
    situacaoCompraItemResultadoNome VARCHAR(50),
    dataResultado DATE,
    dataInclusao TIMESTAMP,
    dataAtualizacao TIMESTAMP,
    ordemClassificacaoSrp INTEGER,
    indicadorSubcontratacao BOOLEAN,
    aplicacaoMargemPreferencia BOOLEAN,
    aplicacaoBeneficioMeEpp BOOLEAN,
    aplicacaoCriterioDesempate BOOLEAN,
    motivoCancelamento TEXT,
    dataCancelamento TIMESTAMP,
    codigoPais VARCHAR(10),
    paisOrigemProdutoServico VARCHAR(100),
    naturezaJuridicaId INTEGER,
    naturezaJuridicaNome VARCHAR(100),
    amparoLegalMargemPreferencia TEXT,
    amparoLegalCriterioDesempate TEXT,
    moedaEstrangeira VARCHAR(10),
    valorNominalMoedaEstrangeira NUMERIC(15, 2),
    dataCotacaoMoedaEstrangeira DATE,
    timezoneCotacaoMoedaEstrangeira VARCHAR(50),
    
    -- Indexes para performance
    CONSTRAINT unique_resultado UNIQUE (numeroControlePNCPCompra, numeroItem, sequencialResultado)
);

-- Índices para melhorar performance de buscas
CREATE INDEX IF NOT EXISTS idx_resultados_numero_controle ON resultados(numeroControlePNCPCompra);
CREATE INDEX IF NOT EXISTS idx_resultados_numero_item ON resultados(numeroItem);
CREATE INDEX IF NOT EXISTS idx_resultados_fornecedor ON resultados(niFornecedor);
CREATE INDEX IF NOT EXISTS idx_resultados_data ON resultados(dataResultado);
