from flask import Flask
from .config import Config
from .models import db, init_db

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize DB
    init_db(app)

    # Register Blueprints / Routes
    from .routes import main_bp
    app.register_blueprint(main_bp)

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

    return app
