"""Application entry point"""
import os
import logging
import sys
from datetime import datetime
from .ControlPlanFlaskApp_postgres import create_app
from .database_postgres import init_db

class TimestampedPrint:
    """Custom print function that adds timestamps"""
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout
    
    def write(self, text):
        if text.strip():  # Only add timestamp to non-empty lines
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.original_stdout.write(f"[{timestamp}] {text}")
        else:
            self.original_stdout.write(text)
    
    def flush(self):
        self.original_stdout.flush()

def main():
    """Main entry point"""
    # Replace stdout to add timestamps to all print statements
    sys.stdout = TimestampedPrint(sys.stdout)
    
    # Initialize database
    init_db()
    
    # Create Flask app
    app = create_app()
    
    # Run application
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    app.run(
        host='0.0.0.0', 
        port=port, 
        debug=os.environ.get('FLASK_ENV') == 'development'
    )

if __name__ == '__main__':
    main()