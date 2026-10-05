"""Configuration settings for AI-SwAutoMorph"""
import os
import subprocess
import logging

# PostgreSQL configuration
def get_database_config():
    """Get PostgreSQL database configuration"""
    return {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', 5432)),
        'database': os.environ.get('POSTGRES_DB', 'ai_swautomorph'),
        'user': os.environ.get('POSTGRES_USER', 'swautomorph'),
        'password': os.environ.get('POSTGRES_PASSWORD', 'swautomorph_password'),
        'min_connections': int(os.environ.get('POSTGRES_MIN_CONN', 2)),
        'max_connections': int(os.environ.get('POSTGRES_MAX_CONN', 20)),
        'sslmode': os.environ.get('POSTGRES_SSLMODE', 'prefer'),
        'connect_timeout': int(os.environ.get('POSTGRES_TIMEOUT', 10))
    }

# Path configuration functions
def get_logs_dir():
    """Get logs directory path"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'logs')

# Configure logging for genai activities
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(get_logs_dir(), os.path.basename(__file__).replace('.py', '.log'))),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Name of print logs output file
OUTPUT_PRINT_LOGS_FILENAME = 'print_output_swautomorph.log'

# Flask configuration
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
FLASK_ENV = os.environ.get('FLASK_ENV', 'development')

# Platform name from deploy.ini
def get_platform_name():
    """Get platform name from deploy.ini"""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'conf', 'deploy.ini')
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith('PLTF_NAME'):
                    return line.split('=', 1)[1].strip().strip("'\"")
    except Exception as e:
        logger.error(f'Failed to read PLTF_NAME from deploy.ini: {e}')
    return 'AI-SwAutoMorph'

# Platform folder name from deploy.ini
def get_platform_folder():
    """Get platform folder name from deploy.ini"""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'conf', 'deploy.ini')
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith('PLTF_FOLDER'):
                    return line.split('=', 1)[1].strip().strip("'\"")
    except Exception as e:
        logger.error(f'Failed to read PLTF_FOLDER from deploy.ini: {e}')
    # Canonical fallback, matching gunicorn.conf.py, deployControlPlan.sh,
    # start_app.sh and scripts/*.sh. Only used when deploy.ini is unreadable.
    return 'agentic-ai-plateform'

# Domain name from deploy.ini
def get_domain_name():
    """Get domain name from deploy.ini"""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'conf', 'deploy.ini')
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith('DOMAIN'):
                    return line.split('=', 1)[1].strip().strip("'\"")
    except Exception as e:
        logger.error(f'Failed to read DOMAIN from deploy.ini: {e}')
    return 'softfluid.fr'


# Version from deploy.ini
def get_version():
    """Get version from deploy.ini"""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'conf', 'deploy.ini')
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith('VERSION'):
                    return line.split('=', 1)[1].strip().strip("'\"")
    except Exception as e:
        logger.error(f'Failed to read VERSION from deploy.ini: {e}')
    return '0.0.1'


# Linux installation user from deploy.ini
def get_linux_user():
    """Get Linux installation user from deploy.ini"""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'conf', 'deploy.ini')
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith('LINUX_USER_INSTALLATION'):
                    value = line.split('=', 1)[1].strip().strip("'\"")
                    if value:
                        return value
    except Exception as e:
        logger.error(f'Failed to read LINUX_USER_INSTALLATION from deploy.ini: {e}')
    return 'psmc'


PLTF_NAME = get_platform_name()
PLTF_FOLDER = get_platform_folder()
DOMAIN = get_domain_name()
APP_VERSION = get_version()
LINUX_USER_INSTALLATION = get_linux_user()

# CORS configuration
CORS_ORIGINS = [
    f'https://wwww.{DOMAIN}', 
    f'https://*.{DOMAIN}',
]

# Timeouts
TIMEOUT_GITEA_HTTP_POST=30
TIMEOUT_SUBPROCESS_RUN=600
TIMEOUT_request_dev_ai_for_app_RUN=1800
TIMEOUT_CLEAN_SHUTDOWN=60
TIMEOUT_QCHAT_OPERATOR_RUN=1800
AI_ENGINE='kiro-cli'

# Path configuration functions
def get_logs_dir():
    """Get logs directory path"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'logs')

def get_qchat_paths():
    """Get qchat command paths to search"""
    home_dir = os.path.expanduser('~')
    qchat_cmd = None
    qchat_paths = [
        os.path.join(home_dir, '.local', 'bin', 'qchat'),
        '/usr/local/bin/qchat',
        '/usr/bin/qchat',
        'qchat',
        os.path.join(home_dir, '.local', 'bin', 'kiro-cli'),
        '/usr/local/bin/kiro-cli',
        '/usr/bin/kiro-cli',
        'kiro-cli'
    ]
    for path in qchat_paths:
        try:
            result = subprocess.run([path, '--version'], capture_output=True, timeout=TIMEOUT_SUBPROCESS_RUN)
            if result.returncode == 0:
                qchat_cmd = path
                break
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError, FileNotFoundError) as e:
            logger.error(f'AI Chat Developer - Failed to check kiro-cli at {path}: {str(e)}')
            continue
        except Exception as e:
            logger.error(f'AI Chat Developer - Unexpected error checking kiro-cli at {path}: {str(e)}')
            continue
    return qchat_cmd

