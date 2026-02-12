from flask import Blueprint, jsonify, render_template, request, flash, redirect, url_for, abort
from .models import Base, db, User
from .utils_tiers import check_tier_access, requires_tier
from sqlalchemy import or_, text
from flask_login import login_required, current_user
from .utils_bigquery import bq_client
from . import cache

main_bp = Blueprint('main', __name__)

def make_cache_key():
    """Custom cache key that includes user tier and query parameters"""
    from flask import request
    from flask_login import current_user
    tier = getattr(current_user, 'tier', 'free')
    # Versioning to force refresh if logic changes
    version = "v7" 
    # Use path and sorted query params to avoid duplicate cache entries for different param order
    args = sorted(request.args.items())
    args_str = "&".join(f"{k}={v}" for k, v in args)
    return f"{version}_{request.path}?{args_str}&tier={tier}"

@main_bp.route('/')
@cache.cached(timeout=3600) # Cache static home page for an hour
def index():
    return render_template('index.html')

@main_bp.route('/search')
@login_required
@cache.cached(timeout=300, key_prefix=make_cache_key)
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
                is_full_access = current_user.tier == 'full' or current_user.role == 'admin'
                if is_full_access:
                    # BigQuery Search
                    results = bq_client.search_items(query_term, limit=per_page+1, offset=offset)
                    total_results = bq_client.count_items(query_term)
                    
                    if len(results) > per_page:
                        has_next = True
                        results = results[:-1]
                else:
                    # Postgres Search
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
@cache.cached(timeout=600, key_prefix=make_cache_key)
def market_analysis_dashboard():
    query_term = request.args.get('q', '')
    if not query_term:
        return render_template('index.html') # Redirect to search if no query
    
    try:
        # Check if we should use BigQuery (Full tier or Admin)
        is_full_access = current_user.tier == 'full' or current_user.role == 'admin'
        
        if is_full_access:
            import concurrent.futures
            
            # Base arguments
            selected_unit = request.args.get('unit')
            selected_state = request.args.get('state')
            selected_region = request.args.get('region')
            
            # Allow selected_unit to be empty for 'All'
            if selected_unit == 'Todas':
                 selected_unit = None
            
            # Execute queries in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                # Filter options (Basal)
                future_units = executor.submit(bq_client.get_unit_distribution, query_term)
                future_states = executor.submit(bq_client.get_states, query_term)
                future_regions = executor.submit(bq_client.get_regions, query_term)
                
                # Filtered Data
                future_stats = executor.submit(bq_client.get_price_stats, query_term, selected_unit, selected_state, selected_region)
                future_prices = executor.submit(bq_client.get_price_sample, query_term, selected_unit, selected_state, selected_region)
                future_top_orgaos = executor.submit(bq_client.get_top_orgaos, query_term, selected_unit, selected_state, selected_region)
                
                # Global Count (conditional)
                future_global_count = None
                if selected_unit or selected_state or selected_region:
                     future_global_count = executor.submit(bq_client.count_items, query_term)
                
                # Gather results
                units = future_units.result()
                states = future_states.result()
                regions = future_regions.result()
                stats = future_stats.result()
                prices = future_prices.result()
                top_orgaos = future_top_orgaos.result()
                
                total_items_filtered = int(stats.get('count_rows') or 0)
                
                if future_global_count:
                    total_items_global = future_global_count.result()
                else:
                    total_items_global = total_items_filtered
            
            # Extract stats
            avg_price = stats.get('avg_price') or 0
            min_price = stats.get('min_price') or 0
            max_price = stats.get('max_price') or 0
            total_quantity = int(stats.get('total_qty') or 0)
            
            # Buckets
            if prices:
                import numpy as np
                counts, bins = np.histogram(prices, bins=10)
                price_buckets_labels = [f"R$ {int(b)}" for b in bins[:-1]]
                price_buckets_values = counts.tolist()
            else:
                 price_buckets_labels = []
                 price_buckets_values = []

            return render_template(
                'dashboard.html',
                query=query_term,
                total_items=total_items_filtered, 
                total_items_global=total_items_global,
                units=units,
                selected_unit=selected_unit,
                states=states,
                selected_state=selected_state,
                regions=regions,
                selected_region=selected_region,
                avg_price=avg_price,
                min_price=min_price,
                max_price=max_price,
                total_quantity=total_quantity,
                price_buckets_labels=price_buckets_labels,
                price_buckets_values=price_buckets_values,
                top_orgaos=top_orgaos
            )

        # Postgres Dashboard (Existing Logic)
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
        return render_template('results.html', query=query_term, results=[], error=f"Erro ao gerar dashboard: {e}")

