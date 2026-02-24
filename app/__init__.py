from flask import Flask
from flask_login import LoginManager
from flask_caching import Cache
from .config import Config
from .models import init_db, User

# Initialize cache
cache = Cache()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Configure cache
    # Using simple in-memory cache (for production, use Redis)
    app.config['CACHE_TYPE'] = 'SimpleCache'  # or 'RedisCache' for production
    app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 minutes default
    
    # Initialize cache
    cache.init_app(app)

    # Initialize DB
    init_db(app)

    # Initialize LoginManager
    login_manager = LoginManager()
    login_manager.login_view = 'auth_bp.login' # Will be created later
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.get(int(user_id))

    # Register Blueprints / Routes
    from .routes import main_bp
    from .auth_routes import auth_bp
    from .admin_routes import admin_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    def format_currency(value):
        if value is None:
            return "0,00"
        try:
            val = float(value)
            # Use dot for thousand separator, comma for decimal separator
            return "{:,.2f}".format(val).replace(",", "X").replace(".", ",").replace("X", ".")
        except (ValueError, TypeError):
            return value

    app.jinja_env.filters['format_currency'] = format_currency

    def pncp_url(control_number):
        if not control_number:
            return "#"
        try:
            # Format: CNPJ-SEQDOC-SEQCOMPRA/YEAR-SEQATA
            # Example: 15126437000143-1-002156/2023-000014
            
            # Split by '/'
            parts_slash = control_number.split('/')
            if len(parts_slash) != 2:
                return "#"
            
            # Part 1: "15126437000143-1-002156"
            # Part 2: "2023-000014"
            
            left_part = parts_slash[0]
            right_part = parts_slash[1]
            
            # Parse Left Part
            # Split by '-' -> ['CNPJ', 'SEQDOC', 'SEQCOMPRA']
            left_tokens = left_part.split('-')
            if len(left_tokens) < 3:
                return "#"
                
            cnpj = left_tokens[0]
            seq_doc = left_tokens[1]
            seq_compra = left_tokens[2]
            
            # Parse Right Part
            # Split by '-' -> ['YEAR', 'SEQATA']
            right_tokens = right_part.split('-')
            if len(right_tokens) < 2:
                return "#"
                
            year = right_tokens[0]
            seq_ata = right_tokens[1]
            
            # Construct URL
            # https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{anoCompra}/{sequencialCompra}/atas/{sequencialAta}/arquivos/{sequencialDocumento}
            return f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{year}/{seq_compra}/atas/{seq_ata}/arquivos/{seq_doc}"
            
        except Exception as e:
            print(f"Error parsing PNCP URL: {e}")
            return "#"

    app.jinja_env.filters['pncp_url'] = pncp_url

    def b64encode_filter(value):
        """Base64 encode a string for URL safety"""
        if not value:
            return ""
        import base64
        return base64.b64encode(value.encode('utf-8')).decode('utf-8')
    
    app.jinja_env.filters['b64encode'] = b64encode_filter

    def format_date(value):
        """Format date for display - handles both date objects and strings"""
        if not value:
            return ""
        # If it's already a string, try to extract just the date part
        if isinstance(value, str):
            return value[:10] if len(value) >= 10 else value
        # If it's a date/datetime object, format it
        try:
            return value.strftime('%Y-%m-%d')
        except:
            return str(value)
    
    app.jinja_env.filters['format_date'] = format_date

    return app
