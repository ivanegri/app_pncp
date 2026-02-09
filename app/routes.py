from flask import Blueprint, jsonify, render_template, request, flash, redirect, url_for, abort
from .models import Base, db, User
from .utils_tiers import check_tier_access, requires_tier
from sqlalchemy import or_, text
from flask_login import login_required, current_user

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/search')
@login_required
def search():
    query_term = request.args.get('q', '')
    search_type = request.args.get('type', 'itens')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    is_partial = request.args.get('partial', 'false') == 'true'
    
    results = []
    has_next = False
    
    if query_term:
        try:
            offset = (page - 1) * per_page
            
            if search_type == 'itens':
                Itens = Base.classes.itens
                # FTS Search against 'busca_descricao_idx'
                fts_condition = text("busca_descricao_idx @@ websearch_to_tsquery('portuguese', :q)")
                query = db.session.query(Itens).filter(fts_condition)
                
                # Use params safely
                count_query = query.params(q=query_term)
                total_results = count_query.count()
                
                db_results = query.params(q=query_term).offset(offset).limit(per_page + 1).all()
                
                if len(db_results) > per_page:
                    has_next = True
                    db_results = db_results[:-1]
                    
                results = [{k: v for k, v in row.__dict__.items() if not k.startswith('_')} for row in db_results]
                
            elif search_type == 'atas':
                Atas = Base.classes.atas
                # FTS Search against 'busca_objeto_idx'
                fts_condition = text("busca_objeto_idx @@ websearch_to_tsquery('portuguese', :q)")
                query = db.session.query(Atas).filter(fts_condition)
                
                count_query = query.params(q=query_term)
                total_results = count_query.count()
                
                db_results = query.params(q=query_term).offset(offset).limit(per_page + 1).all()
                
                if len(db_results) > per_page:
                    has_next = True
                    db_results = db_results[:-1]

                results = [{k: v for k, v in row.__dict__.items() if not k.startswith('_')} for row in db_results]
                
            elif search_type == 'orgaos':
                Orgaos = Base.classes.orgaos
                # FTS Search against 'busca_orgao_idx'
                fts_condition = text("busca_orgao_idx @@ websearch_to_tsquery('portuguese', :q)")
                query = db.session.query(Orgaos).filter(fts_condition)
                
                count_query = query.params(q=query_term)
                total_results = count_query.count()
                
                db_results = query.params(q=query_term).offset(offset).limit(per_page + 1).all()
                
                if len(db_results) > per_page:
                    has_next = True
                    db_results = db_results[:-1]
                
                results = [{k: v for k, v in row.__dict__.items() if not k.startswith('_')} for row in db_results]

        except Exception as e:
            print(f"Search error: {e}")
            if is_partial:
                return jsonify({'error': str(e)}), 500
            return render_template('results.html', query=query_term, results=[], error=str(e))

    if is_partial:
        return render_template('partials/result_cards.html', results=results, type=search_type)

    limit_applied = False
    if not check_tier_access('unlimited_search'):
        # Free tier limit
        if len(results) > 5:
            results = results[:5]
            limit_applied = True
        has_next = False # Hide pagination for limited results
        # Flash removed to prevent spam on login screen

    return render_template('results.html', results=results, query=query_term, type=search_type, page=page, has_next=has_next, total_results=total_results if 'total_results' in locals() else 0, limit_applied=limit_applied)

@main_bp.route('/pricing')
@login_required
def pricing():
    return render_template('pricing.html')

@main_bp.route('/select_plan/<tier>')
@login_required
def select_plan(tier):
    if tier not in ['free', 'starter', 'full']:
        flash('Plano inválido.', 'danger')
        return redirect(url_for('main.pricing'))
    
    current_user.tier = tier
    # Logic to handle payment would go here
    try:
        from .models import db
        db.session.commit()
        flash(f'Plano {tier.upper()} selecionado com sucesso! Bem-vindo.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Erro ao atualizar plano.', 'danger')
        
    return redirect(url_for('main.dashboard'))

