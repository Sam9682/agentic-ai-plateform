#!/usr/bin/env python3
"""CLI commands for App Orchestrator management"""
import sys
import os
import json
import argparse

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import with absolute imports
import database
import orchestrator as orch_module

def create_service(args):
    """Create a new service"""
    ports = json.loads(args.ports) if args.ports else {}
    environment = json.loads(args.environment) if args.environment else {}
    volumes = json.loads(args.volumes) if args.volumes else []
    
    orch_module.orchestrator.create_service(
        name=args.name,
        image=args.image,
        desired_replicas=args.replicas,
        ports=ports,
        environment=environment,
        volumes=volumes,
        health_check_path=args.health_check
    )
    print(f"Service '{args.name}' created successfully")

def scale_service(args):
    """Scale a service"""
    orch_module.orchestrator.scale_service(args.name, args.replicas)
    print(f"Service '{args.name}' scaled to {args.replicas} replicas")

def delete_service(args):
    """Delete a service"""
    orch_module.orchestrator.delete_service(args.name)
    print(f"Service '{args.name}' deleted successfully")

def list_services(args):
    """List all services"""
    services = orch_module.orchestrator.get_service_status()
    
    if not services:
        print("No services found")
        return
    
    print(f"{'Service':<20} {'Image':<30} {'Desired':<8} {'Running':<8} {'Healthy':<8}")
    print("-" * 80)
    
    for service in services:
        running = len([i for i in service['instances'] if i['status'] == 'running'])
        healthy = len([i for i in service['instances'] if i['health_status'] == 'healthy'])
        
        print(f"{service['name']:<20} {service['image']:<30} {service['desired_replicas']:<8} {running:<8} {healthy:<8}")

def show_service(args):
    """Show detailed service information"""
    services = orch_module.orchestrator.get_service_status(args.name)
    
    if not services:
        print(f"Service '{args.name}' not found")
        return
    
    service = services[0]
    print(f"Service: {service['name']}")
    print(f"Image: {service['image']}")
    print(f"Desired Replicas: {service['desired_replicas']}")
    print(f"Ports: {json.dumps(service['ports'], indent=2)}")
    print(f"Instances:")
    
    if not service['instances']:
        print("  No instances")
        return
    
    for instance in service['instances']:
        print(f"  - {instance['instance_id']}")
        print(f"    Server: {instance['server_name']} ({instance['server_ip']})")
        print(f"    Status: {instance['status']}")
        print(f"    Health: {instance['health_status']}")
        print(f"    Port: {instance['port']}")
        print()

def health_check(args):
    """Run health check on all instances"""
    orch_module.orchestrator.health_check_instances()
    print("Health check completed")

def generate_nginx(args):
    """Generate Nginx configuration"""
    config = orch_module.orchestrator.generate_nginx_config()
    if args.output:
        with open(args.output, 'w') as f:
            f.write(config)
        print(f"Nginx configuration written to {args.output}")
    else:
        print(config)

def reload_nginx(args):
    """Reload Nginx configuration"""
    success = orch_module.orchestrator.reload_nginx()
    if success:
        print("Nginx reloaded successfully")
    else:
        print("Failed to reload Nginx")

def init_orchestrator(args):
    """Initialize orchestrator tables"""
    database.init_db()
    orch_module.orchestrator.init_orchestrator_tables()
    print("Orchestrator initialized successfully")

def main():
    parser = argparse.ArgumentParser(description='App Orchestrator CLI')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Init command
    init_parser = subparsers.add_parser('init', help='Initialize orchestrator')
    init_parser.set_defaults(func=init_orchestrator)
    
    # Create service command
    create_parser = subparsers.add_parser('create', help='Create a new service')
    create_parser.add_argument('name', help='Service name')
    create_parser.add_argument('image', help='Docker image')
    create_parser.add_argument('--replicas', type=int, default=1, help='Desired replicas')
    create_parser.add_argument('--ports', help='Port mappings (JSON)')
    create_parser.add_argument('--environment', help='Environment variables (JSON)')
    create_parser.add_argument('--volumes', help='Volume mappings (JSON array)')
    create_parser.add_argument('--health-check', default='/health', help='Health check path')
    create_parser.set_defaults(func=create_service)
    
    # Scale service command
    scale_parser = subparsers.add_parser('scale', help='Scale a service')
    scale_parser.add_argument('name', help='Service name')
    scale_parser.add_argument('replicas', type=int, help='Desired replicas')
    scale_parser.set_defaults(func=scale_service)
    
    # Delete service command
    delete_parser = subparsers.add_parser('delete', help='Delete a service')
    delete_parser.add_argument('name', help='Service name')
    delete_parser.set_defaults(func=delete_service)
    
    # List services command
    list_parser = subparsers.add_parser('list', help='List all services')
    list_parser.set_defaults(func=list_services)
    
    # Show service command
    show_parser = subparsers.add_parser('show', help='Show service details')
    show_parser.add_argument('name', help='Service name')
    show_parser.set_defaults(func=show_service)
    
    # Health check command
    health_parser = subparsers.add_parser('health', help='Run health check')
    health_parser.set_defaults(func=health_check)
    
    # Generate Nginx config command
    nginx_parser = subparsers.add_parser('nginx', help='Generate Nginx configuration')
    nginx_parser.add_argument('--output', '-o', help='Output file (default: stdout)')
    nginx_parser.set_defaults(func=generate_nginx)
    
    # Reload Nginx command
    reload_parser = subparsers.add_parser('reload', help='Reload Nginx')
    reload_parser.set_defaults(func=reload_nginx)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        args.func(args)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()