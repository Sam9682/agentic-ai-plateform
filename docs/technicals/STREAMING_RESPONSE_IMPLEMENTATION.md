# Streaming Response Implementation for Virtual DevOps Team

## Problem
Currently, the Virtual DevOps Team shows the response only after AI Chat completes execution. This can take several minutes, making users think the process is stuck.

## Solution Options

### Option 1: Server-Sent Events (SSE) - RECOMMENDED
Stream responses in real-time as AI Chat generates output.

**Pros**:
- Real-time streaming
- Shows progress as it happens
- Standard HTTP (no WebSocket needed)
- Works with existing Flask setup

**Cons**:
- Requires backend changes
- Need to modify AI Chat execution

### Option 2: Polling with Partial Results
Store partial results in database/cache and poll for updates.

**Pros**:
- Simpler implementation
- No streaming infrastructure needed

**Cons**:
- Not true real-time
- More database/cache operations
- Polling overhead

### Option 3: WebSocket
Full duplex communication for real-time updates.

**Pros**:
- True bidirectional real-time
- Efficient for continuous updates

**Cons**:
- More complex infrastructure
- Requires WebSocket server
- Overkill for this use case

## Recommended Implementation: SSE

### Backend Changes

#### 1. Create Streaming Endpoint (`src/routes/api_routes.py`)

```python
from flask import Response, stream_with_context
import json
import subprocess
import threading
import queue

@api_bp.route('/qchat_devops_stream', methods=['POST'])
def api_qchat_devops_stream():
    """Streaming version of qchat_devops"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.get_json()
    message = data.get('message', '').strip()
    application_name = data.get('application_name', '')
    application_folder = data.get('application_folder', '')
    
    if not message:
        return jsonify({'error': 'Message required'}), 400
    
    # Get user details
    user_details = db_manager.execute_query(
        'SELECT username, email, first_name, last_name FROM users WHERE id = ?', 
        (session['user_id'],), fetch_one=True
    )
    
    username = user_details[0] if user_details else 'user'
    user_email = user_details[1] if user_details else 'user@example.com'
    user_name = f"{user_details[2] or ''} {user_details[3] or ''}".strip() or 'User'
    description = f"Application: {application_name}, Path: {application_folder}" if application_name else ''
    
    def generate():
        """Generator function for streaming"""
        from ..automorph_application import process_qchat_devops_stream
        
        try:
            # Stream chunks from AI Chat
            for chunk in process_qchat_devops_stream(
                message,
                user_id=str(session['user_id']),
                user_name=user_name,
                user_email=user_email,
                description=description
            ):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )
```

#### 2. Create Streaming Function (`src/automorph_application.py`)

