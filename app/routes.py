from flask import Blueprint, jsonify, render_template, request
from .models import Base, db
from sqlalchemy import or_, text

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/search')
def search():
    query_term = request.args.get('q', '')
    search_type = request.args.get('type', 'itens')
    
    results = []
    
    if query_term:
        try:
            if search_type == 'itens':
                Itens = Base.classes.itens
                # Using ilike for case-insensitive search on 'descricao'
                # Limit to 50 results for performance
                db_results = db.session.query(Itens).filter(Itens.descricao.ilike(f'%{query_term}%')).limit(50).all()
                results = [{k: v for k, v in row.__dict__.items() if not k.startswith('_')} for row in db_results]
                
            elif search_type == 'atas':
                Atas = Base.classes.atas
                # Search by 'objeto' (assuming it exists in CSV header inspection result, 
                # looking back at headers: "objeto" was not explicitly listed in my brief check, 
                # but "descricao" or similar likely exists. 
                # Let's check headers again if needed, but 'objeto' is standard in PNCP.
                # Actually, in atas_full.csv head it showed: id, numeroControlePNCP, ...
                # Let's use generic approach or check schema if fails.
                # For now assuming 'objeto' or similar column. 
                # Wait, looking at header from step 19: "Agrupamento de itens de..." 
                # It has 'objetoCompra'? No.
                # Let's check columns for Atas using reflection or previous knowledge.
                # Inspecting 'atas' columns via python might be safer.
                pass 
                
            elif search_type == 'orgaos':
                Orgaos = Base.classes.orgaos
                # Search by 'razaoSocial' or 'nomeFantasia'
                db_results = db.session.query(Orgaos).filter(
                    or_(
                        Orgaos.razaoSocial.ilike(f'%{query_term}%'),
                        Orgaos.nomeFantasia.ilike(f'%{query_term}%')
                    )
                ).limit(50).all()
                results = [{k: v for k, v in row.__dict__.items() if not k.startswith('_')} for row in db_results]

        except Exception as e:
            print(f"Search error: {e}")
            return render_template('results.html', query=query_term, results=[], error=str(e))

    return render_template('results.html', results=results, query=query_term, type=search_type)

@main_bp.route('/dashboard')
def dashboard():
    query_term = request.args.get('q', '')
    if not query_term:
        return render_template('index.html') # Redirect to search if no query
    
    try:
        Itens = Base.classes.itens
        # Filter items by description
        # Ideally we would link to Orgaos table to get names, but automap relationships might need checking.
        # For now, let's just do single table stats or assume basic fields.
        
        items_query = db.session.query(Itens).filter(Itens.descricao.ilike(f'%{query_term}%'))
        total_items = items_query.count()
        
        if total_items == 0:
             return render_template('results.html', query=query_term, results=[], error="Sem dados para análise")

        # Basic Stats
        # We need to broadcast types correctly for math operations if they are strings in DB
        # Since we just used migration script, check models.
        # Actually our migration script relied on pandas to_sql, so types should be reasonably inferred (float/int).
        
        from sqlalchemy import func
        stats = items_query.with_entities(
            func.avg(Itens.valorUnitarioEstimado).label('avg_price'),
            func.min(Itens.valorUnitarioEstimado).label('min_price'),
            func.max(Itens.valorUnitarioEstimado).label('max_price'),
            func.sum(Itens.quantidade).label('total_qty')
        ).first()
        
        # Price Distribution (Histogram-like) using Python for simplicity on small-medium datasets filtered
        # Fetching all prices might be heavy if > 10k items. limit to 1000 for chart sample.
        prices = [r[0] for r in items_query.with_entities(Itens.valorUnitarioEstimado).limit(1000).all() if r[0] is not None]
        
        # Create buckets
        if prices:
            import numpy as np
            counts, bins = np.histogram(prices, bins=10)
            price_buckets_labels = [f"R$ {int(b)}" for b in bins[:-1]]
            price_buckets_values = counts.tolist()
        else:
            price_buckets_labels = []
            price_buckets_values = []
            
        # Top Orgaos (by qty) - This requires linking to Orgaos or using cnpj from item which is 'parent_cnpj' possibly?
        # In migration script step 19 output: 'parent_cnpj' column existed in itens csv.
        # Let's check Itens model attributes in a separate step if needed, but 'parent_cnpj' is likely the FK.
        # We can group by parent_cnpj.
        
        Orgaos = Base.classes.orgaos
        
        # Join Itens and Orgaos on parent_cnpj == cnpj
        top_orgaos_query = db.session.query(
            Orgaos.razaoSocial, 
            func.count(Itens.id).label('count')
        ).join(
            Orgaos, Itens.parent_cnpj == Orgaos.cnpj
        ).filter(
            Itens.descricao.ilike(f'%{query_term}%')
        ).group_by(
            Orgaos.razaoSocial
        ).order_by(
            text('count DESC')
        ).limit(5).all()
        
        top_orgaos_labels = [str(r[0])[:30] + '...' if len(str(r[0])) > 30 else str(r[0]) for r in top_orgaos_query]
        top_orgaos_values = [r[1] for r in top_orgaos_query]

        return render_template(
            'dashboard.html',
            query=query_term,
            total_items=total_items,
            avg_price=stats.avg_price or 0,
            min_price=stats.min_price or 0,
            max_price=stats.max_price or 0,
            total_quantity=int(stats.total_qty or 0),
            price_buckets_labels=price_buckets_labels,
            price_buckets_values=price_buckets_values,
            top_orgaos_labels=top_orgaos_labels,
            top_orgaos_values=top_orgaos_values
        )

    except Exception as e:
        print(f"Dashboard error: {e}")
        import traceback
        traceback.print_exc()
        return render_template('results.html', query=query_term, results=[], error="Erro ao gerar dashboard")