@main_bp.route('/dashboard')
@login_required
@cache.cached(timeout=600, key_prefix=make_cache_key)
def dashboard():
    query_term = request.args.get('q', '')
    if not query_term:
        return render_template('index.html') # Redirect to search if no query
    
    try:
        # Check if we should use BigQuery (Full tier or Admin)
        is_full_access = current_user.tier == 'full' or current_user.role == 'admin'
        
        if is_full_access:
            import concurrent.futures
            
            # Prepare arguments
            selected_unit = request.args.get('unit')
            selected_state = request.args.get('state')
            selected_region = request.args.get('region')
            
            # Allow selected_unit to be empty for 'All'
            if selected_unit == 'Todas':
                 selected_unit = None
            
            # Execute queries in parallel to reduce total latency
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                # Filter options (Basal)
                future_units = executor.submit(bq_client.get_unit_distribution, query_term)
                future_states = executor.submit(bq_client.get_states, query_term)
                future_regions = executor.submit(bq_client.get_regions, query_term)
                
                # Filtered Data
                future_stats = executor.submit(bq_client.get_price_stats, query_term, selected_unit, selected_state, selected_region)
                future_prices = executor.submit(bq_client.get_price_sample, query_term, selected_unit, selected_state, selected_region)
                future_top_orgaos = executor.submit(bq_client.get_top_orgaos, query_term, selected_unit, selected_state, selected_region)
                
                # Global Count (conditional)
                future_global_count = None
                if selected_unit or selected_state or selected_region:
                     future_global_count = executor.submit(bq_client.count_items, query_term)

                # Gather results (this will block until each is ready)
                units = future_units.result()
                states = future_states.result()
                regions = future_regions.result()
                stats = future_stats.result()
                prices = future_prices.result()
                top_orgaos = future_top_orgaos.result()
                
                total_items_filtered = int(stats.get('count_rows') or 0)
                
                if future_global_count:
                    total_items_global = future_global_count.result()
                else:
                    total_items_global = total_items_filtered
            
            # Extract stats
            avg_price = stats.get('avg_price') or 0
            min_price = stats.get('min_price') or 0
            max_price = stats.get('max_price') or 0
            total_quantity = int(stats.get('total_qty') or 0)
            
            # Buckets
            if prices:
                import numpy as np
                counts, bins = np.histogram(prices, bins=10)
                price_buckets_labels = [f"R$ {int(b)}" for b in bins[:-1]]
                price_buckets_values = counts.tolist()
            else:
                 price_buckets_labels = []
                 price_buckets_values = []

            return render_template(
                'dashboard.html',
                query=query_term,
                total_items=total_items_filtered, 
                total_items_global=total_items_global,
                units=units,
                selected_unit=selected_unit,
                states=states,
                selected_state=selected_state,
                regions=regions,
                selected_region=selected_region,
                avg_price=avg_price,
                min_price=min_price,
                max_price=max_price,
                total_quantity=total_quantity,
                price_buckets_labels=price_buckets_labels,
                price_buckets_values=price_buckets_values,
                top_orgaos=top_orgaos
            )

        # Postgres Dashboard
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
        return render_template('results.html', query=query_term, results=[], error=f"Erro ao gerar dashboard: {e}")