```python
def process_qchat_devops_stream(user_question: str, user_id: str = '0', 
                                   user_name: str = 'User', user_email: str = 'user@example.com', 
                                   description: str = ''):
    """
    Streaming version of process_qchat_devops
    Yields chunks of output as they arrive
    """
    import time
    import select
    
    start_time = time.time()
    
    # Detect action and load context (same as before)
    action_keywords = {
        'start': ['start', 'deploy', 'launch', 'run'],
        'stop': ['stop', 'shutdown', 'halt', 'terminate'],
        'restart': ['restart', 'reboot', 'reload'],
        'ps': ['status', 'ps', 'check', 'running'],
        'logs': ['logs', 'log', 'output', 'console']
    }
    
    detected_action = None
    question_lower = user_question.lower()
    
    for action, keywords in action_keywords.items():
        if any(keyword in question_lower for keyword in keywords):
            detected_action = action
            break
    
    # Load context if action detected
    if detected_action:
        context_file = f"/home/ubuntu/<PLTF_FOLDER>/shared/{detected_action.upper()}_context.md"
        
        if os.path.exists(context_file):
            with open(context_file, 'r') as f:
                context_template = f.read()
            
            context = context_template.replace('{USER_ID}', user_id)
            context = context.replace('{USER_NAME}', user_name)
            context = context.replace('{USER_EMAIL}', user_email)
            context = context.replace('{DESCRIPTION}', description)
            context = context.replace('{TAIL_LINES}', '100')
            
            app_folder = ''
            if 'Path:' in description:
                parts = description.split('Path:')
                if len(parts) > 1:
                    app_folder = parts[1].strip()
            
            prompt = f"""
You are an autonomous DevOps agent with access to execute shell commands on a Linux server.

The user has requested an application management action.

User Request: {user_question}

{'Application Folder: ' + app_folder if app_folder else ''}

Follow the instructions below to execute the {detected_action.upper()} action:

{context}

IMPORTANT: Execute all commands in the application folder: {app_folder if app_folder else '/home/ubuntu/deployments/[username]/[appname]'}

Execute all required steps and provide a clear summary of the results.
"""
        else:
            prompt = f"You are a helpful assistant. Answer: {user_question}"
    else:
        prompt = f"You are a helpful assistant. Answer: {user_question}"
    
    # Find qchat command
    qchat_paths = ['/usr/local/bin/qchat', '/usr/bin/qchat', 'qchat']
    qchat_cmd = None
    
    for path in qchat_paths:
        try:
            subprocess.run([path, '--version'], capture_output=True, timeout=5)
            qchat_cmd = path
            break
        except:
            continue
    
    if not qchat_cmd:
        yield {'error': 'AI Chat command not found', 'done': True}
        return
    
    # Execute AI Chat with streaming
    cmd_args = [qchat_cmd, 'chat']
    if detected_action:
        cmd_args.append('--trust-all-tools')
    cmd_args.append(prompt)
    
    qchat_env = os.environ.copy()
    qchat_env.update({
        'HOME': '/home/ubuntu',
        'USER': 'ubuntu',
        'PATH': '/usr/local/bin:/usr/bin:/bin:' + qchat_env.get('PATH', '')
    })
    
    try:
        # Start process with line buffering
        process = subprocess.Popen(
            cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=qchat_env
        )
        
        # Stream output line by line
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                # Strip ANSI codes
                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                clean_line = ansi_escape.sub('', line.rstrip())
                
                yield {
                    'chunk': clean_line,
                    'done': False
                }
        
        # Get any remaining stderr
        stderr = process.stderr.read()
        
        execution_time = time.time() - start_time
        
        yield {
            'done': True,
            'execution_time': round(execution_time, 2),
            'success': process.returncode == 0
        }
        
    except Exception as e:
        yield {
            'error': str(e),
            'done': True,
            'execution_time': round(time.time() - start_time, 2)
        }
```

### Frontend Changes (`templates/dashboard.html`)

