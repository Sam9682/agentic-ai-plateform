#!/usr/bin/env python3
"""Test script for App Orchestrator"""
import os
import sys

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Now we can import the Flask app which will handle the imports correctly
from src.ControlPlanFlaskApp_postgres import create_app

def test_orchestrator():
    """Test orchestrator functionality"""
    print("🎯 Testing App Orchestrator")
    print("=" * 50)
    
    # Create Flask app context
    app = create_app()
    
    with app.app_context():
        from src.orchestrator import orchestrator
        
        print("✅ Orchestrator imported successfully")
        
        # Test service creation
        print("📋 Creating test service...")
        try:
            orchestrator.create_service(
                name="test-nginx",
                image="nginx:alpine",
                desired_replicas=1,
                ports={"80": "8080"},
                environment={"NGINX_HOST": "localhost"},
                volumes=[],
                health_check_path="/health"
            )
            print("✅ Test service created successfully")
        except Exception as e:
            print(f"❌ Error creating service: {e}")
        
        # Test service listing
        print("📊 Listing services...")
        try:
            services = orchestrator.get_service_status()
            print(f"✅ Found {len(services)} services")
            for service in services:
                print(f"  - {service['name']}: {service['desired_replicas']} replicas")
        except Exception as e:
            print(f"❌ Error listing services: {e}")
        
        # Test Nginx config generation
        print("🌐 Generating Nginx config...")
        try:
            config = orchestrator.generate_nginx_config()
            print("✅ Nginx config generated:")
            print(config[:200] + "..." if len(config) > 200 else config)
        except Exception as e:
            print(f"❌ Error generating Nginx config: {e}")
        
        print("\n🎉 App Orchestrator test completed!")

if __name__ == '__main__':
    test_orchestrator()