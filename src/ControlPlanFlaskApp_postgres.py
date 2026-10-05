"""Main Flask application with PostgreSQL database"""
#import debugpy
#debugpy.listen(("0.0.0.0", 5678))
#print("⏳ Debugger listening on port 5678")

from flask import Flask, session
from flask_cors import CORS
import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from .config_postgres import SECRET_KEY, CORS_ORIGINS, TRANSLATIONS, OUTPUT_PRINT_LOGS_FILENAME, PLTF_NAME, APP_VERSION
from .database_postgres import init_db
from .routes.main_routes import main_bp
from .routes.auth_routes import auth_bp
from .routes.sso_routes import sso_bp
from .routes.api_routes import api_bp
from .routes.genai_routes import genai_bp
from .routes.billing_routes import billing_bp
from .routes.orchestrator_routes import orchestrator_bp
from .routes.replication_routes import replication_bp, init_replication_routes
from .routes.security_routes import security_bp
from .routes.serverless_routes import serverless_bp
from .routes.gpu_routes import gpu_bp
from .routes.templates_routes import templates_bp
from .routes.wizard_routes import wizard_bp
from .routes.sandbox_routes import sandbox_bp

# Redirect all print() statements to log files
class PrintLogger:
    def __init__(self, log_file):
        self.log_file = log_file
        self.terminal = sys.stdout
        
    def write(self, message):
        if message.strip():  # Only log non-empty messages
            with open(self.log_file, 'a') as f:
                f.write(f"{message}\n")
                f.flush()
        self.terminal.write(message)
        
    def flush(self):
        self.terminal.flush()

# Setup print logging
log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)
print_log_file = os.path.join(log_dir, OUTPUT_PRINT_LOGS_FILENAME)
sys.stdout = PrintLogger(print_log_file)

def create_app():
    """Application factory"""
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.secret_key = SECRET_KEY
    
    # Configure CORS
    CORS(app, origins=CORS_ORIGINS, supports_credentials=True)
    
    # Initialize database and orchestrator
    with app.app_context():
        init_db()
        try:
            from .orchestrator import orchestrator
            orchestrator.init_orchestrator_tables()
            orchestrator.start_reconciliation_loop()
        except Exception as e:
            print(f"[ERROR] Orchestrator initialization failed: {e}")
            # Continue without orchestrator if it fails
        
        # Initialize replication manager
        try:
            from .replication_manager import ReplicationManager
            from .database_postgres import db_manager
            sync_secret = os.getenv('SYNC_SECRET', 'default-sync-secret-change-me')
            replication_manager = ReplicationManager(db_manager, sync_secret)
            replication_manager.start_worker()
            init_replication_routes(db_manager, sync_secret)
            print("[REPLICATION] Manager initialized and worker started")
        except Exception as e:
            print(f"[ERROR] Replication initialization failed: {e}")
    
    # Language support
    def get_language():
        return session.get('language', 'fr')

    def get_text(key):
        lang = get_language()
        return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS['en'].get(key, key))

    @app.context_processor
    def inject_language():
        from datetime import datetime
        return {
            'get_text': get_text, 
            'current_lang': get_language(),
            'moment': lambda: datetime.now(),
            'PLTF_NAME': PLTF_NAME,
            'APP_VERSION': APP_VERSION
        }
    
    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(sso_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(genai_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(orchestrator_bp)
    app.register_blueprint(replication_bp)
    app.register_blueprint(security_bp)
    app.register_blueprint(serverless_bp)
    app.register_blueprint(gpu_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(wizard_bp)
    app.register_blueprint(sandbox_bp)
    
    return app