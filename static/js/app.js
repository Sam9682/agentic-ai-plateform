// Handle add application form
document.addEventListener('DOMContentLoaded', function() {
    const addAppForm = document.getElementById('addAppForm');
    
    if (addAppForm) {
        addAppForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(addAppForm);
            const data = {
                name: formData.get('name'),
                url: formData.get('url'),
                description: formData.get('description')
            };
            
            try {
                const response = await fetch('/api/applications', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(data)
                });
                
                if (response.ok) {
                    alert('Application added successfully!');
                    location.reload();
                } else {
                    const error = await response.json();
                    alert('Error: ' + error.error);
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        });
    }
    
    // Handle login form
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', function(e) {
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            if (!username || !password) {
                e.preventDefault();
                alert('Please fill in all fields');
            }
        });
    }
    
    // Handle register form
    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.addEventListener('submit', function(e) {
            const username = document.getElementById('username').value;
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;
            
            if (!username || !email || !password) {
                e.preventDefault();
                alert('Please fill in all required fields');
            }
        });
    }
});