@main_bp.route('/market_analysis_dashboard')
@login_required
@requires_tier('full')
def market_analysis_dashboard():
    query_term = request.args.get('q', '')
    if not query_term:
        return render_template('index.html') # Redirect to search if no query
    
    try:
        Itens = Base.classes.itens
        # Filter items by description
        items_query_base = db.session.query(Itens).filter(Itens.descricao.ilike(f'%{query_term}%'))
        total_items_global = items_query_base.count() 
        
        if total_items_global == 0:
             return render_template('results.html', query=query_term, results=[], error="Sem dados para análise")

        # 1. Get Units Distribution
        from sqlalchemy import func, desc
        units_query = db.session.query(
            Itens.unidadeMedida,
            func.count(Itens.id).label('count')
        ).filter(
            Itens.descricao.ilike(f'%{query_term}%')
        ).group_by(
            Itens.unidadeMedida
        ).order_by(
            desc('count')
        ).all()

        units = [{'name': u[0], 'count': u[1]} for u in units_query if u[0]]
        
        # 2. Determine Selected Unit
        selected_unit = request.args.get('unit')
        
        # Default to first unit if none selected, or if selected is invalid (though we won't validate strictly for now)
        if not selected_unit and units:
            selected_unit = units[0]['name']

        # 3. Filter for Stats
        if selected_unit:
            # Case-insensitive comparison just in case, though usually exact match from DB group by is fine
            items_query = items_query_base.filter(Itens.unidadeMedida == selected_unit)
        else:
            items_query = items_query_base 

        total_items_filtered = items_query.count()

        # Basic Stats
        stats = items_query.with_entities(
            func.avg(Itens.valorUnitarioEstimado).label('avg_price'),
            func.min(Itens.valorUnitarioEstimado).label('min_price'),
            func.max(Itens.valorUnitarioEstimado).label('max_price'),
            func.sum(Itens.quantidade).label('total_qty')
        ).first()
        
        # Price Distribution (Histogram-like) using Python
        # OPTIMIZATION: Use a sample for histogram if dataset is large to improve performance
        
        # Check if we have too many items to fetch all prices
        if total_items_filtered > 10000:
             # Fetch a random sample of prices
             # PostgreSQL RANDOM() is fast enough for sampling 10k out of millions
             prices_query = items_query.with_entities(Itens.valorUnitarioEstimado).order_by(func.random()).limit(10000).all()
        else:
             prices_query = items_query.with_entities(Itens.valorUnitarioEstimado).all()

        prices = [r[0] for r in prices_query if r[0] is not None]
        
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
        # Join Itens and Orgaos on parent_cnpj == cnpj
        # Join Itens and Orgaos on parent_cnpj == cnpj
        top_orgaos_query = db.session.query(
            Orgaos.razaoSocial,
            Orgaos.cnpj,
            func.count(Itens.id).label('count'),
            func.sum(Itens.quantidade).label('total_qty'),
            func.avg(Itens.valorUnitarioEstimado).label('avg_price')
        ).join(
            Orgaos, Itens.parent_cnpj == Orgaos.cnpj
        ).filter(
            Itens.descricao.ilike(f'%{query_term}%')
        ).filter(
            Itens.unidadeMedida == selected_unit if selected_unit else text('1=1')
        ).group_by(
            Orgaos.razaoSocial,
            Orgaos.cnpj
        ).order_by(
            desc('count')
        ).limit(20).all()
        
        # Pass full objects to template for table
        top_orgaos = [{
            'name': r[0], 
            'cnpj': r[1], 
            'count': r[2], 
            'total_qty': int(r[3] or 0), 
            'avg_price': float(r[4] or 0)
        } for r in top_orgaos_query]
        
        # Keep labels/values for chart if we still wanted it, but user asked for table. 
        # We can remove chart data prep if we are fully replacing.
        # But let's leave it compatible if template needs it (unlikely).
        # We'll just pass 'top_orgaos' list.

        return render_template(
            'dashboard.html',
            query=query_term,
            total_items=total_items_filtered,
            total_items_global=total_items_global,
            units=units,
            selected_unit=selected_unit,
            avg_price=stats.avg_price or 0,
            min_price=stats.min_price or 0,
            max_price=stats.max_price or 0,
            total_quantity=int(stats.total_qty or 0),
            price_buckets_labels=price_buckets_labels,
            price_buckets_values=price_buckets_values,
            top_orgaos=top_orgaos
        )

    except Exception as e:
        print(f"Dashboard error: {e}")
        import traceback
        traceback.print_exc()
        return render_template('results.html', query=query_term, results=[], error="Erro ao gerar dashboard")