@main_bp.route('/item/<string:numero_controle_encoded>/<int:numero_item>')
@login_required
@cache.cached(timeout=3600, key_prefix=make_cache_key)
def item_details(numero_controle_encoded, numero_item):
    try:
        # Decode base64-encoded numero_controle
        import base64
        numero_controle = base64.b64decode(numero_controle_encoded).decode('utf-8')
        
        is_full_access = current_user.tier == 'full' or current_user.role == 'admin'
        
        # Query based on user tier
        if is_full_access:
            # BigQuery query
            client = bq_client.get_client()
            sql = f"""
                SELECT *
                FROM `{bq_client.project_id}.{bq_client.dataset_id}.itens`
                WHERE parent_numeroControlePNCPAta = @numero_controle
                AND numeroItem = @numero_item
                LIMIT 1
            """
            from google.cloud import bigquery
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("numero_controle", "STRING", numero_controle),
                    bigquery.ScalarQueryParameter("numero_item", "INT64", numero_item),
                ]
            )
            query_job = client.query(sql, job_config=job_config)
            results = list(query_job.result())
            
            if not results:
                return render_template('results.html', query="", results=[], error="Item não encontrado")
            
            item = dict(results[0])
            
            # Get Orgao from BigQuery
            orgao = None
            if item.get('parent_cnpj'):
                sql_orgao = f"""
                    SELECT *
                    FROM `{bq_client.project_id}.{bq_client.dataset_id}.orgaos`
                    WHERE cnpj = @cnpj
                    LIMIT 1
                """
                job_config_orgao = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("cnpj", "INT64", int(item['parent_cnpj'])),
                    ]
                )
                query_job_orgao = client.query(sql_orgao, job_config=job_config_orgao)
                orgao_results = list(query_job_orgao.result())
                if orgao_results:
                    orgao = dict(orgao_results[0])
            
            # Get Ata from BigQuery
            ata = None
            if item.get('parent_numeroControlePNCPAta'):
                sql_ata = f"""
                    SELECT *
                    FROM `{bq_client.project_id}.{bq_client.dataset_id}.atas`
                    WHERE numeroControlePNCPAta = @numero_controle_ata
                    LIMIT 1
                """
                job_config_ata = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("numero_controle_ata", "STRING", item['parent_numeroControlePNCPAta']),
                    ]
                )
                query_job_ata = client.query(sql_ata, job_config=job_config_ata)
                ata_results = list(query_job_ata.result())
                if ata_results:
                    ata = dict(ata_results[0])
        else:
            # PostgreSQL query
            Itens = Base.classes.itens
            Atas = Base.classes.atas
            Orgaos = Base.classes.orgaos
            
            # Get Item
            item = db.session.query(Itens).filter_by(
                parent_numeroControlePNCPAta=numero_controle,
                numeroItem=numero_item
            ).first()
            
            if not item:
                return render_template('results.html', query="", results=[], error="Item não encontrado")
            
            # Convert to dict for consistent template usage
            item = {k: v for k, v in item.__dict__.items() if not k.startswith('_')}
                
            # Get Orgao
            orgao = None
            if item.get('parent_cnpj'):
                orgao_obj = db.session.query(Orgaos).filter_by(cnpj=item['parent_cnpj']).first()
                if orgao_obj:
                    orgao = {k: v for k, v in orgao_obj.__dict__.items() if not k.startswith('_')}
                
            # Get Ata
            ata = None
            if item.get('parent_numeroControlePNCPAta'):
                ata_obj = db.session.query(Atas).filter_by(numeroControlePNCPAta=item['parent_numeroControlePNCPAta']).first()
                if ata_obj:
                    ata = {k: v for k, v in ata_obj.__dict__.items() if not k.startswith('_')}
            
        # Pega resultados (Vencedor) via API PNCP ou tabela resultados
        item_results = []
        item_files = []
        
        if ata and ata.get('numeroControlePNCPCompra'):
            try:
                import requests
                # Parse numeroControlePNCPCompra: e.g., 45132495000140-1-000579/2024
                ctrl = ata['numeroControlePNCPCompra']
                cnpj = ctrl[:14]
                
                # Split by / to separate year part
                parts = ctrl.split('/')
                if len(parts) == 2:
                    ano_part = parts[1]
                    ano = ano_part.split('-')[0] if '-' in ano_part else ano_part[:4]
                    
                    # Sequence: last part before /
                    dash_parts = parts[0].split('-')
                    if len(dash_parts) >= 3:
                        sequencial = dash_parts[2]
                    else:
                        sequencial = parts[0][-6:]
                    
                    url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{item['numeroItem']}/resultados"
                    
                    print(f"Fetching item results: {url}")
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if isinstance(data, list):
                            item_results = data
                            try:
                                item_results.sort(key=lambda x: x.get('valorUnitarioHomologado', float('inf')))
                            except:
                                pass
                        else:
                            item_results = [data]
                    
                    # Fetch Files
                    url_files = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos"
                    resp_files = requests.get(url_files, timeout=5)
                    if resp_files.status_code == 200:
                        item_files = resp_files.json()

            except Exception as api_err:
                print(f"Error fetching item results from External API: {api_err}")

        return render_template('item.html', item=item, orgao=orgao, ata=ata, item_results=item_results, item_files=item_files)
            
    except Exception as e:
        print(f"Item detail error: {e}")
        import traceback
        traceback.print_exc()
        return render_template('results.html', query="", results=[], error="Erro ao carregar detalhes do item")

