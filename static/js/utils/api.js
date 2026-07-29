const api = {
    baseURL: '/api/v1',
    
    getToken() {
        return localStorage.getItem('access_token') || sessionStorage.getItem('access_token');
    },
    
    async request(endpoint, options = {}) {
        const token = this.getToken();
        
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        const config = {
            ...options,
            headers,
            credentials: 'include'
        };
        
        try {
            const response = await fetch(endpoint, config);
            
            if (response.status === 401) {
                if (typeof auth !== 'undefined') {
                    const refreshed = await auth.refreshToken();
                    if (refreshed) {
                        const newToken = this.getToken();
                        headers['Authorization'] = `Bearer ${newToken}`;
                        const retryResponse = await fetch(endpoint, { ...config, headers });
                        if (retryResponse.ok) return retryResponse.json();
                    }
                }
                
                if (typeof auth !== 'undefined') auth.clearTokens();
                sessionStorage.removeItem('access_token');
                sessionStorage.removeItem('refresh_token');
                window.location.href = '/login/';
                throw new Error('Session expired');
            }
            
            if (response.status === 429) {
                const error = new Error('Too many attempts. Please wait a few minutes.');
                error.status = 429;
                throw error;
            }
            
            const data = await response.json();
            
            if (!response.ok) {
                const error = new Error(data.error || data.detail || 'Request failed');
                error.status = response.status;
                error.data = data;
                throw error;
            }
            
            return data;
        } catch (error) {
            if (error.status) throw error;
            throw new Error('Network error. Please check your connection.');
        }
    },
    
    get(endpoint, params = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const urlObj = new URL(url, window.location.origin);
        Object.keys(params).forEach(key => urlObj.searchParams.append(key, params[key]));
        return this.request(urlObj.pathname + urlObj.search, { method: 'GET' });
    },
    
    post(endpoint, data = {}) {
        return this.request(`${this.baseURL}${endpoint}`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    },
    
    put(endpoint, data = {}) {
        return this.request(`${this.baseURL}${endpoint}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    },
    
    patch(endpoint, data = {}) {
        return this.request(`${this.baseURL}${endpoint}`, {
            method: 'PATCH',
            body: JSON.stringify(data)
        });
    },
    
    delete(endpoint) {
        return this.request(`${this.baseURL}${endpoint}`, { method: 'DELETE' });
    }
};

window.api = api;