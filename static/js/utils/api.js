const api = {
    baseURL: '/api/v1',
    
    async request(endpoint, options = {}) {
        const token = localStorage.getItem('access_token');
        const csrfToken = document.querySelector('[name=csrf-token]')?.getAttribute('content');
        
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        if (csrfToken && !options.headers?.Authorization) {
            headers['X-CSRFToken'] = csrfToken;
        }
        
        const config = {
            ...options,
            headers
        };
        
        try {
            const response = await fetch(`${this.baseURL}${endpoint}`, config);
            
            if (response.status === 429) {
                const error = new Error('Too many attempts. Please wait a few minutes.');
                error.status = 429;
                error.data = { error: 'Too many requests' };
                throw error;
            }
            
            const data = await response.json();
            
            if (!response.ok) {
                if (response.status === 401) {
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('refresh_token');
                    window.location.href = '/login/';
                }
                const error = new Error(data.error || 'Request failed');
                error.status = response.status;
                error.data = data;
                throw error;
            }
            
            return data;
            
        } catch (error) {
            throw error;
        }
    },
    
    get(endpoint, params = {}) {
        const url = new URL(endpoint, window.location.origin);
        Object.keys(params).forEach(key => 
            url.searchParams.append(key, params[key])
        );
        return this.request(url.pathname + url.search, { method: 'GET' });
    },
    
    post(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    },
    
    put(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    },
    
    patch(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'PATCH',
            body: JSON.stringify(data)
        });
    },
    
    delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
};

window.api = api;