@main_bp.route('/orgao/<path:cnpj>')
@login_required
@cache.cached(timeout=600, key_prefix=make_cache_key)
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
@cache.cached(timeout=600, key_prefix=make_cache_key)
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

@main_bp.route('/api/proxy/arquivos/<path:numero_controle_compra>')
@login_required
@cache.cached(timeout=600, key_prefix=make_cache_key)
def proxy_arquivos(numero_controle_compra):
    if not check_tier_access('download_single'):
        return abort(403, description="Upgrade to Starter or Full to download files.")
        
    # PNCP URL to fetch from
    try:
        import requests
        # Parse numeroControlePNCPCompra: e.g., 45132495000140-1-000579/2024
        # CNPJ: first 14
        ctrl = numero_controle_compra
        cnpj = ctrl[:14]
        
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
        import openpyxl
        import io
        from flask import send_file
        
        results = []
        limit = 5000 # Hard limit to prevent server overload
        
        if search_type == 'itens':
            is_full_access = current_user.tier == 'full' or current_user.role == 'admin'
            if is_full_access:
                # BigQuery Export with JOIN to resultados table
                client = bq_client.get_client()
                sql = f"""
                    SELECT 
                        i.descricao,
                        i.valorUnitarioEstimado,
                        i.quantidade,
                        i.unidadeMedida,
                        i.situacaoCompraItemNome,
                        i.dataAtualizacao,
                        o.razaoSocial as orgaoNome,
                        r.nomeRazaoSocialFornecedor as fornecedor,
                        r.valorUnitarioHomologado as valorVencedor
                    FROM `{bq_client.project_id}.{bq_client.dataset_id}.itens` i
                    LEFT JOIN `{bq_client.project_id}.{bq_client.dataset_id}.orgaos` o
                        ON i.parent_cnpj = o.cnpj
                    LEFT JOIN `{bq_client.project_id}.{bq_client.dataset_id}.resultados` r
                        ON i.parent_numeroControlePNCPAta = r.numeroControlePNCPCompra
                        AND i.numeroItem = r.numeroItem
                    WHERE SEARCH(i.descricao, @query_term)
                    LIMIT @limit
                """
                from google.cloud import bigquery
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("query_term", "STRING", query_term),
                        bigquery.ScalarQueryParameter("limit", "INT64", limit),
                    ]
                )
                query_job = client.query(sql, job_config=job_config)
                results = [dict(row) for row in query_job.result()]
            else:
                Itens = Base.classes.itens
                Orgaos = Base.classes.orgaos
                
                # Check if resultados table exists
                try:
                    Resultados = Base.classes.resultados
                    has_resultados = True
                except:
                    has_resultados = False
                
                # Join query with specific columns
                if query_term:
                    search_query = func.websearch_to_tsquery('portuguese', query_term)
                    
                    if has_resultados:
                        query = db.session.query(
                            Itens.descricao,
                            Itens.valorUnitarioEstimado,
                            Itens.quantidade,
                            Itens.unidadeMedida,
                            Itens.situacaoCompraItemNome,
                            Itens.dataAtualizacao,
                            Orgaos.razaoSocial.label('orgaoNome'),
                            Resultados.nomerazaosocialfornecedor.label('fornecedor'),
                            Resultados.valorunitariohomologado.label('valorVencedor')
                        ).outerjoin(
                            Orgaos, Itens.parent_cnpj == Orgaos.cnpj
                        ).outerjoin(
                            Resultados, 
                            db.and_(
                                Itens.parent_numeroControlePNCPAta == Resultados.numerocontrolepncpcompra,
                                Itens.numeroItem == Resultados.numeroitem
                            )
                        ).filter(
                            Itens.busca_descricao_idx.op('@@')(search_query)
                        )
                    else:
                        query = db.session.query(
                            Itens.descricao,
                            Itens.valorUnitarioEstimado,
                            Itens.quantidade,
                            Itens.unidadeMedida,
                            Itens.situacaoCompraItemNome,
                            Itens.dataAtualizacao,
                            Orgaos.razaoSocial.label('orgaoNome')
                        ).outerjoin(
                            Orgaos, Itens.parent_cnpj == Orgaos.cnpj
                        ).filter(
                            Itens.busca_descricao_idx.op('@@')(search_query)
                        )
                else:
                    if has_resultados:
                        query = db.session.query(
                            Itens.descricao,
                            Itens.valorUnitarioEstimado,
                            Itens.quantidade,
                            Itens.unidadeMedida,
                            Itens.situacaoCompraItemNome,
                            Itens.dataAtualizacao,
                            Orgaos.razaoSocial.label('orgaoNome'),
                            Resultados.nomerazaosocialfornecedor.label('fornecedor'),
                            Resultados.valorunitariohomologado.label('valorVencedor')
                        ).outerjoin(
                            Orgaos, Itens.parent_cnpj == Orgaos.cnpj
                        ).outerjoin(
                            Resultados, 
                            db.and_(
                                Itens.parent_numeroControlePNCPAta == Resultados.numerocontrolepncpcompra,
                                Itens.numeroItem == Resultados.numeroitem
                            )
                        )
                    else:
                        query = db.session.query(
                            Itens.descricao,
                            Itens.valorUnitarioEstimado,
                            Itens.quantidade,
                            Itens.unidadeMedida,
                            Itens.situacaoCompraItemNome,
                            Itens.dataAtualizacao,
                            Orgaos.razaoSocial.label('orgaoNome')
                        ).outerjoin(
                            Orgaos, Itens.parent_cnpj == Orgaos.cnpj
                        )
                     
                db_results = query.limit(limit).all()
                results = [dict(row._mapping) for row in db_results]
                
                # Add empty columns if resultados table doesn't exist
                if not has_resultados:
                    for r in results:
                        r['fornecedor'] = None
                        r['valorVencedor'] = None
            
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
        
        # Remove timezone information from datetime columns
        for col in df.select_dtypes(include=['datetime', 'datetimetz']).columns:
            df[col] = df[col].dt.tz_localize(None)

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
