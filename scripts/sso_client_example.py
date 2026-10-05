#!/usr/bin/env python3
"""
Example SSO client implementation for external applications
This shows how AI HACCP or other applications can validate SSO tokens
"""

import requests
from flask import Flask, request, jsonify, session, redirect
from urllib.parse import parse_qs, urlparse

# SSO Identity Provider URL
SSO_PROVIDER_URL = 'http://www.swautomorph.com:80'

def validate_sso_token(token):
    """Validate SSO token with the identity provider"""
    try:
        response = requests.post(
            f'{SSO_PROVIDER_URL}/sso/validate',
            json={'token': token},
            timeout=5
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('valid'):
                return result.get('user')
        return None
    except requests.exceptions.RequestException:
        return None

# Example Flask application using SSO
app = Flask(__name__)
app.secret_key = 'example-app-secret'

@app.route('/')
def index():
    # Check for SSO token in URL parameters
    sso_token = request.args.get('sso_token')
    
    if sso_token:
        # Validate token with SSO provider
        user_info = validate_sso_token(sso_token)
        
        if user_info:
            # Store user info in session
            session['user_id'] = user_info['id']
            session['username'] = user_info['username']
            session['email'] = user_info['email']
            
            # Redirect to remove token from URL
            return redirect('/')
        else:
            return jsonify({'error': 'Invalid SSO token'}), 401
    
    # Check if user is already logged in
    if 'user_id' in session:
        return f"""
        <h1>Welcome to AI HACCP</h1>
        <p>Hello, {session['username']}!</p>
        <p>Email: {session['email']}</p>
        <a href="/logout">Logout</a>
        """
    else:
        return f"""
        <h1>AI HACCP - Please Login</h1>
        <p>Please login through the main portal:</p>
        <a href="{SSO_PROVIDER_URL}">Login via SwAutoMorph</a>
        """

@app.route('/logout')
def logout():
    session.clear()
    return redirect(f'{SSO_PROVIDER_URL}')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)