const auth = {
    setTokens(access, refresh) {
        localStorage.setItem('access_token', access);
        localStorage.setItem('refresh_token', refresh);
    },
    
    clearTokens() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    },
    
    getAccessToken() {
        return localStorage.getItem('access_token');
    },
    
    getRefreshToken() {
        return localStorage.getItem('refresh_token');
    },
    
    isAuthenticated() {
        return !!this.getAccessToken();
    },
    
    async refreshToken() {
        const refresh = this.getRefreshToken();
        if (!refresh) {
            return false;
        }
        
        try {
            const response = await api.post('/auth/token/refresh/', {
                refresh: refresh
            });
            
            if (response.access) {
                this.setTokens(response.access, response.refresh || refresh);
                return true;
            }
            
            return false;
            
        } catch (error) {
            console.error('Token refresh failed:', error);
            this.clearTokens();
            return false;
        }
    },
    
    async checkAuth() {
        if (!this.isAuthenticated()) {
            return false;
        }
        
        try {
            await api.get('/auth/profile/');
            return true;
            
        } catch (error) {
            if (error.status === 401) {
                return await this.refreshToken();
            }
            return false;
        }
    }
};

window.auth = auth;