@main_bp.route('/item/<int:item_id>')
def item_details(item_id):
    try:
        Itens = Base.classes.itens
        Atas = Base.classes.atas
        Orgaos = Base.classes.orgaos
        
        # Get Item
        item = db.session.query(Itens).get(item_id)
        if not item:
            return render_template('results.html', query="", results=[], error="Item não encontrado")
            
        # Get Orgao
        orgao = None
        if item.parent_cnpj:
            orgao = db.session.query(Orgaos).filter_by(cnpj=item.parent_cnpj).first()
            
        # Get Ata
        ata = None
        if item.parent_numeroControlePNCPAta:
            # Note: script output showed 'numeroControlePNCPAta' in Atas columns. 
            # Itens has 'parent_numeroControlePNCPAta'.
            ata = db.session.query(Atas).filter_by(numeroControlePNCPAta=item.parent_numeroControlePNCPAta).first()
            
        return render_template('item.html', item=item, orgao=orgao, ata=ata)
            
    except Exception as e:
        print(f"Item detail error: {e}")
        return render_template('results.html', query="", results=[], error="Erro ao carregar detalhes do item")

    except Exception as e:
        print(f"Item detail error: {e}")
        return render_template('results.html', query="", results=[], error="Erro ao carregar detalhes do item")

@main_bp.route('/orgao/<path:cnpj>')
def orgao_details(cnpj):
    try:
        Orgaos = Base.classes.orgaos
        Atas = Base.classes.atas

        query_ata = request.args.get('q', '')
        vigencia_inicio = request.args.get('vigencia_inicio', '')
        vigencia_fim = request.args.get('vigencia_fim', '')
        
        # Determine the correct primary key or unique field. 
        # Cnpj is unique but 'id' is pk. Route parameter gives cnpj.
        orgao = db.session.query(Orgaos).filter_by(cnpj=cnpj).first()
        
        if not orgao:
             return render_template('results.html', query="", results=[], error="Órgão não encontrado")
             
        # Fetch Atas linked to this Orgao
        atas_query = db.session.query(Atas).filter_by(cnpjOrgao=cnpj)
        
        if query_ata:
            atas_query = atas_query.filter(Atas.objetoContratacao.ilike(f'%{query_ata}%'))
            
        if vigencia_inicio:
            atas_query = atas_query.filter(Atas.vigenciaInicio >= vigencia_inicio)
            
        if vigencia_fim:
            atas_query = atas_query.filter(Atas.vigenciaFim <= vigencia_fim)
            
        atas = atas_query.limit(100).all()
        
        return render_template('orgao.html', orgao=orgao, atas=atas, query_ata=query_ata, vigencia_inicio=vigencia_inicio, vigencia_fim=vigencia_fim)
        
    except Exception as e:
        print(f"Orgao detail error: {e}")
        return render_template('results.html', query="", results=[], error="Erro ao carregar detalhes do órgão")

@main_bp.route('/ata/<int:ata_id>/itens')
def ata_items(ata_id):
    try:
        Atas = Base.classes.atas
        Itens = Base.classes.itens
        
        ata = db.session.query(Atas).get(ata_id)
        if not ata:
             return render_template('results.html', query="", results=[], error="Ata não encontrada")
             
        # Fetch Items linked to this Ata via numeroControlePNCPAta
        # Itens table uses 'parent_numeroControlePNCPAta'
        items = db.session.query(Itens).filter_by(parent_numeroControlePNCPAta=ata.numeroControlePNCPAta).all()
        
        return render_template('ata_items.html', ata=ata, items=items)
        
    except Exception as e:
        print(f"Ata items error: {e}")
        return render_template('results.html', query="", results=[], error="Erro ao carregar itens da ata")

@main_bp.route('/api/status')
def status():
    return jsonify({
        "status": "online",
        "message": "API de Análise do Jupiter PNCP",
        "tables": list(Base.classes.keys())
    })

@main_bp.route('/old_api/atas')
def list_atas():
    # Access the reflected class
    try:
        Atas = Base.classes.atas
        # Query first 5 records
        results = db.session.query(Atas).limit(5).all()
        
        # Convert to dict (simple serialization)
        data = []
        for row in results:
            # Automap doesn't provide to_dict automatically, so we'll do a basic one
            # relying on __dict__ but filtering out internal state
            row_dict = {k: v for k, v in row.__dict__.items() if not k.startswith('_')}
            data.append(row_dict)
            
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main_bp.route('/old_api/orgaos')
def list_orgaos():
    try:
        Orgaos = Base.classes.orgaos
        results = db.session.query(Orgaos).limit(5).all()
        data = [{k: v for k, v in row.__dict__.items() if not k.startswith('_')} for row in results]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main_bp.route('/old_api/itens')
def list_itens():
    try:
        Itens = Base.classes.itens
        results = db.session.query(Itens).limit(5).all()
        data = [{k: v for k, v in row.__dict__.items() if not k.startswith('_')} for row in results]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
