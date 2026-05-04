from flask import Blueprint, jsonify, render_template, request, flash, redirect, url_for, abort
from .models import User
from .utils_tiers import check_tier_access, requires_tier
from flask_login import login_required, current_user
from .utils_bigquery import bq_client
from . import cache
import os

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

@main_bp.route('/pesquisa')
@login_required
def pesquisa():
    """Tela de busca histórica (campo de pesquisa)."""
    return render_template('pesquisa.html')

@main_bp.route('/search')
@login_required
@cache.cached(timeout=300, key_prefix=make_cache_key)
def search():
    query_term = request.args.get('q', '')
    search_type = request.args.get('type', 'itens')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    is_partial = request.args.get('partial', 'false') == 'true'

    # Sem termo de busca → redireciona para a tela de pesquisa
    if not query_term and not is_partial:
        return redirect(url_for('main.pesquisa'))

    results = []
    has_next = False

    if query_term:
        try:
            offset = (page - 1) * per_page
            
            if search_type == 'itens':
                # BigQuery Search
                results = bq_client.search_items(query_term, limit=per_page+1, offset=offset)
                total_results = bq_client.count_items(query_term)
                
                if len(results) > per_page:
                    has_next = True
                    results = results[:-1]
                
            elif search_type == 'atas':
                # BigQuery search for atas
                from google.cloud import bigquery as bq_module
                client = bq_client.get_client()
                
                # Data query with orgaos JOIN for city/state (skip count for performance)
                sql = f"""
                    SELECT 
                        a.numeroControlePNCPAta,
                        a.numeroAtaRegistroPreco,
                        a.anoAta,
                        a.numeroControlePNCPCompra,
                        a.objetoContratacao,
                        a.cnpjOrgao,
                        a.nomeOrgao,
                        a.nomeUnidadeOrgao,
                        a.vigenciaInicio,
                        a.vigenciaFim,
                        a.cancelado,
                        o.City as city,
                        o.State as state
                    FROM `{bq_client.project_id}.{bq_client.dataset_id}.atas` a
                    LEFT JOIN `{bq_client.project_id}.{bq_client.dataset_id}.orgaos` o
                        ON a.cnpjOrgao = o.cnpj
                    WHERE CONTAINS_SUBSTR(a.objetoContratacao, @query_term)
                    LIMIT @limit OFFSET @offset
                """
                job_config = bq_module.QueryJobConfig(
                    query_parameters=[
                        bq_module.ScalarQueryParameter("query_term", "STRING", query_term),
                        bq_module.ScalarQueryParameter("limit", "INT64", per_page + 1),
                        bq_module.ScalarQueryParameter("offset", "INT64", offset),
                    ]
                )
                query_job = client.query(sql, job_config=job_config)
                db_results = [dict(row) for row in query_job.result()]
                
                total_results = -1  # Skip count for performance
                if len(db_results) > per_page:
                    has_next = True
                    db_results = db_results[:-1]

                results = db_results


                
            elif search_type == 'orgaos':
                from google.cloud import bigquery as bq_module
                client = bq_client.get_client()
                sql = f"""
                    SELECT * FROM `{bq_client.project_id}.{bq_client.dataset_id}.orgaos`
                    WHERE SEARCH(razaoSocial, @query_term) OR SEARCH(nomeFantasia, @query_term)
                    LIMIT @limit OFFSET @offset
                """
                job_config = bq_module.QueryJobConfig(
                    query_parameters=[
                        bq_module.ScalarQueryParameter("query_term", "STRING", query_term),
                        bq_module.ScalarQueryParameter("limit", "INT64", per_page + 1),
                        bq_module.ScalarQueryParameter("offset", "INT64", offset),
                    ]
                )
                query_job = client.query(sql, job_config=job_config)
                db_results = [dict(row) for row in query_job.result()]
                
                total_results = -1
                if len(db_results) > per_page:
                    has_next = True
                    db_results = db_results[:-1]
                
                results = db_results

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
        current_user.save()
        flash(f'Plano {tier.upper()} selecionado com sucesso! Bem-vindo.', 'success')
    except Exception as e:
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
        is_full_access = True
        
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
            
            total_quantity = int(stats.get('total_qty') or 0)
            
            # Default stats (fallback)
            avg_price = stats.get('avg_price') or 0
            min_price = stats.get('min_price') or 0
            max_price = stats.get('max_price') or 0
            
            # Buckets and Filtered Stats
            if prices:
                import numpy as np
                prices_raw = [p for p in prices if p > 0]
                if prices_raw:
                    p05 = np.percentile(prices_raw, 5)
                    p95 = np.percentile(prices_raw, 95)
                    prices_filtered = [p for p in prices_raw if p >= p05 and p <= p95]
                    if not prices_filtered:
                        prices_filtered = prices_raw
                        
                    counts, bins = np.histogram(prices_filtered, bins=10)
                    price_buckets_labels = [f"R$ {b:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') for b in bins[:-1]]
                    price_buckets_values = counts.tolist()
                    
                    # Update stats using sample (excludes high outliers)
                    avg_price = float(np.mean(prices_filtered))
                    min_price = float(np.min(prices_filtered))
                    max_price = float(np.max(prices_filtered))
                else:
                    price_buckets_labels = []
                    price_buckets_values = []
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
        is_full_access = True
        
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
            
            total_quantity = int(stats.get('total_qty') or 0)
            
            # Default stats (fallback)
            avg_price = stats.get('avg_price') or 0
            min_price = stats.get('min_price') or 0
            max_price = stats.get('max_price') or 0
            
            # Buckets and Filtered Stats
            if prices:
                import numpy as np
                prices_raw = [p for p in prices if p > 0]
                if prices_raw:
                    p05 = np.percentile(prices_raw, 5)
                    p95 = np.percentile(prices_raw, 95)
                    prices_filtered = [p for p in prices_raw if p >= p05 and p <= p95]
                    if not prices_filtered:
                        prices_filtered = prices_raw
                        
                    counts, bins = np.histogram(prices_filtered, bins=10)
                    price_buckets_labels = [f"R$ {b:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') for b in bins[:-1]]
                    price_buckets_values = counts.tolist()
                    
                    # Update stats using sample (excludes high outliers)
                    avg_price = float(np.mean(prices_filtered))
                    min_price = float(np.min(prices_filtered))
                    max_price = float(np.max(prices_filtered))
                else:
                    price_buckets_labels = []
                    price_buckets_values = []
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
        
        is_full_access = True
        
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
        from google.cloud import bigquery as bq_module
        client = bq_client.get_client()

        query_ata = request.args.get('q', '')
        vigencia_inicio = request.args.get('vigencia_inicio', '')
        vigencia_fim = request.args.get('vigencia_fim', '')
        page = request.args.get('page', 1, type=int)
        per_page = 20
        is_partial = request.args.get('partial', 'false') == 'true'
        
        # cnpj column is INT64 in BigQuery, cast from URL string
        try:
            cnpj_int = int(cnpj)
        except (ValueError, TypeError):
            cnpj_int = 0
        
        # Get Orgao
        orgao_sql = f"SELECT * FROM `{bq_client.project_id}.{bq_client.dataset_id}.orgaos` WHERE cnpj = @cnpj LIMIT 1"
        orgao_job = client.query(orgao_sql, job_config=bq_module.QueryJobConfig(query_parameters=[bq_module.ScalarQueryParameter("cnpj", "INT64", cnpj_int)]))
        orgao_results = list(orgao_job.result())
        
        if not orgao_results:
             return render_template('results.html', query="", results=[], error="Órgão não encontrado")
        orgao = type('Orgao', (), dict(orgao_results[0]))()

        # Get Distinct Units — use CAST for type safety
        units_sql = f"SELECT DISTINCT nomeUnidadeOrgao FROM `{bq_client.project_id}.{bq_client.dataset_id}.atas` WHERE CAST(cnpjOrgao AS STRING) = @cnpj AND nomeUnidadeOrgao IS NOT NULL ORDER BY nomeUnidadeOrgao"
        units_job = client.query(units_sql, job_config=bq_module.QueryJobConfig(query_parameters=[bq_module.ScalarQueryParameter("cnpj", "STRING", cnpj)]))
        units = [row['nomeUnidadeOrgao'] for row in units_job.result()]
        
        # Build Atas Query — use CAST for type safety
        atas_sql = f"SELECT * FROM `{bq_client.project_id}.{bq_client.dataset_id}.atas` WHERE CAST(cnpjOrgao AS STRING) = @cnpj"
        query_parameters = [bq_module.ScalarQueryParameter("cnpj", "STRING", cnpj)]
        
        if query_ata:
            atas_sql += " AND CONTAINS_SUBSTR(objetoContratacao, @query_ata)"
            query_parameters.append(bq_module.ScalarQueryParameter("query_ata", "STRING", query_ata))
            
        if vigencia_inicio:
            atas_sql += " AND vigenciaInicio >= @inicio"
            query_parameters.append(bq_module.ScalarQueryParameter("inicio", "STRING", vigencia_inicio))
            
        if vigencia_fim:
            atas_sql += " AND vigenciaFim <= @fim"
            query_parameters.append(bq_module.ScalarQueryParameter("fim", "STRING", vigencia_fim))
            
        selected_unit = request.args.get('unidade', '')
        if selected_unit:
            atas_sql += " AND nomeUnidadeOrgao = @unidade"
            query_parameters.append(bq_module.ScalarQueryParameter("unidade", "STRING", selected_unit))
            
        offset = (page - 1) * per_page
        atas_sql += " LIMIT @limit OFFSET @offset"
        query_parameters.extend([
            bq_module.ScalarQueryParameter("limit", "INT64", per_page + 1),
            bq_module.ScalarQueryParameter("offset", "INT64", offset)
        ])
        
        atas_job = client.query(atas_sql, job_config=bq_module.QueryJobConfig(query_parameters=query_parameters))
        atas_results = list(atas_job.result())
        
        has_next = False
        if len(atas_results) > per_page:
            has_next = True
            atas_results = atas_results[:-1]
            
        atas = [type('Ata', (), dict(row))() for row in atas_results]

        if is_partial:
            return render_template('partials/ata_cards.html', atas=atas)
        
        return render_template('orgao.html', orgao=orgao, atas=atas, query_ata=query_ata, vigencia_inicio=vigencia_inicio, vigencia_fim=vigencia_fim, units=units, selected_unit=selected_unit, page=page, has_next=has_next)
        
    except Exception as e:
        print(f"Orgao detail error: {e}")
        if is_partial:
             return jsonify({'error': str(e)}), 500
        return render_template('results.html', query="", results=[], error="Erro ao carregar detalhes do órgão")

@main_bp.route('/ata/<path:numero_controle_encoded>/itens')
@login_required
@cache.cached(timeout=600, key_prefix=make_cache_key)
def ata_items(numero_controle_encoded):
    try:
        import base64
        from google.cloud import bigquery as bq_module
        client = bq_client.get_client()
        
        numero_controle = base64.b64decode(numero_controle_encoded).decode('utf-8')
        
        # Fetch Ata by numeroControlePNCPAta
        ata_sql = f"""
            SELECT *
            FROM `{bq_client.project_id}.{bq_client.dataset_id}.atas`
            WHERE numeroControlePNCPAta = @numero_controle
            LIMIT 1
        """
        ata_config = bq_module.QueryJobConfig(
            query_parameters=[bq_module.ScalarQueryParameter("numero_controle", "STRING", numero_controle)]
        )
        ata_job = client.query(ata_sql, job_config=ata_config)
        ata_results = [dict(row) for row in ata_job.result()]
        
        if not ata_results:
            return render_template('results.html', query="", results=[], error="Ata não encontrada")
        
        ata = type('Ata', (), ata_results[0])()  # Convert dict to object for template compatibility
        
        # Fetch Items linked to this Ata via numeroControlePNCPAta
        items_sql = f"""
            SELECT *
            FROM `{bq_client.project_id}.{bq_client.dataset_id}.itens`
            WHERE parent_numeroControlePNCPAta = @numero_controle
            ORDER BY numeroItem
        """
        items_config = bq_module.QueryJobConfig(
            query_parameters=[bq_module.ScalarQueryParameter("numero_controle", "STRING", numero_controle)]
        )
        items_job = client.query(items_sql, job_config=items_config)
        items = [type('Item', (), dict(row))() for row in items_job.result()]
        
        return render_template('ata_items.html', ata=ata, items=items)
        
    except Exception as e:
        print(f"Ata items error: {e}")
        import traceback
        traceback.print_exc()
        return render_template('results.html', query="", results=[], error=f"Erro ao carregar itens da ata: {e}")

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
            is_full_access = True
            if is_full_access:
                # BigQuery Export - try with resultados table, fallback without
                client = bq_client.get_client()
                from google.cloud import bigquery
                
                # First try with resultados JOIN
                try:
                    sql = f"""
                        SELECT 
                            i.descricao,
                            i.valorUnitarioEstimado,
                            i.quantidade,
                            i.unidadeMedida,
                            i.situacaoCompraItemNome,
                            i.dataAtualizacao,
                            o.razaoSocial as orgaoNome,
                            o.State as estado,
                            o.regiao,
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
                    job_config = bigquery.QueryJobConfig(
                        query_parameters=[
                            bigquery.ScalarQueryParameter("query_term", "STRING", query_term),
                            bigquery.ScalarQueryParameter("limit", "INT64", limit),
                        ]
                    )
                    query_job = client.query(sql, job_config=job_config)
                    results = [dict(row) for row in query_job.result()]
                except Exception as e_resultados:
                    print(f"Export: resultados table not available ({e_resultados}), falling back without it")
                    sql = f"""
                        SELECT 
                            i.descricao,
                            i.valorUnitarioEstimado,
                            i.quantidade,
                            i.unidadeMedida,
                            i.situacaoCompraItemNome,
                            i.dataAtualizacao,
                            o.razaoSocial as orgaoNome,
                            o.State as estado,
                            o.regiao
                        FROM `{bq_client.project_id}.{bq_client.dataset_id}.itens` i
                        LEFT JOIN `{bq_client.project_id}.{bq_client.dataset_id}.orgaos` o
                            ON i.parent_cnpj = o.cnpj
                        WHERE SEARCH(i.descricao, @query_term)
                        LIMIT @limit
                    """
                    job_config = bigquery.QueryJobConfig(
                        query_parameters=[
                            bigquery.ScalarQueryParameter("query_term", "STRING", query_term),
                            bigquery.ScalarQueryParameter("limit", "INT64", limit),
                        ]
                    )
                    query_job = client.query(sql, job_config=job_config)
                    results = [dict(row) for row in query_job.result()]


            
            filename = f"itens_pncp_{query_term}.xlsx"
            
        elif search_type == 'atas':
            from google.cloud import bigquery as bq_module
            client = bq_client.get_client()
            sql = f"SELECT * FROM `{bq_client.project_id}.{bq_client.dataset_id}.atas`"
            job_config = None
            if query_term:
                sql += " WHERE CONTAINS_SUBSTR(objetoContratacao, @query_term)"
            sql += " LIMIT @limit"
            job_config = bq_module.QueryJobConfig(
                query_parameters=[
                    bq_module.ScalarQueryParameter("query_term", "STRING", query_term or ""),
                    bq_module.ScalarQueryParameter("limit", "INT64", limit),
                ]
            )
            query_job = client.query(sql, job_config=job_config)
            results = [dict(row) for row in query_job.result()]
            filename = f"atas_pncp_{query_term}.xlsx"
            
        elif search_type == 'orgaos':
            from google.cloud import bigquery as bq_module
            client = bq_client.get_client()
            sql = f"SELECT * FROM `{bq_client.project_id}.{bq_client.dataset_id}.orgaos`"
            job_config = None
            if query_term:
                sql += " WHERE SEARCH(razaoSocial, @query_term) OR SEARCH(nomeFantasia, @query_term)"
            sql += " LIMIT @limit"
            job_config = bq_module.QueryJobConfig(
                query_parameters=[
                    bq_module.ScalarQueryParameter("query_term", "STRING", query_term or ""),
                    bq_module.ScalarQueryParameter("limit", "INT64", limit),
                ]
            )
            query_job = client.query(sql, job_config=job_config)
            results = [dict(row) for row in query_job.result()]
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
        "backend": "BigQuery"
    })

@main_bp.route('/old_api/atas')
def list_atas():
    try:
        from google.cloud import bigquery as bq_module
        client = bq_client.get_client()
        sql = f"SELECT * FROM `{bq_client.project_id}.{bq_client.dataset_id}.atas` LIMIT 5"
        query_job = client.query(sql)
        return jsonify([dict(row) for row in query_job.result()])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main_bp.route('/old_api/orgaos')
def list_orgaos():
    try:
        from google.cloud import bigquery as bq_module
        client = bq_client.get_client()
        sql = f"SELECT * FROM `{bq_client.project_id}.{bq_client.dataset_id}.orgaos` LIMIT 5"
        query_job = client.query(sql)
        return jsonify([dict(row) for row in query_job.result()])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main_bp.route('/old_api/itens')
def list_itens():
    try:
        from google.cloud import bigquery as bq_module
        client = bq_client.get_client()
        sql = f"SELECT * FROM `{bq_client.project_id}.{bq_client.dataset_id}.itens` LIMIT 5"
        query_job = client.query(sql)
        return jsonify([dict(row) for row in query_job.result()])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Oportunidades Futuras ─────────────────────────────────────────────────────

@main_bp.route('/oportunidades')
@login_required
def oportunidades():
    """Tela de pesquisa de pregões/licitações em aberto."""
    from google.cloud import bigquery as bq_module

    query = request.args.get('q', '')
    selected_uf = request.args.get('uf', '')
    selected_modalidade = request.args.get('modalidade', '')
    cnpj_orgao = request.args.get('cnpj_orgao', '')
    data_fim = request.args.get('data_fim', '')
    page = request.args.get('page', 1, type=int)
    per_page = 24

    results = []
    total_results = 0
    has_next = False
    ufs = []
    table_exists = True

    try:
        client = bq_client.get_client()
        table = f"`{bq_client.project_id}.{bq_client.dataset_id}.compras_abertas`"

        # UFs para filtro — se a tabela não existir, captura graciosamente
        try:
            ufs_sql = f"SELECT DISTINCT uf FROM {table} WHERE uf IS NOT NULL AND uf != '' ORDER BY uf"
            ufs = [row['uf'] for row in client.query(ufs_sql).result()]
        except Exception as e_ufs:
            err_str = str(e_ufs)
            if "Not found" in err_str or "notFound" in err_str or "does not exist" in err_str:
                table_exists = False
                print(f"Tabela compras_abertas ainda não existe: {e_ufs}")
            else:
                print(f"Erro ao buscar UFs: {e_ufs}")

        if table_exists:
            params = []
            # Sem filtros → retorna TODOS os registros do banco
            conditions = []

            if query:
                conditions.append("CONTAINS_SUBSTR(objetoCompra, @query)")
                params.append(bq_module.ScalarQueryParameter("query", "STRING", query))

            if selected_uf:
                conditions.append("uf = @uf")
                params.append(bq_module.ScalarQueryParameter("uf", "STRING", selected_uf))

            if selected_modalidade:
                conditions.append("modalidadeId = @modalidade_id")
                params.append(bq_module.ScalarQueryParameter("modalidade_id", "INT64", int(selected_modalidade)))

            if cnpj_orgao:
                cnpj_clean = ''.join(filter(str.isdigit, cnpj_orgao))
                conditions.append("cnpjOrgao = @cnpj_orgao")
                params.append(bq_module.ScalarQueryParameter("cnpj_orgao", "STRING", cnpj_clean))

            if data_fim:
                conditions.append("DATE(dataEncerramentoProposta) <= @data_fim")
                params.append(bq_module.ScalarQueryParameter("data_fim", "DATE", data_fim))

            where = " AND ".join(conditions) if conditions else "TRUE"
            offset = (page - 1) * per_page

            sql = f"""
                SELECT *,
                    DATE_DIFF(DATE(dataEncerramentoProposta), CURRENT_DATE(), DAY) AS dias_restantes
                FROM {table}
                WHERE {where}
                ORDER BY dataEncerramentoProposta DESC
                LIMIT @limit OFFSET @offset
            """
            params += [
                bq_module.ScalarQueryParameter("limit", "INT64", per_page + 1),
                bq_module.ScalarQueryParameter("offset", "INT64", offset),
            ]

            job_config = bq_module.QueryJobConfig(query_parameters=params)
            raw_rows = list(client.query(sql, job_config=job_config).result())

            # Serializa datetimes para string (evita erros no Jinja2 com [:10])
            def serialize_row(row):
                out = {}
                for k, v in dict(row).items():
                    out[k] = v.isoformat() if hasattr(v, 'isoformat') else v
                return out

            db_results = [serialize_row(r) for r in raw_rows]

            if len(db_results) > per_page:
                has_next = True
                db_results = db_results[:-1]

            results = db_results
            total_results = len(results) + (1 if has_next else 0) + offset

    except Exception as e:
        print(f"Oportunidades error: {e}")
        import traceback; traceback.print_exc()

    return render_template(
        'oportunidades.html',
        results=results,
        query=query,
        ufs=ufs,
        selected_uf=selected_uf,
        selected_modalidade=selected_modalidade,
        cnpj_orgao=cnpj_orgao,
        data_fim=data_fim,
        page=page,
        has_next=has_next,
        total_results=total_results,
        table_exists=table_exists,
    )


@main_bp.route('/oportunidades/<path:numero_controle>')
@login_required
def oportunidade_detail(numero_controle):
    from google.cloud import bigquery as bq_module

    try:
        client = bq_client.get_client()
        table = f"`{bq_client.project_id}.{bq_client.dataset_id}.compras_abertas`"

        sql = f"""
            SELECT *,
                DATE_DIFF(DATE(dataEncerramentoProposta), CURRENT_DATE(), DAY) AS dias_restantes
            FROM {table}
            WHERE numeroControlePNCPCompra = @numero_controle
            LIMIT 1
        """
        job_config = bq_module.QueryJobConfig(
            query_parameters=[
                bq_module.ScalarQueryParameter("numero_controle", "STRING", numero_controle)
            ]
        )
        rows = list(client.query(sql, job_config=job_config).result())

        if not rows:
            return render_template('results.html', query="", results=[], error="Edital não encontrado")

        # Converte datetime → string ISO para o Jinja conseguir fazer [:10]
        def serialize_row(row):
            result = {}
            for key, val in dict(row).items():
                if hasattr(val, 'isoformat'):
                    result[key] = val.isoformat()
                else:
                    result[key] = val
            return result

        edital = serialize_row(rows[0])


        # ── Balizamento Histórico (Dupla Estratégia) ──
        benchmark = {"exact_matches": [], "semantic_matches": [], "benchmark": {}}
        benchmark_error = None

        try:
            from .utils_embeddings import get_price_benchmark
            benchmark = get_price_benchmark(
                description=edital.get("objetoCompra") or "",
                cnpj_orgao=edital.get("cnpjOrgao"),
            )
        except Exception as emb_err:
            benchmark_error = str(emb_err)
            print(f"Benchmark error (non-fatal): {emb_err}")

        # ── Itens do Edital via API PNCP ──
        itens_edital = []
        try:
            import requests as req_lib
            cnpj = edital.get("cnpjOrgao", "")[:14]
            ano = str(edital.get("anoCompra") or "")
            seq = str(edital.get("sequencialCompra") or "").zfill(6)
            if cnpj and ano and seq:
                url_itens = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens"
                resp = req_lib.get(url_itens, timeout=10)
                if resp.status_code == 200:
                    itens_edital = resp.json() if isinstance(resp.json(), list) else []
        except Exception as api_err:
            print(f"API itens error (non-fatal): {api_err}")

        return render_template(
            'oportunidade_detail.html',
            edital=edital,
            benchmark=benchmark,
            benchmark_error=benchmark_error,
            itens_edital=itens_edital,
        )

    except Exception as e:
        print(f"Oportunidade detail error: {e}")
        import traceback; traceback.print_exc()
        return render_template('results.html', query="", results=[], error=f"Erro ao carregar edital: {e}")


# ─── Helper: persiste itens_novos no BigQuery (background) ────────────────────

def _salvar_itens_novos_bg(itens: list, edital_info: dict):
    """
    Persiste itens de editais abertos na tabela itens_novos do BigQuery.
    Executado em daemon thread — não bloqueia o response.
    Usa INSERT...WHERE NOT EXISTS (batch job, sem streaming buffer).
    """
    import threading

    def _run():
        try:
            from google.cloud import bigquery as bq_module
            from datetime import datetime, timezone
            from .utils_bigquery import bq_client as _bq

            pid = _bq.project_id
            did = _bq.dataset_id
            table_id = f"{pid}.{did}.itens_novos"
            client = _bq.get_client()

            schema = [
                bq_module.SchemaField("id",                        "STRING"),
                bq_module.SchemaField("numeroControlePNCPCompra",  "STRING"),
                bq_module.SchemaField("cnpjOrgao",                 "STRING"),
                bq_module.SchemaField("anoCompra",                 "INTEGER"),
                bq_module.SchemaField("sequencialCompra",          "INTEGER"),
                bq_module.SchemaField("numeroItem",                "INTEGER"),
                bq_module.SchemaField("descricao",                 "STRING"),
                bq_module.SchemaField("quantidade",                "FLOAT"),
                bq_module.SchemaField("unidadeMedida",             "STRING"),
                bq_module.SchemaField("valorUnitarioEstimado",     "FLOAT"),
                bq_module.SchemaField("materialOuServico",         "STRING"),
                bq_module.SchemaField("criterioJulgamentoNome",    "STRING"),
                bq_module.SchemaField("nomeOrgao",                 "STRING"),
                bq_module.SchemaField("uf",                        "STRING"),
                bq_module.SchemaField("municipio",                 "STRING"),
                bq_module.SchemaField("dataEncerramentoProposta",  "TIMESTAMP"),
                bq_module.SchemaField("updated_at",                "TIMESTAMP"),
            ]
            table = bq_module.Table(table_id, schema=schema)
            client.create_table(table, exists_ok=True)

            now = datetime.now(timezone.utc).isoformat()
            num_controle = edital_info.get("numeroControlePNCPCompra", "")

            for item in itens:
                num_item = int(item.get("numeroItem") or 0)
                item_id = f"{num_controle}-{num_item}"
                enc = str(edital_info.get("dataEncerramentoProposta") or now)
                if len(enc) > 19:
                    enc = enc[:19] + "Z"

                sql = f"""
                    INSERT INTO `{table_id}`
                        (id, numeroControlePNCPCompra, cnpjOrgao, anoCompra,
                         sequencialCompra, numeroItem, descricao, quantidade,
                         unidadeMedida, valorUnitarioEstimado, materialOuServico,
                         criterioJulgamentoNome, nomeOrgao, uf, municipio,
                         dataEncerramentoProposta, updated_at)
                    SELECT
                        @id, @ctrl, @cnpj, @ano, @seq, @nitem, @desc,
                        @qty, @unid, @vest, @mat, @crit, @orgao, @uf, @mun,
                        @enc, @upd
                    WHERE NOT EXISTS (
                        SELECT 1 FROM `{table_id}` WHERE id = @id
                    )
                """
                params = [
                    bq_module.ScalarQueryParameter("id",    "STRING",  item_id),
                    bq_module.ScalarQueryParameter("ctrl",  "STRING",  num_controle),
                    bq_module.ScalarQueryParameter("cnpj",  "STRING",  str(edital_info.get("cnpjOrgao") or "")),
                    bq_module.ScalarQueryParameter("ano",   "INT64",   int(edital_info.get("anoCompra") or 0)),
                    bq_module.ScalarQueryParameter("seq",   "INT64",   int(edital_info.get("sequencialCompra") or 0)),
                    bq_module.ScalarQueryParameter("nitem", "INT64",   num_item),
                    bq_module.ScalarQueryParameter("desc",  "STRING",  str(item.get("descricao") or item.get("descricaoItem") or "")),
                    bq_module.ScalarQueryParameter("qty",   "FLOAT64", float(item.get("quantidade") or 0)),
                    bq_module.ScalarQueryParameter("unid",  "STRING",  str(item.get("unidadeMedida") or "")),
                    bq_module.ScalarQueryParameter("vest",  "FLOAT64", float(item.get("valorUnitarioEstimado") or 0)),
                    bq_module.ScalarQueryParameter("mat",   "STRING",  str(item.get("materialOuServico") or "")),
                    bq_module.ScalarQueryParameter("crit",  "STRING",  str(item.get("criterioJulgamentoNome") or "")),
                    bq_module.ScalarQueryParameter("orgao", "STRING",  str(edital_info.get("nomeOrgao") or edital_info.get("nomeUnidadeOrgao") or "")),
                    bq_module.ScalarQueryParameter("uf",    "STRING",  str(edital_info.get("uf") or "")),
                    bq_module.ScalarQueryParameter("mun",   "STRING",  str(edital_info.get("municipio") or "")),
                    bq_module.ScalarQueryParameter("enc",   "TIMESTAMP", enc),
                    bq_module.ScalarQueryParameter("upd",   "TIMESTAMP", now),
                ]
                jc = bq_module.QueryJobConfig(query_parameters=params)
                client.query(sql, job_config=jc).result()

            print(f"[itens_novos] {len(itens)} itens salvos para {num_controle}")
        except Exception as e:
            print(f"[itens_novos] Erro (non-fatal): {e}")
            import traceback; traceback.print_exc()

    threading.Thread(target=_run, daemon=True).start()


# ─── Balizamento por Item (mecânico, Jaccard) ──────────────────────────────────

@main_bp.route('/api/balizamento/por-item', methods=['POST'])
@login_required
def balizamento_por_item():
    """
    Recebe lista de itens de um edital e retorna balizamento histórico mecânico.
    Body JSON: { "itens": [...], "edital": {...} }
    Processa todos em paralelo (ThreadPoolExecutor) e salva em itens_novos (background).
    """
    import concurrent.futures

    data = request.get_json(silent=True) or {}
    itens = data.get('itens', [])
    edital_info = data.get('edital', {})

    if not itens:
        return jsonify({"error": "itens é obrigatório"}), 400

    from .utils_embeddings import balizamento_mecanico_por_item

    def baliza_item(item):
        desc = item.get('descricao') or item.get('descricaoItem') or ''
        num  = item.get('numeroItem')
        if not desc:
            return {"numeroItem": num, "matches": [], "benchmark": {}, "aderencia_max": 0.0, "descricao": ""}
        result = balizamento_mecanico_por_item(descricao=desc, top_n=5, min_aderencia=0.75)
        result["numeroItem"] = num
        result["descricao"]  = desc
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(itens))) as executor:
        futures = {executor.submit(baliza_item, item): item for item in itens}
        resultados = []
        for future in concurrent.futures.as_completed(futures):
            try:
                resultados.append(future.result())
            except Exception as e:
                item = futures[future]
                resultados.append({
                    "numeroItem": item.get('numeroItem'),
                    "error": str(e),
                    "matches": [], "benchmark": {}, "aderencia_max": 0.0,
                })

    # Salva itens_novos em background (não bloqueia o response)
    if edital_info:
        _salvar_itens_novos_bg(itens, edital_info)

    resultados.sort(key=lambda x: x.get('numeroItem') or 0)
    return jsonify({"resultados": resultados})


# ─── Agente de IA (Streaming SSE) ─────────────────────────────────────────────

@main_bp.route('/api/ai/analyze', methods=['POST'])
@login_required
def ai_analyze():
    """
    Endpoint de análise por IA via Gemini (Server-Sent Events / streaming).
    Body JSON: { "query": str, "results": [...], "type": "search"|"oportunidade" }
    """
    import json as _json
    from flask import Response, stream_with_context

    data = request.get_json(silent=True) or {}
    query = data.get('query', '')
    results = data.get('results', [])
    analysis_type = data.get('type', 'search')

    if not query:
        return jsonify({"error": "query é obrigatório"}), 400

    if not os.environ.get('GEMINI_API_KEY'):
        return jsonify({"error": "GEMINI_API_KEY não configurada. Adicione ao arquivo .env."}), 503

    def generate():
        try:
            from .utils_ai import analyze_search_results, analyze_oportunidade
            if analysis_type == 'oportunidade':
                edital = data.get('edital', {})
                gen = analyze_oportunidade(edital=edital, historico=results)
            else:
                gen = analyze_search_results(query=query, results=results)

            for chunk in gen:
                # Server-Sent Events format — usa json.dumps (sem contexto Flask)
                yield f"data: {_json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"

        except Exception as e:
            error_msg = str(e)
            print(f"AI analyze error: {error_msg}")
            yield f"data: {_json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
