#!/bin/bash
# Script de monitoramento da população de resultados

echo "========================================="
echo "  MONITORAMENTO - População Resultados"
echo "========================================="
echo ""

# Verificar se o processo está rodando
PID=$(ps aux | grep populate_resultados_optimized | grep -v grep | awk '{print $2}')

if [ -z "$PID" ]; then
    echo "❌ Processo NÃO está rodando"
else
    echo "✅ Processo rodando (PID: $PID)"
    echo ""
    
    # Mostrar uso de CPU e memória
    echo "📊 Recursos:"
    ps aux | grep $PID | grep -v grep | awk '{printf "   CPU: %s%%  |  MEM: %s%%\n", $3, $4}'
fi

echo ""
echo "========================================="

# Mostrar checkpoint
if [ -f "populate_checkpoint.json" ]; then
    echo "📌 Checkpoint:"
    cat populate_checkpoint.json | python3 -m json.tool 2>/dev/null || cat populate_checkpoint.json
else
    echo "⚠️  Checkpoint ainda não criado"
fi

echo ""
echo "========================================="

# Contar registros no banco
echo "💾 Registros no PostgreSQL:"
python3 -c "
from app import create_app
from app.models import db, Base
import sys

try:
    app = create_app()
    with app.app_context():
        Base.prepare(db.engine, reflect=True)
        Resultados = Base.classes.resultados
        total = db.session.query(Resultados).count()
        print(f'   Total: {total:,} resultados')
except Exception as e:
    print(f'   Erro: {e}')
" 2>/dev/null || echo "   Erro ao consultar banco"

echo ""
echo "========================================="

# Mostrar últimas linhas do log
if [ -f "populate_optimized.log" ]; then
    echo "📝 Últimas linhas do log:"
    tail -10 populate_optimized.log | sed 's/^/   /'
else
    echo "⚠️  Log ainda não criado"
fi

echo ""
echo "========================================="
echo ""
echo "Comandos úteis:"
echo "  Ver log completo:  tail -f populate_optimized.log"
echo "  Parar processo:    kill $PID"
echo "  Retomar processo:  python populate_resultados_optimized.py"
echo ""