@main_bp.route('/dashboard')
@login_required
def dashboard():
    query_term = request.args.get('q', '')
    if not query_term:
        return render_template('index.html') # Redirect to search if no query
    
    try:
        Itens = Base.classes.itens
        # Filter items by description
        items_query_base = db.session.query(Itens).filter(Itens.descricao.ilike(f'%{query_term}%'))
        total_items_global = items_query_base.count() 
        
        if total_items_global == 0:
             return render_template('results.html', query=query_term, results=[], error="Sem dados para análise")

        # 1. Get Units Distribution
        from sqlalchemy import func, desc
        units_query = db.session.query(
            Itens.unidadeMedida,
            func.count(Itens.id).label('count')
        ).filter(
            Itens.descricao.ilike(f'%{query_term}%')
        ).group_by(
            Itens.unidadeMedida
        ).order_by(
            desc('count')
        ).all()

        units = [{'name': u[0], 'count': u[1]} for u in units_query if u[0]]
        
        # 2. Determine Selected Unit
        selected_unit = request.args.get('unit')
        
        # Default to first unit if none selected, or if selected is invalid (though we won't validate strictly for now)
        if not selected_unit and units:
            selected_unit = units[0]['name']

        # 3. Filter for Stats
        if selected_unit:
            # Case-insensitive comparison just in case, though usually exact match from DB group by is fine
            items_query = items_query_base.filter(Itens.unidadeMedida == selected_unit)
        else:
            items_query = items_query_base 

        total_items_filtered = items_query.count()

        # Basic Stats
        stats = items_query.with_entities(
            func.avg(Itens.valorUnitarioEstimado).label('avg_price'),
            func.min(Itens.valorUnitarioEstimado).label('min_price'),
            func.max(Itens.valorUnitarioEstimado).label('max_price'),
            func.sum(Itens.quantidade).label('total_qty')
        ).first()
        
        # Price Distribution (Histogram-like) using Python
        # OPTIMIZATION: Use a sample for histogram if dataset is large to improve performance
        
        # Check if we have too many items to fetch all prices
        if total_items_filtered > 10000:
             # Fetch a random sample of prices
             # PostgreSQL RANDOM() is fast enough for sampling 10k out of millions
             prices_query = items_query.with_entities(Itens.valorUnitarioEstimado).order_by(func.random()).limit(10000).all()
        else:
             prices_query = items_query.with_entities(Itens.valorUnitarioEstimado).all()
             
        prices = [r[0] for r in prices_query if r[0] is not None]
        
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
        # Join Itens and Orgaos on parent_cnpj == cnpj
        # Join Itens and Orgaos on parent_cnpj == cnpj
        top_orgaos_query = db.session.query(
            Orgaos.razaoSocial,
            Orgaos.cnpj,
            func.count(Itens.id).label('count'),
            func.sum(Itens.quantidade).label('total_qty'),
            func.avg(Itens.valorUnitarioEstimado).label('avg_price')
        ).join(
            Orgaos, Itens.parent_cnpj == Orgaos.cnpj
        ).filter(
            Itens.descricao.ilike(f'%{query_term}%')
        ).filter(
            Itens.unidadeMedida == selected_unit if selected_unit else text('1=1')
        ).group_by(
            Orgaos.razaoSocial,
            Orgaos.cnpj
        ).order_by(
            desc('count')
        ).limit(20).all()
        
        # Pass full objects to template for table
        top_orgaos = [{
            'name': r[0], 
            'cnpj': r[1], 
            'count': r[2], 
            'total_qty': int(r[3] or 0), 
            'avg_price': float(r[4] or 0)
        } for r in top_orgaos_query]
        
        # Keep labels/values for chart if we still wanted it, but user asked for table. 
        # We can remove chart data prep if we are fully replacing.
        # But let's leave it compatible if template needs it (unlikely).
        # We'll just pass 'top_orgaos' list.

        return render_template(
            'dashboard.html',
            query=query_term,
            total_items=total_items_filtered,
            total_items_global=total_items_global,
            units=units,
            selected_unit=selected_unit,
            avg_price=stats.avg_price or 0,
            min_price=stats.min_price or 0,
            max_price=stats.max_price or 0,
            total_quantity=int(stats.total_qty or 0),
            price_buckets_labels=price_buckets_labels,
            price_buckets_values=price_buckets_values,
            top_orgaos=top_orgaos
        )

    except Exception as e:
        print(f"Dashboard error: {e}")
        import traceback
        traceback.print_exc()
        return render_template('results.html', query=query_term, results=[], error="Erro ao gerar dashboard")