def get_shai_paths():
    """Get shai command path"""
    home_dir = os.path.expanduser('~')
    qchat_paths = [
        os.path.join(home_dir, '.local', 'bin', 'shai'),
        f'/home/{LINUX_USER_INSTALLATION}/.local/bin/shai',
        '/usr/local/bin/shai',
        '/usr/bin/shai',
        'shai'
    ]
    for path in qchat_paths:
        try:
            result = subprocess.run([path, '--version'], capture_output=True, timeout=TIMEOUT_SUBPROCESS_RUN)
            if result.returncode == 0:
                qchat_cmd = path
                break
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError, FileNotFoundError) as e:
            logger.error(f'AI Chat Developer - Failed to check SHAI at {path}: {str(e)}')
            continue
        except Exception as e:
            logger.error(f'AI Chat Developer - Unexpected error checking SHAI at {path}: {str(e)}')
            continue
    return qchat_cmd

# Language translations
TRANSLATIONS = {
    'en': {
        'login': 'Login',
        'register': 'Register',
        'username': 'Username',
        'email': 'Email',
        'password': 'Password',
        'first_name': 'First Name',
        'last_name': 'Last Name',
        'dashboard': 'Dashboard',
        'logout': 'Logout',
        'welcome': 'Welcome',
        'used_applications': '📋 Authorized Applications',
        'available_applications': '📋 Available Applications',
        'assigned_applications': '📋 Assigned Applications',
        'add_new_application': 'Add New Application',
        'application_name': 'Application Name',
        'url': 'URL',
        'description': 'Description',
        'add_application': 'Add Application',
        'no_apps': 'No applications available yet. Contact the administrator of the web site to authorize the use of applications.',
        'already_account': 'Already have an account?',
        'no_account': "Don't have an account?",
        'login_here': 'Login here',
        'register_here': 'Register here',
        'open_application': 'Open Application',
        'no_description': 'No description available',
        'app_is_running': 'App. is running',
        'app_is_not_running': 'App. is not running',
        'first_clone': 'Clone to be done',
        'clone': 'Clone',
        'reclone': 'Clone again',
        'not_cloned': 'Not Cloned',
        'start': 'Start',
        'stop': 'Stop',
        'restart': 'Restart',
        'status': 'Status',
        'logs': 'Logs',
        'start_app': 'Start Application',
        'stop_app': 'Stop Application',
        'backup_db': 'Backup DB',
        'restore_db': 'Restore DB',
        'deployment_logs': 'Deployment Logs',
        'clear_logs': 'Clear Logs',
        'hide': 'Hide',
        'select_application': 'Select Application',
        'qchat_title': 'AI Chat - GenAI Assistant to modify the code of the selected Application',
        'auto_approve': 'Auto-approve updates/writes',
        'send': 'Send',
        'qchat_placeholder': 'Type your message to AI Chat...',
        'cancel': 'Cancel',
        'edit': 'Edit',
        'delete': 'Delete',
        'users': 'Users',
        'applications': 'Applications',
        'qchat_ready': 'Your virtual developer assistant is waiting for you! Ask it for a modification to the selected software, for example: add the ability to clock in multiple times per day in the ai-haccp software.',
        'platform_subtitle': 'The Future of Software Development is Here',
        'mission_statement': 'Welcome to the next evolution of GenAI impact. After replacing IT developers, <strong>agentic AI will now replace entire IT companies</strong> that develop software.',
        'target_title': 'Built for Forward-Thinking Businesses',
        'restaurants_title': 'Restaurants & Hospitality',
        'restaurants_desc': 'Manage your digital ecosystem with AI-powered virtual developers',
        'small_business_title': 'Small Businesses',
        'small_business_desc': 'Get enterprise-level software development without the enterprise costs',
        'entrepreneurs_title': 'Entrepreneurs',
        'entrepreneurs_desc': 'Transform ideas into running applications through natural language',
        'features_title': 'What You Get',
        'virtual_devs_title': 'Virtual AI Developers',
        'virtual_devs_desc': 'Chat with AI agents to modify, deploy, and manage your applications',
        'realtime_updates_title': 'Real-time Code Updates',
        'realtime_updates_desc': 'Request changes in plain English, watch them happen instantly',
        'auto_deploy_title': 'Automated Deployment',
        'auto_deploy_desc': 'From code to production in minutes, not months',
        'multi_app_title': 'Multi-App Management',
        'multi_app_desc': 'Control multiple applications from one collaborative dashboard',
        'revolution_message': 'The software development industry as we know it is about to change forever. Get ready to get wet - the wave of agentic AI is here.',
        'all_rights_reserved': 'All rights reserved.',
        'developed_by': 'Developed by',
        'with_help_of': 'tested by',
        'and': 'and',
        'virtual_advisor_toggle': 'My Virtual Operations Team : ask them to START / STOP / PS / RESTART / LOGS',
        'virtual_developer_toggle': 'My Virtual Developer: ask him to modify the application',
        'platform_subtitle': 'Centralized Application Deployment & Management Platform',
        'mission_statement': 'Enable GenAI agents to autonomously deploy, manage, and access web applications without human intervention.',
        'built_for_title': 'Built For',
        'genai_agents': 'GenAI Agents',
        'genai_agents_desc': 'Autonomous application deployment and management',
        'developers': 'Developers',
        'developers_desc': 'Streamlined deployment with virtual AI assistants',
        'operations_teams': 'Operations Teams',
        'operations_teams_desc': 'Multi-server deployment with automated lifecycle management',
        'key_features': 'Key Features',
        'virtual_agents': 'My Virtual IT Team Agents',
        'virtual_agents_desc': 'AI Developer & Operations assistants for code and deployment',
        'app_lifecycle': 'Application Lifecycle',
        'app_lifecycle_desc': 'CLONE, START, STOP, RESTART, PS, LOGS management',
        'sso_auth': 'SSO Authentication',
        'sso_auth_desc': 'Token-based authentication with Gitea integration',
        'multi_server': 'Multi-Server Support',
        'multi_server_desc': 'Capacity-based server allocation and management',
        'billing_tracking': 'Billing & Cost Tracking',
        'billing_tracking_desc': 'Usage monitoring with automated cost calculation',
        'security': 'Security',
        'security_desc': 'ModSecurity WAF protection with OWASP CRS rules',
        'multiple_interfaces': 'Multiple Interfaces',
        'multiple_interfaces_desc': 'Web Dashboard, CLI, REST API, MCP Protocol',
        'revolution_message': 'Autonomous application deployment for the AI-driven future',
        'multi_server_short': 'Multi-Server',
        'sso_short': 'SSO',
        'virtual_agents_short': 'Virtual Agents',
        'billing_short': 'Billing',
        'waf_protected': 'WAF Protected',
        'servers': 'Servers',
        'billing': 'Billing',
        'database': 'Database',
        'deployment_logs': 'Deployment Logs',
        'app_identity': 'APPLICATION IDENTITY',
        'github_repo_url': 'Github Official Readonly Repository URL',
        'edit_application': 'Edit Application',
        'update_application': 'Update Application',
        'application_details': 'Application Details',
        'close': 'Close',
        'billing_management': 'Billing Management',
        'period': 'Period',
        'today': 'Today',
        'this_week': 'This Week',
        'this_month': 'This Month',
        'overview': 'Overview',
        'invoices': 'Invoices',
        'manage_costs': 'Manage Costs',
        'application_costs': 'Application Costs',
        'usage_summary': 'Usage Summary',
        'activity_log': 'Activity Log',
        'loading': 'Loading...',
        'add_user': 'Add User',
        'add_new_user': 'Add New User',
        'create_user': 'Create User',
        'edit_user': 'Edit User',
        'update_user': 'Update User',
        'manage_applications_for': 'Manage Applications for',
        'server_management': 'Server Management',
        'add_server': 'Add Server',
        'invite_server': 'Invite Server',
        'loading_servers': 'Loading servers...',
        'add_new_server': 'Add New Server',
        'server_ip': 'Server IP',
        'server_name': 'Server Name',
        'max_users': 'Max Users',
        'max_applications': 'Max Applications',
        'server_type': 'Server Type',
        'create_server': 'Create Server',
        'edit_server': 'Edit Server',
        'update_server': 'Update Server',
        'database_management': 'Database Management',
        'select_table': 'Select Table',
        'select_table_option': '-- Select Table --',
        'auth_tokens': 'Auth Tokens',
        'user_applications_ports': 'User Applications',
        'deployments_management': 'Deployments Management',
        'application_costs': 'Application Costs',
        'billing_activities': 'Billing Activities',
        'users_logs': 'Users Logs',
        'refresh': 'Refresh',
        'add_record': 'Add Record',
        'select_table_view_data': 'Select a table to view data',
        'add_new_record': 'Add New Record',
        'save': 'Save',
        'edit_record': 'Edit Record',
        'update': 'Update',
        'ready_deployment_commands': 'Ready for deployment commands...',
        'developer': 'Developer',
        'operations': 'Operations',
        'virtual_developer': 'Virtual Developer',
        'select_application': 'Select Application',
        'select_application_option': '-- Select Application --',
        'describe_changes_placeholder': 'Describe what changes you want the AI to make to the code...',
        'auto_approve': 'Auto Approve',
        'virtual_operations': 'Virtual Operator',
        'ask_question_placeholder': 'Ask your question or describe what you need...',
        'deployment_status': 'Deployment Status',
        'automorph_session': 'Automorph Session',
        'instructions_ai_agent': 'Instructions for AI Agent',
        'describe_changes_ai_placeholder': 'Describe what changes you want the AI to make to the code...',
        'interactive_session': 'Interactive Session',
        'step_by_step_interaction': 'Check this for step-by-step interaction with the AI agent',
        'start_automorph': 'Start Automorph',
        'replace_it_team': 'Replace Your IT Team with AI Agents',
        'stop_waiting_message': 'Stop waiting for developers and IT support. Our AI agents handle everything - from coding new features to deploying and managing your applications. No more tickets, no more delays, no more expensive IT contracts.',
        'what_ai_agents_do': 'What AI Agents Do For You',
        'ai_developer_desc': 'Modifies your app code instantly based on your requests in plain English',
        'ai_operations_desc': 'Deploys, starts, stops, and monitors your applications 24/7',
        'instant_results': 'Instant Results',
        'instant_results_desc': 'Changes happen in minutes, not weeks or months',
        'why_choose_ai': 'Why Choose AI Over Human IT',
        'cost_savings': 'Cost Savings',
        'cost_savings_desc': 'No salaries, no benefits, no training costs',
        'availability_247': '24/7 Availability',
        'availability_247_desc': 'AI agents never sleep, take breaks, or go on vacation',
        'instant_response': 'Instant Response',
        'instant_response_desc': 'No waiting in ticket queues or scheduling meetings',
        'perfect_execution': 'Perfect Execution',
        'perfect_execution_desc': 'No human errors, consistent quality every time',
        'unlimited_scalability': 'Unlimited Scalability',
        'unlimited_scalability_desc': 'Handle multiple projects simultaneously',
        'always_learning': 'Always Learning',
        'always_learning_desc': 'AI agents improve with every interaction',
        'disruption_warning': "The IT industry is being disrupted RIGHT NOW. Companies using AI agents are moving 10x faster than those still relying on human IT teams. Don't get left behind. !!! You can implement ai-powered-store platform on your own environment !!!",
        'configuration': 'Configuration',
        'user_management': 'User Management',
        'server_management': 'Server Management',
        'applications_management': 'Applications Management',
        'database_management': 'Database Management',
        'virtual_agents_ready': 'Virtual Agents ready. Select an application and action to get started.',
        'specify_context_option': '📝 SPECIFY an AI context',
        'modify_code_option': '👨💻 MODIFY the App. (IT Dev)',
        'start_app_option': '▶️ START the App. (IT Ops)',
        'stop_app_option': '⏹️ STOP the App. (IT Ops)',
        'display_logs_option': '📋 DISPLAY logs of the App. (IT Ops)',
        'display_ps_option': '🔍 VERIFY status of the App. (IT Ops)',
        'account_activation_message_title': '⚠️ Account Activation Required',
        'account_activation_message_body': 'Your account will not be activated by default. It will be activated by AUTOMORPH since the usage generates costs.',
        'specify_context_request1': 'I need help to write a detailed specification for modifying the application',
        'specify_context_request2': 'Please, hereafter is my brief description of what needs to be changed:',
        'dev_modify_code_request1': 'I need a developer specialist to modify the code of the application',
        'dev_modify_code_request2': 'Please, hereafter is the specification of the request :',
        'ops_exec_request1': 'I need an operations specialist to execute the',
        'ops_exec_request2': 'action on the application',
        'select_app_tooltip': 'Select an application on which you want to ask the virtual IT specialists to perform an action',
        'replication_queue': 'Replication Synchronization Queue between servers PRIMARY and SECONDARY',
        'gitea_branch': 'Gitea Branch',
        'local_active_version': 'Local Active Version',
        'orchestrator': 'Applications Orchestrator',
        'confirm_password': 'Confirm password',
        'username_hint': 'Letters (a-z, A-Z), digits (0-9) only. No spaces or special characters.',
        'password_match': '✓ password match',
        'password_do_not_match': '✗ password do not match',
        'account_pending_activation': 'Your account is pending activation. Please wait for the administration team to activate your account and try again later.',
        'invalid_credentials': 'Invalid username or password.',
        'loading_available_apps': 'Loading available applications...',
        'error_loading_apps': 'Error',
        'failed_load_available_apps': 'Failed to load available applications',
        'all_apps_assigned': 'All available applications have been assigned to you.',
        'not_assigned_contact_admin': 'Not assigned - Contact your administrator to request access',
        'view_details': 'View Details',
        'access_required': 'Access Required',
        'access_required_message': 'This application has not been assigned to you. Please contact your administrator to request access.',
        'no_description_available': 'No description available',
        'repository': 'Repository',
        'account_security': 'Account Security',
        'change_password': 'Change Password',
        'change_password_desc': 'Change your password by entering your current password and a new one.',
        'current_password': 'Current Password',
        'new_password': 'New Password',
        'new_password_placeholder': 'Enter new password (min 6 characters)',
        'confirm_password_placeholder': 'Confirm new password',
        'reset_via_email': 'Reset via Email',
        'reset_password': 'Reset Password',
        'reset_password_for': 'Set a new password for',
        'password_reset_success': 'Password Reset Successful',
        'password_reset_success_message': 'Your password has been changed. You can now log in with your new password.',
        'two_factor_auth': 'Two-Factor Authentication (2FA)',
        'two_factor_auth_desc': 'Add an extra layer of security to your account by requiring a second verification step during login.',
        'authenticator_app': 'Authenticator App (TOTP)',
        'authenticator_app_desc': 'Use an app like Google Authenticator, Authy, or Microsoft Authenticator to generate time-based codes.',
        'setup_authenticator': 'Setup Authenticator App',
        'email_verification': 'Email Verification',
        'email_verification_desc': 'Receive a verification code via email each time you log in.',
        'enable_email_2fa': 'Enable Email 2FA',
        'disable_2fa': 'Disable 2FA',
        'disable_2fa_desc': 'Disabling 2FA will remove the extra security layer from your account.',
        'enter_password': 'Enter your password',
        'two_factor_verification': 'Two-Factor Verification',
        'verification_code': 'Verification Code',
        'verify': 'Verify',
        # Onboarding: Template Marketplace panel (Req 8.2-8.6)
        'marketplace': 'Template Marketplace',
        'marketplace_desc': 'Deploy a prebuilt application blueprint in one click.',
        'refresh': 'Refresh',
        'template': 'Template',
        'app_type': 'Type',
        'ports': 'Ports',
        'resources': 'Resources',
        'deploy': 'Deploy',
        'loading_templates': 'Loading templates...',
        'no_templates': 'No templates available.',
        'enter_application_name': 'Enter an application name',
        'deploying': 'Deploying...',
        'deploy_success': 'Application deployed',
        'deploy_failed': 'Deployment failed',
        'authentication_required': 'Authentication is required. Please sign in.',
        'access_url': 'Access URL',
        # Onboarding: Sandbox / Demo Mode panel (Req 1.6, 2.1, 2.2, 3.3)
        'sandbox': 'Sandbox / Demo Mode',
        'sandbox_desc': 'Provision, reset, or tear down a demo environment seeded with sample applications.',
        'sandbox_provision': 'Provision',
        'sandbox_reset': 'Reset',
        'sandbox_teardown': 'Teardown',
        'sandbox_status': 'Status',
        'sandbox_loading': 'Loading sandbox status...',
        'sandbox_none': 'No sandbox environment is present.',
        'sandbox_already_exists': 'A sandbox already exists. Run reset or teardown first.',
        'sandbox_seed_failed': 'Sandbox seeding failed; no partial applications remain.',
        'status_running': 'running',
        'status_stopped': 'stopped',
        'status_failed': 'failed'
    },
    'fr': {
        'login': 'Connexion',
        'register': 'Inscription',
        'username': "Nom utilisateur",
        'email': 'Email',
        'password': 'Mot de passe',
        'first_name': 'Prénom',
        'last_name': 'Nom',
        'dashboard': 'Tableau de bord',
        'logout': 'Déconnexion',
        'welcome': 'Bienvenue',
        'add_new_application': 'Ajouter une nouvelle application',
        'application_name': "Nom de l'application",
        'url': 'URL',
        'description': 'Description',
        'add_application': 'Ajouter une application',
        'no_apps': "Aucune application disponible pour le moment. Contactez l'administrateur du site pour autoriser l'utilisation d'applications",
        'already_account': 'Vous avez déjà un compte ?',
        'no_account': "Vous n'avez pas de compte ?",
        'login_here': 'Connectez-vous ici',
        'register_here': 'Inscrivez-vous ici',
        'open_application': "Application accessible",
        'no_description': 'Aucune description disponible',
        'app_is_not_running': 'Application arrêtée',
        'app_is_running': 'Application démarrée',
        'first_clone': 'A Cloner pour la première fois',
        'clone': 'A Cloner',
        'reclone': 're-Cloner',
        'not_cloned': 'Non encore cloné',
        'start': 'Démarrer',
        'stop': 'Arrêter',
        'restart': 'Redémarrer',
        'status': 'Statut',
        'logs': 'Journaux',
        'start_app': 'Application a démarrer',
        'stop_app': 'Application a arrêter',
        'backup_db': 'Sauvegarder BD',
        'restore_db': 'Restaurer BD',
        'deployment_logs': 'Journaux de déploiement',
        'clear_logs': 'Effacer les journaux',
        'hide': 'Masquer',
        'select_application': 'Sélectionner une application',
        'qchat_title': 'AI Chat - Assistant GenAI pour modifier le code du logiciel sélectionnée',
        'auto_approve': 'Approuver automatiquement les mises à jour/écritures',
        'send': 'Envoyer',
        'qchat_placeholder': 'Tapez votre message à AI Chat...',
        'cancel': 'Annuler',
        'edit': 'Modifier',
        'delete': 'Supprimer',
        'users': 'Utilisateurs',
        'applications': 'Applications',
        'qchat_ready': 'Votre assistant développeur virtuel vous attend ! Demandez-lui une modification pour le logiciel sélectionné, par exemple : ajoute la possibilité de pointer plusieurs fois par jour dans le logiciel ai-haccp.',
        'platform_subtitle': "L'Avenir du Développement Logiciel est Arrivé",
        'mission_statement': "Bienvenue dans la prochaine évolution de l'impact de l'IA générative. Après avoir remplacé les développeurs IT, <strong>l'IA agentique va maintenant remplacer des entreprises IT entières</strong> qui développent des logiciels.",
        'target_title': 'Conçu pour les Entreprises Visionnaires',
        'restaurants_title': 'Restaurants et Hôtellerie',
        'restaurants_desc': 'Gérez votre écosystème numérique avec des développeurs virtuels alimentés par l\'IA',
        'small_business_title': 'Petites Entreprises',
        'small_business_desc': "Obtenez un développement logiciel de niveau entreprise sans les coûts d'entreprise",
        'entrepreneurs_title': 'Entrepreneurs',
        'entrepreneurs_desc': "Transformez vos idées en applications fonctionnelles grâce au langage naturel",
        'features_title': 'Ce que Vous Obtenez',
        'virtual_devs_title': 'Développeurs IA Virtuels',
        'virtual_devs_desc': "Discutez avec des agents IA pour modifier, déployer et gérer vos applications",
        'realtime_updates_title': 'Mises à Jour de Code en Temps Réel',
        'realtime_updates_desc': 'Demandez des modifications en français simple, regardez-les se réaliser instantanément',
        'auto_deploy_title': 'Déploiement Automatisé',
        'auto_deploy_desc': 'Du code à la production en minutes, pas en mois',
        'multi_app_title': 'Gestion Multi-Applications',
        'multi_app_desc': 'Contrôlez plusieurs applications depuis un tableau de bord collaboratif',
        'revolution_message': "Une industrie du développement logiciel telle que nous la connaissons va changer à jamais. Préparez-vous à être mouillés - la vague de l'IA agentique est là.",
        'all_rights_reserved': 'Tous droits réservés.',
        'developed_by': 'Développé par',
        'with_help_of': 'testé par',
        'and': 'et',
        'virtual_advisor_toggle': 'La Team Ingénieurs Opérations virtuels : demandez-leur de START / STOP / PS / RESTART / LOGS',
        'virtual_developer_toggle': 'La Team Développeurs virtuels : demandez-leur de modifier le logiciel',
        'platform_subtitle': 'Plateforme Centralisée de Déploiement et Gestion du logiciel',
        'mission_statement': 'Permettre aux agents GenAI de déployer, gérer et accéder aux applications web de manière autonome sans intervention humaine.',
        'built_for_title': 'Conçu Pour',
        'genai_agents': 'Agents GenAI',
        'genai_agents_desc': 'Déploiement et gestion autonome du logiciel',
        'developers': 'Développeurs',
        'developers_desc': 'Déploiement simplifié avec assistants IA virtuels',
        'operations_teams': 'Équipes Opérations',
        'operations_teams_desc': 'Déploiement multi-serveurs avec gestion automatisée du cycle de vie',
        'key_features': 'Fonctionnalités Clés',
        'virtual_agents': 'Mes Informaticiens Virtuels',
        'virtual_agents_desc': 'Assistants IA Développeur et Opérations pour le code et le déploiement',
        'app_lifecycle': 'Cycle de Vie des Applications',
        'app_lifecycle_desc': 'Gestion CLONE, START, STOP, RESTART, PS, LOGS',
        'sso_auth': 'Authentification SSO',
        'sso_auth_desc': 'Authentification basée sur des tokens avec intégration Gitea',
        'multi_server': 'Support Multi-Serveurs',
        'multi_server_desc': 'Allocation et gestion de serveurs basée sur la capacité',
        'billing_tracking': 'Suivi de Facturation et Coûts',
        'billing_tracking_desc': 'Surveillance du usage avec calcul automatisé des coûts',
        'security': 'Sécurité',
        'security_desc': 'Protection ModSecurity WAF avec règles OWASP CRS',
        'multiple_interfaces': 'Interfaces Multiples',
        'multiple_interfaces_desc': 'Tableau de Bord Web, CLI, API REST, Protocole MCP',
        'revolution_message': 'Déploiement autonome du logiciel pour un avenir piloté par IA',
        'multi_server_short': 'Multi-Serveurs',
        'sso_short': 'SSO',
        'virtual_agents_short': 'Mes Informaticiens Virtuels',
        'billing_short': 'Facturation',
        'waf_protected': 'Protégé WAF',
        'servers': 'Serveurs',
        'billing': 'Facturation',
        'database': 'Base de Données',
        'deployment_logs': 'Journaux de Déploiement',
        'app_identity': 'IDENTITÉ APPLICATION',
        'github_repo_url': 'URL du Dépôt GitHub Officiel en Lecture Seule',
        'edit_application': 'Modifier mon application',
        'update_application': 'Mettre à Jour mon application',
        'application_details': 'Détails de mon application',
        'close': 'Fermer',
        'billing_management': 'Gestion de la Facturation',
        'period': 'Période',
        'today': "Aujourd'hui",
        'this_week': 'Cette Semaine',
        'this_month': 'Ce Mois',
        'manage_costs': 'Gérer les Coûts',
        'application_costs': 'Coûts des Applications',
        'usage_summary': 'Résumé du Usage',
        'activity_log': 'Journal des Activités',
        'loading': 'Chargement...',
        'add_user': 'Ajouter un Utilisateur',
        'add_new_user': 'Ajouter Nouvel Utilisateur',
        'create_user': 'Créer un Utilisateur',
        'edit_user': 'Modifier un Utilisateur',
        'update_user': 'Mettre à Jour Utilisateur',
        'manage_applications_for': 'Gérer les Applications pour',
        'used_applications': '📋 Applications Autorisées',
        'available_applications': '📋 Applications Disponibles',
        'assigned_applications': '📋 Applications Assignées',
        'server_management': 'Gestion des Serveurs',
        'applications_management': 'Gestion des Applications',
        'add_server': 'Ajouter un Serveur',
        'invite_server': 'Inviter un Serveur',
        'loading_servers': 'Chargement des serveurs...',
        'add_new_server': 'Ajouter Nouveau Serveur',
        'server_ip': 'IP du Serveur',
        'server_name': 'Nom du Serveur',
        'max_users': 'Utilisateurs Max',
        'max_applications': 'Applications Max',
        'server_type': 'Type de Serveur',
        'create_server': 'Créer Serveur',
        'edit_server': 'Modifier Serveur',
        'update_server': 'Mettre à Jour Serveur',
        'database_management': 'Gestion de la Base de Données',
        'select_table': 'Sélectionner Table',
        'select_table_option': '-- Sélectionner Table --',
        'auth_tokens': 'Tokens pour Authentification',
        'user_applications_ports': 'Applications Utilisateur',
        'deployments': 'Déploiements',
        'application_costs': 'Coûts des Applications',
        'billing_activities': 'Activités de Facturation',
        'users_logs': 'Journaux Utilisateurs',
        'refresh': 'Actualiser',
        'add_record': 'Ajouter Enregistrement',
        'select_table_view_data': 'Sélectionner une table pour voir les données',
        'add_new_record': 'Ajouter Nouvel Enregistrement',
        'save': 'Sauvegarder',
        'edit_record': 'Modifier Enregistrement',
        'update': 'Mettre à Jour',
        'ready_deployment_commands': 'Prêt pour les commandes de déploiement...',
        'developer': 'Développeur',
        'operations': 'Opérations',
        'virtual_developer': 'Développeur Virtuel',
        'select_application': 'Sélectionner une Application',
        'select_application_option': '-- Sélectionner une Application --',
        'describe_changes_placeholder': 'Décrivez les modifications que vous voulez que les IA apporte au code...',
        'auto_approve': 'Approbation Automatique',
        'virtual_operations': 'Opérateur Virtuel',
        'ask_question_placeholder': 'Posez votre question ou décrivez ce dont vous avez besoin...',
        'deployment_status': 'Statut de Déploiement',
        'automorph_session': 'Session Automorph',
        'instructions_ai_agent': 'Instructions pour votre Agent IA',
        'describe_changes_ai_placeholder': 'Décrivez les modifications que vous voulez que les IA apporte au code...',
        'interactive_session': 'Session Interactive',
        'step_by_step_interaction': 'Cochez ceci pour une interaction étape par étape avec votre agent IA',
        'start_automorph': 'Démarrer Automorph',
        'replace_it_team': 'Remplacez Votre Équipe IT par des Agents IA',
        'stop_waiting_message': "Arrêtez d'attendre les développeurs et le support IT. Nos agents IA gèrent tout - du codage de nouvelles fonctionnalités au déploiement et à la gestion de vos applications. Fini les tickets, les retards et les contrats IT coûteux.",
        'what_ai_agents_do': 'Ce que les Agents IA Font Pour Vous',
        'ai_developer_desc': 'Modifie le code de votre application instantanément selon vos demandes en français simple',
        'ai_operations_desc': 'Déploie, démarre, arrête et surveille vos applications 24h/24 et 7j/7',
        'instant_results': 'Résultats Instantanés',
        'instant_results_desc': 'Les changements se font en minutes, pas en semaines ou mois',
        'why_choose_ai': 'Pourquoi Choisir une IA Plutôt que les IT Humaines',
        'cost_savings': 'Économies de Coûts',
        'cost_savings_desc': 'Pas de salaires, ni avantages sociaux ou de coûts de formation',
        'availability_247': 'Disponibilité 24h/24 7j/7',
        'availability_247_desc': 'Les agents IA ne dorment jamais, ne prennent pas de pauses ou de vacances',
        'instant_response': 'Réponse Instantanée',
        'instant_response_desc': 'Aucune attente dans les files de tickets ou de planification de réunions',
        'perfect_execution': 'Exécution Parfaite',
        'perfect_execution_desc': 'Aucunes erreurs humaines, qualité constante à chaque fois',
        'unlimited_scalability': 'Évolutivité Illimitée',
        'unlimited_scalability_desc': 'Gérer plusieurs projets simultanément',
        'always_learning': 'Apprentissage Continu',
        'always_learning_desc': 'Les agents IA en auto amélioration à chaque interaction',
        'disruption_warning': "Une industrie IT est en cours de disruption MAINTENANT. Les entreprises utilisant des agents IA avancent 10 fois plus vite que celles qui dépendent encore d'équipes IT humaines. Ne vous laissez pas distancer. !!! Vous pouvez implémenter ai-powered-store dans votre environnement !!!",
        'configuration': 'Configuration',
        'user_management': 'Gestion des Utilisateurs',
        'server_management': 'Gestion des Serveurs',
        'database_management': 'Gestion de la Base de Données',
        'virtual_agents_ready': 'Agents Virtuels prêts. Sélectionnez une application et une action pour commencer.',
        'specify_context_option': '📝 SPÉCIFIER un contexte IA',
        'modify_code_option': "👨💻 MODIFIER mon application (Dév)",
        'start_app_option': "▶️ DÉMARRER mon application. (Ops)",
        'stop_app_option': "⏹️ ARRÊTER mon application. (Ops)",
        'display_logs_option': "📋 AFFICHER les logs de mon appli. (Ops)",
        'display_ps_option': "🔍 VERIFIER mon appli. (Ops)",
        'account_activation_message_title': '⚠️ Activation du compte nécessaire',
        'account_activation_message_body': 'Votre compte ne sera pas activé par défaut. Il sera activé par AUTOMORPH, puisque son utilisation génère des coûts.',
        'specify_context_request1': "J'ai besoin d'aide pour écrire une spécification détaillée pour modifier l'application",
        'specify_context_request2': 'Veuillez trouver ci-dessous ma brève description de ce qui doit être modifié :',
        'dev_modify_code_request1': "Je veux un spécialiste développeur pour modifier le code de mon application",
        'dev_modify_code_request2': 'Veuillez trouver ci-dessous la spécification de la demande :',
        'ops_exec_request1': "Je veux un spécialiste des opérations pour exécuter",
        'ops_exec_request2': "action sur mon application",
        'select_app_tooltip': "Selectionnez une application sur laquelle vous voulez demander aux informaticiens virtuels d'effectuer une action",
        'unified_input_tooltip': "Tapez en français ce que vous voulez demander à votre informaticien virtuel concernant les modifications à réaliser concernant l'application. Soyez précis, par exemple: modifie le numéro de téléphone qui s'affiche sur la page principale du site web 06 19 89 90 50 et remplace par 01 46 43 23 56",
        'replication_queue': "Queue/Liste pour la synchronisation entre le serveur PRIMAIRE et les SECONDAIRES",
        'gitea_branch': 'Branche Gitea',
        'local_active_version': 'Version Active Locale',
        'orchestrator': 'Applications Orchestrateur',
        'confirm_password': 'Confirmation du mot de passe',
        'username_hint': 'Lettres (a-z, A-Z) et chiffres (0-9) uniquement. Pas d\'espaces ni de caractères spéciaux.',
        'password_match': '✓ le mot de passe correspond',
        'password_do_not_match': '✗ le mot de passe ne correspond pas',
        'account_pending_activation': "Votre compte est en attente d'activation. Veuillez attendre que l'équipe d'administration active votre compte et réessayez plus tard.",
        'invalid_credentials': "Nom d'utilisateur ou mot de passe invalide.",
        'loading_available_apps': 'Chargement des applications disponibles...',
        'error_loading_apps': 'Erreur',
        'failed_load_available_apps': 'Échec du chargement des applications disponibles',
        'all_apps_assigned': 'Toutes les applications disponibles vous ont été assignées.',
        'not_assigned_contact_admin': 'Non assignée - Contactez votre administrateur pour demander l\'accès',
        'view_details': 'Voir les détails',
        'access_required': 'Accès Requis',
        'access_required_message': 'Cette application ne vous a pas été assignée. Veuillez contacter votre administrateur pour demander l\'accès.',
        'no_description_available': 'Aucune description disponible',
        'repository': 'Dépôt',
        'account_security': 'Sécurité du Compte',
        'change_password': 'Changer le Mot de Passe',
        'change_password_desc': 'Changez votre mot de passe en entrant votre mot de passe actuel et un nouveau.',
        'current_password': 'Mot de passe actuel',
        'new_password': 'Nouveau mot de passe',
        'new_password_placeholder': 'Entrez le nouveau mot de passe (min 6 caractères)',
        'confirm_password_placeholder': 'Confirmez le nouveau mot de passe',
        'reset_via_email': 'Réinitialiser par Email',
        'reset_password': 'Réinitialiser le Mot de Passe',
        'reset_password_for': 'Définir un nouveau mot de passe pour',
        'password_reset_success': 'Mot de Passe Réinitialisé',
        'password_reset_success_message': 'Votre mot de passe a été changé. Vous pouvez maintenant vous connecter avec votre nouveau mot de passe.',
        'two_factor_auth': 'Authentification à Deux Facteurs (2FA)',
        'two_factor_auth_desc': "Ajoutez une couche de sécurité supplémentaire à votre compte en exigeant une deuxième étape de vérification lors de la connexion.",
        'authenticator_app': 'Application Authenticator (TOTP)',
        'authenticator_app_desc': "Utilisez une application comme Google Authenticator, Authy ou Microsoft Authenticator pour générer des codes temporels.",
        'setup_authenticator': "Configurer l'Application Authenticator",
        'email_verification': 'Vérification par Email',
        'email_verification_desc': 'Recevez un code de vérification par email à chaque connexion.',
        'enable_email_2fa': 'Activer 2FA par Email',
        'disable_2fa': 'Désactiver 2FA',
        'disable_2fa_desc': 'Désactiver la 2FA supprimera la couche de sécurité supplémentaire de votre compte.',
        'enter_password': 'Entrez votre mot de passe',
        'two_factor_verification': 'Vérification à Deux Facteurs',
        'verification_code': 'Code de Vérification',
        'verify': 'Vérifier',
        # Onboarding: Marketplace de modèles (Req 8.2-8.6)
        'marketplace': 'Marketplace de modèles',
        'marketplace_desc': "Déployez un modèle d'application prédéfini en un clic.",
        'refresh': 'Actualiser',
        'template': 'Modèle',
        'app_type': 'Type',
        'ports': 'Ports',
        'resources': 'Ressources',
        'deploy': 'Déployer',
        'loading_templates': 'Chargement des modèles...',
        'no_templates': 'Aucun modèle disponible.',
        'enter_application_name': "Saisissez un nom d'application",
        'deploying': 'Déploiement...',
        'deploy_success': 'Application déployée',
        'deploy_failed': 'Échec du déploiement',
        'authentication_required': 'Authentification requise. Veuillez vous connecter.',
        'access_url': "URL d'accès",
        # Onboarding: Mode Bac à sable / Démo (Req 1.6, 2.1, 2.2, 3.3)
        'sandbox': 'Bac à sable / Mode démo',
        'sandbox_desc': "Provisionnez, réinitialisez ou supprimez un environnement de démonstration avec des applications d'exemple.",
        'sandbox_provision': 'Provisionner',
        'sandbox_reset': 'Réinitialiser',
        'sandbox_teardown': 'Supprimer',
        'sandbox_status': 'État',
        'sandbox_loading': "Chargement de l'état du bac à sable...",
        'sandbox_none': "Aucun environnement bac à sable n'est présent.",
        'sandbox_already_exists': "Un bac à sable existe déjà. Exécutez d'abord réinitialiser ou supprimer.",
        'sandbox_seed_failed': "Échec de l'amorçage du bac à sable ; aucune application partielle ne subsiste.",
        'status_running': 'en cours',
        'status_stopped': 'arrêté',
        'status_failed': 'échoué'
    }
}


# Pure path/command helpers for the configurable Linux installation user.
# These are side-effect-free string builders consumed with LINUX_USER_INSTALLATION.
def home_path(user, *suffix_parts):
    """Build /home/<user>/<suffix...>.

    Joins the given suffix parts under the user's home directory using '/'.
    With no suffix parts, returns '/home/<user>'.
    """
    base = f'/home/{user}'
    parts = [str(part).strip('/') for part in suffix_parts if str(part) != '']
    if parts:
        return base + '/' + '/'.join(parts)
    return base


def deployments_prefix(user):
    """Return the deployments path prefix '/home/<user>/deployments/'."""
    return f'/home/{user}/deployments/'


def ssh_target(user, host):
    """Return an SSH target of the form '<user>@<host>'."""
    return f'{user}@{host}'


def chown_arg(user):
    """Return an ownership argument of the form '<user>:<user>'."""
    return f'{user}:{user}'


def is_under_deployments(user, path):
    """Return True iff path is under the user's deployments prefix and safe.

    True only when path starts with deployments_prefix(user) and contains no
    '..' path traversal component.
    """
    return path.startswith(deployments_prefix(user)) and '..' not in path
