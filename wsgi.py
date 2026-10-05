#!/usr/bin/env python3
"""WSGI entry point for production deployment"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.ControlPlanFlaskApp_postgres import create_app
from src.database_postgres import init_db

# Initialize database on startup
init_db()

# Create application instance
application = create_app()

if __name__ == "__main__":
    application.run()