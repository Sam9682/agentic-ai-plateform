#!/usr/bin/env python3
"""MCP Server for AI-SwAutoMorph"""
import json
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
from typing import Any, Dict, List
import asyncio
import sys
import os

# Add the parent directory to the path so we can import from src
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database_postgres import db_manager
from src.template_catalog import TemplateCatalog
from src.template_deploy import TemplateDeployService
from src.orchestrator import orchestrator

class MCPServer:
    def __init__(self, db_path: str = 'softfluid/db/ai_swautomorph.db'):
        self.db_path = db_path
        self.tools = {
            'list_applications': self.list_applications,
            'add_application': self.add_application,
            'get_user_info': self.get_user_info,
            'list_users': self.list_users,
            'deploy_template': self.deploy_template
        }
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP request"""
        method = request.get('method')
        params = request.get('params', {})
        
        if method == 'tools/list':
            return {
                'tools': [
                    {
                        'name': 'list_applications',
                        'description': 'List all available applications',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {}
                        }
                    },
                    {
                        'name': 'add_application',
                        'description': 'Add a new application',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'name': {'type': 'string'},
                                'url': {'type': 'string'},
                                'description': {'type': 'string'}
                            },
                            'required': ['name', 'url']
                        }
                    },
                    {
                        'name': 'list_users',
                        'description': 'List all registered users',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {}
                        }
                    },
                    {
                        'name': 'deploy_template',
                        'description': 'Deploy an application from a Deploy Template blueprint',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'template_id': {'type': 'string'},
                                'application_name': {'type': 'string'},
                                'user_id': {'type': 'integer'}
                            },
                            'required': ['template_id', 'application_name', 'user_id']
                        }
                    }
                ]
            }
        
        elif method == 'tools/call':
            tool_name = params.get('name')
            arguments = params.get('arguments', {})
            
            if tool_name in self.tools:
                try:
                    result = await self.tools[tool_name](**arguments)
                    return {'content': [{'type': 'text', 'text': json.dumps(result, indent=2)}]}
                except Exception as e:
                    return {'error': str(e)}
            else:
                return {'error': f'Unknown tool: {tool_name}'}
        
        return {'error': 'Unknown method'}
    
    async def list_applications(self) -> List[Dict[str, Any]]:
        """List all applications"""
        # conn = sqlite3.connect(self.db_path)  # COMMENTED OUT - Using PostgreSQL now
        # cursor = conn.cursor()
        # cursor.execute('SELECT id, name, url, description FROM applications ORDER BY name')
        # apps = [{'id': row[0], 'name': row[1], 'url': row[2], 'description': row[3]} 
        #         for row in cursor.fetchall()]
        # conn.close()
        # return apps
        
        # Using PostgreSQL now
        try:
            result = db_manager.execute_query(
                'SELECT id, name, git_url, description FROM applications ORDER BY name',
                fetch_all=True
            )
            apps = [{'id': row[0], 'name': row[1], 'url': row[2], 'description': row[3]} 
                    for row in result] if result else []
            return apps
        except Exception as e:
            return [{'error': f'Database error: {str(e)}'}]
    
    async def add_application(self, name: str, url: str, description: str = '') -> Dict[str, str]:
        """Add a new application"""
        # conn = sqlite3.connect(self.db_path)  # COMMENTED OUT - Using PostgreSQL now
        # cursor = conn.cursor()
        # cursor.execute('INSERT INTO applications (name, url, description) VALUES (?, ?, ?)',
        #               (name, url, description))
        # conn.commit()
        # conn.close()
        # return {'message': 'Application added successfully'}
        
        # Using PostgreSQL now
        try:
            db_manager.execute_query(
                'INSERT INTO applications (name, git_url, description) VALUES (%s, %s, %s)',
                (name, url, description)
            )
            return {'message': 'Application added successfully'}
        except Exception as e:
            return {'error': f'Database error: {str(e)}'}
    
    async def list_users(self) -> List[Dict[str, Any]]:
        """List all users (without sensitive data)"""
        # conn = sqlite3.connect(self.db_path)  # COMMENTED OUT - Using PostgreSQL now
        # cursor = conn.cursor()
        # cursor.execute('SELECT id, username, email, first_name, last_name, created_at FROM users')
        # users = [{'id': row[0], 'username': row[1], 'email': row[2], 
        #          'first_name': row[3], 'last_name': row[4], 'created_at': row[5]} 
        #         for row in cursor.fetchall()]
        # conn.close()
        # return users
        
        # Using PostgreSQL now
        try:
            result = db_manager.execute_query(
                'SELECT id, username, email, first_name, last_name, created_at FROM users',
                fetch_all=True
            )
            users = [{'id': row[0], 'username': row[1], 'email': row[2], 
                     'first_name': row[3], 'last_name': row[4], 'created_at': row[5]} 
                    for row in result] if result else []
            return users
        except Exception as e:
            return [{'error': f'Database error: {str(e)}'}]

    async def deploy_template(self, template_id: str, application_name: str, user_id: int) -> Dict[str, Any]:
        """Deploy an application from a Deploy Template blueprint (Req 9.2, 9.4).

        Uses the shared TemplateDeployService so MCP deployments follow the exact
        same path as the Dashboard, CLI, and REST API. On an unknown template id
        the not-found error is returned up front and NO deployment is initiated
        (Req 9.4).
        """
        try:
            catalog = TemplateCatalog().load()

            # Unknown template id -> report not found and initiate no deployment (Req 9.4).
            if catalog.get(template_id) is None:
                return {'error': 'template not found', 'template_id': template_id}

            service = TemplateDeployService(catalog, orchestrator)
            result = service.deploy(template_id, application_name, user_id)

            if not result.success:
                return {
                    'error': result.message or 'deployment failed',
                    'error_code': result.error_code,
                    'template_id': template_id,
                }

            # Return the created deployment identifier (Req 9.2).
            return {
                'application_id': result.application_id,
                'access_url': result.access_url,
                'template_id': template_id,
            }
        except Exception as e:
            return {'error': f'Deployment error: {str(e)}'}

async def main():
    """Main MCP server loop"""
    server = MCPServer()
    
    print("MCP Server for AI-SwAutoMorph started")
    print("Available tools: list_applications, add_application, list_users")
    
    # Simple stdin/stdout MCP protocol
    while True:
        try:
            line = input()
            if not line:
                break
            
            request = json.loads(line)
            response = await server.handle_request(request)
            print(json.dumps(response))
        except (EOFError, KeyboardInterrupt):
            break
        except json.JSONDecodeError:
            print(json.dumps({'error': 'Invalid JSON'}))
        except Exception as e:
            print(json.dumps({'error': str(e)}))

if __name__ == '__main__':
    asyncio.run(main())