@main_bp.route('/item/<int:item_id>')
@login_required
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
            
        # Pega resultados (Vencedor) via API PNCP
        # https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencialcompra}/itens/{numerodoitem}/resultados
        item_results = []
        if ata and ata.numeroControlePNCPCompra:
            try:
                import requests
                # Parse numeroControlePNCPCompra: e.g., 45132495000140-1-000579/2024
                # CNPJ: first 14
                ctrl = ata.numeroControlePNCPCompra
                cnpj = ctrl[:14]
                
                # Split by / to separate year part
                parts = ctrl.split('/')
                if len(parts) == 2:
                    ano = parts[1][:4] # 4 chars after /
                    
                    # Sequence: 6 chars before /
                    # parts[0] is everything before /. We take last 6 chars of that.
                    sequencial = parts[0][-6:]
                    
                    url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{item.numeroItem}/resultados"
                    
                    print(f"Fetching item results: {url}")
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        # Ensure it's a list. If /1 was used it would be dict.
                        # Since we removed /1, it should be list.
                        if isinstance(data, list):
                            item_results = data
                            # Sort by price (lowest first) as a proxy for classification if not already sorted
                            try:
                                item_results.sort(key=lambda x: x.get('valorUnitarioHomologado', float('inf')))
                            except:
                                pass # Keep original order if sort fails
                        else:
                            item_results = [data] # Handle single object just in case
                    
                    # Fetch Files (Arquivos)
                    # https://pncp.gov.br/api/pncp/v1/orgaos/{CNPJ}/compras/{ano}/{sequencialCompra}/arquivos
                    url_files = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos"
                    # print(f"Fetching files: {url_files}")
                    resp_files = requests.get(url_files, timeout=5)
                    if resp_files.status_code == 200:
                        item_files = resp_files.json()

            except Exception as api_err:
                print(f"Error fetching item results from External API: {api_err}")

        return render_template('item.html', item=item, orgao=orgao, ata=ata, item_results=item_results, item_files=item_files if 'item_files' in locals() else [])
            
    except Exception as e:
        print(f"Item detail error: {e}")
        return render_template('results.html', query="", results=[], error="Erro ao carregar detalhes do item")

    except Exception as e:
        print(f"Item detail error: {e}")
        return render_template('results.html', query="", results=[], error="Erro ao carregar detalhes do item")

