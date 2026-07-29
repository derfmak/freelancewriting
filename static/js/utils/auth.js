if (typeof window.auth === 'undefined') {
    const auth = {
        setTokens(access, refresh) {
            if (access) localStorage.setItem('access_token', access);
            if (refresh) localStorage.setItem('refresh_token', refresh);
        },
        
        clearTokens() {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            localStorage.removeItem('user');
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
        
        isTokenExpired() {
            const token = this.getAccessToken();
            if (!token) return true;
            try {
                const payload = JSON.parse(atob(token.split('.')[1]));
                const now = Math.floor(Date.now() / 1000);
                return payload.exp <= now;
            } catch {
                return true;
            }
        },
        
        async refreshToken() {
            const refresh = this.getRefreshToken();
            if (!refresh) {
                this.clearTokens();
                return false;
            }
            try {
                const response = await fetch('/auth/refresh/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ refresh: refresh })
                });
                if (response.ok) {
                    const data = await response.json();
                    this.setTokens(data.access, null);
                    return true;
                }
                this.clearTokens();
                return false;
            } catch {
                this.clearTokens();
                return false;
            }
        },
        
        async checkAuth() {
            if (!this.isAuthenticated()) return false;
            if (this.isTokenExpired()) {
                const refreshed = await this.refreshToken();
                if (!refreshed) return false;
            }
            return true;
        },
        
        async login(email, password, remember) {
            const response = await fetch('/auth/login/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ 
                    email: email, 
                    password: password, 
                    remember: remember || false 
                })
            });
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Login failed');
            }
            const data = await response.json();
            
            if (remember) {
                this.setTokens(data.access, data.refresh);
            } else {
                sessionStorage.setItem('access_token', data.access);
                sessionStorage.setItem('refresh_token', data.refresh);
            }
            
            if (data.user) {
                localStorage.setItem('user', JSON.stringify(data.user));
            }
            
            return data;
        },
        
        async logout() {
            const refresh = this.getRefreshToken() || sessionStorage.getItem('refresh_token');
            try {
                await fetch('/auth/logout/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ refresh: refresh })
                });
            } catch {}
            this.clearTokens();
            sessionStorage.removeItem('access_token');
            sessionStorage.removeItem('refresh_token');
            window.location.href = '/login/';
        },
        
        getUser() {
            try {
                const user = localStorage.getItem('user');
                return user ? JSON.parse(user) : null;
            } catch {
                return null;
            }
        }
    };

    window.auth = auth;
}