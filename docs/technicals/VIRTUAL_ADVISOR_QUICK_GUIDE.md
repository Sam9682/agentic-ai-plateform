# Virtual Advisor - Quick Reference Guide

## 🎯 What Can Virtual Advisor Do?

Virtual Advisor now handles **application management** in addition to answering questions!

## 📋 Quick Commands

### Start Application
```
"Start my application"
"Deploy the app"
"Launch the service"
```

### Stop Application
```
"Stop the application"
"Shutdown the service"
"Halt all containers"
```

### Restart Application
```
"Restart the application"
"Reboot the service"
"Reload containers"
```

### Check Status
```
"What's the status?"
"Is my app running?"
"Show deployment status"
```

### View Logs
```
"Show me the logs"
"Display application output"
"What's in the console?"
```

### General Questions
```
"How do I configure SSL?"
"What ports are being used?"
"How do I backup the database?"
```

## 🔧 Behind the Scenes

When you ask about app management:
1. ✅ Virtual Advisor detects the action keyword
2. 📄 Loads detailed instructions from `./shared/` folder
3. 🔄 Replaces your user info (ID, name, email)
4. 🤖 Sends to AI Chat with execution permissions
5. 📊 Returns results with status and logs

## 💡 Tips

- Use **natural language** - no need for exact commands
- Virtual Advisor understands **context** from your question
- For complex tasks, be **specific** about what you want
- Check the **response** for execution details and errors

## 🚀 Access Virtual Advisor

1. Login to dashboard: https://localhost:5000
2. Click the **"💡 Virtual Advisor"** button
3. Type your question or command
4. Press Enter or click Send

## 📝 Example Conversation

**You**: "What's the status of my application?"

**Virtual Advisor**: 
```json
{
  "environment_vars": {
    "USER_ID": "5",
    "HTTP_PORT": "8080",
    "HTTPS_PORT": "8081"
  },
  "docker_compose_ps": "IS_RUNNING",
  "docker_ports": ["8080", "8081"]
}
```

**You**: "Show me the logs"

**Virtual Advisor**: *[Displays real-time container logs]*

**You**: "Restart the service"

**Virtual Advisor**: "✅ Services restarted successfully for USER_ID=5"

## 🔍 Troubleshooting

**No response?**
- Check if qchat is installed: `which qchat`
- Verify you're logged in
- Check application logs

**Action not detected?**
- Use clearer keywords (start, stop, restart, status, logs)
- Try rephrasing your question
- Check spelling

**Permission errors?**
- Ensure proper user permissions
- Check deployment directory access
- Verify Docker is running

## 📚 More Information

- Full documentation: `VIRTUAL_ADVISOR_CHANGES.md`
- Testing guide: `TEST_VIRTUAL_ADVISOR.md`
- Context files: `./shared/*_context.md`