@main_bp.route('/orgao/<path:cnpj>')
@login_required
def orgao_details(cnpj):
    try:
        Orgaos = Base.classes.orgaos
        Atas = Base.classes.atas

        query_ata = request.args.get('q', '')
        vigencia_inicio = request.args.get('vigencia_inicio', '')
        vigencia_fim = request.args.get('vigencia_fim', '')
        page = request.args.get('page', 1, type=int)
        per_page = 20
        is_partial = request.args.get('partial', 'false') == 'true'
        
        # Determine the correct primary key or unique field. 
        # Cnpj is unique but 'id' is pk. Route parameter gives cnpj.
        orgao = db.session.query(Orgaos).filter_by(cnpj=cnpj).first()
        
        if not orgao:
             return render_template('results.html', query="", results=[], error="Órgão não encontrado")
             
        # Fetch Distinct Units for Dropdown
        distinct_units = db.session.query(Atas.nomeUnidadeOrgao).filter_by(cnpjOrgao=cnpj).distinct().order_by(Atas.nomeUnidadeOrgao).all()
        # Flatten list of tuples
        units = [u[0] for u in distinct_units if u[0]]
        
        # Filter params
        query_ata = request.args.get('q', '')
        vigencia_inicio = request.args.get('vigencia_inicio', '')
        vigencia_fim = request.args.get('vigencia_fim', '')
        selected_unit = request.args.get('unidade', '')
        
        # Fetch Atas linked to this Orgao
        atas_query = db.session.query(Atas).filter_by(cnpjOrgao=cnpj)
        
        if query_ata:
            atas_query = atas_query.filter(Atas.objetoContratacao.ilike(f'%{query_ata}%'))
            
        if vigencia_inicio:
            atas_query = atas_query.filter(Atas.vigenciaInicio >= vigencia_inicio)
            
        if vigencia_fim:
            atas_query = atas_query.filter(Atas.vigenciaFim <= vigencia_fim)
            
        if selected_unit:
            atas_query = atas_query.filter(Atas.nomeUnidadeOrgao == selected_unit)
            
        offset = (page - 1) * per_page
        atas = atas_query.offset(offset).limit(per_page + 1).all()
        
        has_next = False
        if len(atas) > per_page:
            has_next = True
            atas = atas[:-1] # Remove the extra item used for checking next page

        if is_partial:
            return render_template('partials/ata_cards.html', atas=atas)
        
        return render_template('orgao.html', orgao=orgao, atas=atas, query_ata=query_ata, vigencia_inicio=vigencia_inicio, vigencia_fim=vigencia_fim, units=units, selected_unit=selected_unit, page=page, has_next=has_next)
        
    except Exception as e:
        print(f"Orgao detail error: {e}")
        if is_partial:
             return jsonify({'error': str(e)}), 500
        return render_template('results.html', query="", results=[], error="Erro ao carregar detalhes do órgão")

@main_bp.route('/ata/<int:ata_id>/itens')
@login_required
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

@main_bp.route('/api/proxy/arquivos/<path:url>')
@login_required
def proxy_arquivos(url):
    if not check_tier_access('download_single'):
        return abort(403, description="Upgrade to Starter or Full to download files.")
        
    # PNCP URL to fetch frompra):
    try:
        import requests
        # Parse numeroControlePNCPCompra: e.g., 45132495000140-1-000579/2024
        # CNPJ: first 14
        ctrl = numero_controle_compra
        
        # Split by / to separate year part
        parts = ctrl.split('/')
        if len(parts) == 2:
            ano = parts[1][:4] # 4 chars after /
            
            # Sequence: 6 chars before /
            sequencial = parts[0][-6:]
            
            # https://pncp.gov.br/api/pncp/v1/orgaos/{CNPJ}/compras/{ano}/{sequencialCompra}/arquivos
            url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos"
            
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return jsonify(response.json())
            return jsonify({"error": f"PNCP API Error: {response.status_code}"}), response.status_code
            
        return jsonify({"error": "Invalid control number format"}), 400
        
    except Exception as e:
        print(f"Proxy error: {e}")
        return jsonify({"error": str(e)}), 500