```javascript
function sendVirtualAdvisorMessage() {
    const input = document.getElementById('virtualAdvisorInput');
    const message = input.value.trim();
    const selectedAction = document.getElementById('virtualAdvisorAction').value;
    const selectedApp = document.getElementById('virtualAdvisorAppSelect').value;
    
    if (!message) return;
    
    if (!selectedApp) {
        addVirtualAdvisorMessage('error', 'Please select an application before sending your request.');
        return;
    }
    
    const username = '{{ username }}';
    const userId = '{{ session.user_id }}';
    const appFolder = `/home/ubuntu/deployments/${username}/${selectedApp.toLowerCase().replace(/\s+/g, '-')}`;
    const fullMessage = `[${selectedAction}] [APP:${selectedApp}] [PATH:${appFolder}] ${message}`;
    
    addVirtualAdvisorMessage('user', `Application: ${selectedApp}`);
    addVirtualAdvisorMessage('user', `Action: ${selectedAction}`);
    addVirtualAdvisorMessage('user', message);
    input.value = '';
    
    // Create a message div for streaming response
    const messages = document.getElementById('virtualAdvisorMessages');
    const streamingDiv = document.createElement('div');
    streamingDiv.className = 'chat-message chat-assistant';
    streamingDiv.innerHTML = `
        <div class="message-header">
            <span class="message-icon">💡</span>
            <span class="message-time">${new Date().toLocaleTimeString()}</span>
        </div>
        <div class="message-content" id="streaming-content"></div>
    `;
    messages.appendChild(streamingDiv);
    messages.scrollTop = messages.scrollHeight;
    
    const streamingContent = document.getElementById('streaming-content');
    
    // Use EventSource for SSE
    const eventSource = new EventSource('/api/qchat_devops_stream?' + new URLSearchParams({
        message: fullMessage,
        application_name: selectedApp,
        application_folder: appFolder
    }));
    
    // Alternative: Use fetch with streaming
    fetch('/api/qchat_devops_stream', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            message: fullMessage,
            application_name: selectedApp,
            application_folder: appFolder
        })
    })
    .then(response => {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        function readStream() {
            reader.read().then(({done, value}) => {
                if (done) {
                    streamingContent.innerHTML += '<br><em>✅ Completed</em>';
                    messages.scrollTop = messages.scrollHeight;
                    return;
                }
                
                const chunk = decoder.decode(value, {stream: true});
                const lines = chunk.split('\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.substring(6));
                            
                            if (data.error) {
                                streamingContent.innerHTML += `<br><span style="color: red;">Error: ${data.error}</span>`;
                            } else if (data.chunk) {
                                streamingContent.innerHTML += data.chunk + '<br>';
                            } else if (data.done) {
                                streamingContent.innerHTML += `<br><em>⏱️ Execution time: ${data.execution_time}s</em>`;
                            }
                            
                            messages.scrollTop = messages.scrollHeight;
                        } catch (e) {
                            console.error('Parse error:', e);
                        }
                    }
                }
                
                readStream();
            });
        }
        
        readStream();
    })
    .catch(error => {
        streamingContent.innerHTML += `<br><span style="color: red;">Error: ${error.message}</span>`;
        console.error('Streaming error:', error);
    });
}
```

## Simpler Alternative: Progress Updates

If streaming is too complex, show periodic progress updates:

```javascript
function sendVirtualAdvisorMessage() {
    // ... existing code ...
    
    // Add progress indicator
    const progressDiv = addVirtualAdvisorMessage('system', '⏳ Processing...');
    
    // Update progress every 2 seconds
    const progressMessages = [
        '⏳ Analyzing request...',
        '🔄 Loading context...',
        '⚙️ Executing commands...',
        '📝 Generating response...',
        '✅ Almost done...'
    ];
    let progressIndex = 0;
    
    const progressInterval = setInterval(() => {
        if (progressIndex < progressMessages.length) {
            updateVirtualAdvisorMessage(progressDiv, progressMessages[progressIndex]);
            progressIndex++;
        }
    }, 3000);
    
    // Send request
    fetch('/api/qchat_devops', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...})
    })
    .then(response => response.json())
    .then(data => {
        clearInterval(progressInterval);
        removeVirtualAdvisorMessage(progressDiv);
        
        if (data.error) {
            addVirtualAdvisorMessage('error', `Error: ${data.error}`);
        } else {
            addVirtualAdvisorMessage('assistant', data.response);
        }
    })
    .catch(error => {
        clearInterval(progressInterval);
        removeVirtualAdvisorMessage(progressDiv);
        addVirtualAdvisorMessage('error', `Error: ${error.message}`);
    });
}

function updateVirtualAdvisorMessage(messageDiv, newContent) {
    const contentDiv = messageDiv.querySelector('.message-content');
    if (contentDiv) {
        contentDiv.textContent = newContent;
    }
}

function removeVirtualAdvisorMessage(messageDiv) {
    if (messageDiv && messageDiv.parentNode) {
        messageDiv.parentNode.removeChild(messageDiv);
    }
}
```

## Recommendation

**Start with Progress Updates** (simpler alternative):
1. No backend changes needed
2. Shows user that processing is happening
3. Updates every few seconds with status messages
4. Easy to implement and test

**Upgrade to SSE later** if needed:
1. True real-time streaming
2. Shows actual AI Chat output as it happens
3. Better user experience
4. More complex implementation

## Implementation Priority

1. ✅ **Immediate**: Add progress indicator with rotating messages
2. 🔄 **Short-term**: Implement SSE streaming for real-time output
3. 🎯 **Long-term**: Add WebSocket for bidirectional communication