@main_bp.route('/api/proxy/arquivos/<path:numero_controle_compra>/zip')
@login_required
def proxy_download_all_arquivos(numero_controle_compra):
    if not check_tier_access('download_zip'):
        flash("Funcionalidade exclusiva do plano Full. Atualize para baixar tudo de uma vez!", "warning")
        return redirect(url_for('main.pricing'))
    try:
        import requests
        import zipfile
        import io
        from flask import send_file

        # 1. Fetch File List
        ctrl = numero_controle_compra
        cnpj = ctrl[:14]
        parts = ctrl.split('/')
        if len(parts) != 2:
             return jsonify({"error": "Invalid format"}), 400
             
        ano = parts[1][:4]
        sequencial = parts[0][-6:]
        
        list_url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos"
        resp_list = requests.get(list_url, timeout=10)
        
        if resp_list.status_code != 200:
            return jsonify({"error": "Failed to fetch file list"}), resp_list.status_code
            
        files = resp_list.json()
        if not files:
            return jsonify({"error": "No files found"}), 404

        # 2. Prepare Zip
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_info in files:
                file_url = file_info.get('url')
                file_name = file_info.get('titulo', 'documento')
                # Sanitize filename
                file_name = "".join([c for c in file_name if c.isalpha() or c.isdigit() or c==' ' or c=='_']).strip()
                if not file_name:
                    file_name = f"doc_{file_info.get('sequencialDocumento')}"
                
                # Try to get extension from URL or content-disposition? Just assume generic or fetch it.
                # Simplification: PNCP urls often redirect to a storage.
                # Let's simple fetch.
                try:
                    # Generic request
                    f_resp = requests.get(file_url, timeout=30)
                    if f_resp.status_code == 200:
                        # try guess extension
                        content_type = f_resp.headers.get('Content-Type', '')
                        ext = '.pdf' # Default
                        if 'pdf' in content_type: ext = '.pdf'
                        elif 'xml' in content_type: ext = '.xml'
                        elif 'html' in content_type: ext = '.html'
                        elif 'zip' in content_type: ext = '.zip'
                        elif 'word' in content_type: ext = '.docx'
                        
                        # Avoid duplicates
                        final_name = f"{file_name}{ext}"
                        
                        zf.writestr(final_name, f_resp.content)
                except Exception as e:
                    print(f"Error downloading {file_url}: {e}")
                    # Continue to next file
                    pass
        
        memory_file.seek(0)
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'documentos_{numero_controle_compra.replace("/","-")}.zip'
        )

    except Exception as e:
        print(f"Zip error: {e}")
        return jsonify({"error": str(e)}), 500

@main_bp.route('/export_excel')
@login_required
def export_excel():
    if not check_tier_access('export_excel'):
        flash("Funcionalidade exclusiva do plano Full!", "warning")
        return redirect(url_for('main.pricing'))

    query_term = request.args.get('q', '')
    search_type = request.args.get('type', 'itens')
    
    try:
        import pandas as pd
        import io
        from flask import send_file
        
        results = []
        limit = 5000 # Hard limit to prevent server overload
        
        if search_type == 'itens':
            Itens = Base.classes.itens
            
            # OPTIMIZATION: Use FTS if query_term is present (same logic as search engine)
            if query_term:
                search_query = func.websearch_to_tsquery('portuguese', query_term)
                # Use the FTS index column for speed
                query = db.session.query(Itens).filter(
                    Itens.busca_descricao_idx.op('@@')(search_query)
                )
            else:
                 query = db.session.query(Itens)
                 
            db_results = query.limit(limit).all()
            results = [{k: v for k, v in row.__dict__.items() if not k.startswith('_')} for row in db_results]
            filename = f"itens_pncp_{query_term}.xlsx"
            
        elif search_type == 'atas':
            Atas = Base.classes.atas
            query = db.session.query(Atas).filter(Atas.objetoContratacao.ilike(f'%{query_term}%')) if query_term else db.session.query(Atas)
            db_results = query.limit(limit).all()
            results = [{k: v for k, v in row.__dict__.items() if not k.startswith('_')} for row in db_results]
            filename = f"atas_pncp_{query_term}.xlsx"
            
        elif search_type == 'orgaos':
            Orgaos = Base.classes.orgaos
            # Keep ILIKE for Orgaos as we might not have FTS there yet, and volume is smaller
            query = db.session.query(Orgaos).filter(
                or_(
                    Orgaos.razaoSocial.ilike(f'%{query_term}%'),
                    Orgaos.nomeFantasia.ilike(f'%{query_term}%')
                )
            ) if query_term else db.session.query(Orgaos)
            db_results = query.limit(limit).all()
            results = [{k: v for k, v in row.__dict__.items() if not k.startswith('_')} for row in db_results]
            filename = f"orgaos_pncp_{query_term}.xlsx"
            
        else:
            flash("Tipo de busca inválido", "danger")
            return redirect(url_for('main.index'))

        if not results:
             flash("Sem dados para exportar", "warning")
             return redirect(request.referrer or url_for('main.index'))

        # Create DataFrame
        df = pd.DataFrame(results)
        
        # Remove SQLAlchemy specific or unnecessary columns if any (optional cleaning)
        # For now, export raw data is usually what admins/power users want.
        
        # Output to BytesIO
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Dados')
            
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Export error: {e}")
        flash(f"Erro ao exportar: {str(e)}", "danger")
        return redirect(request.referrer or url_for('main.index'))

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
