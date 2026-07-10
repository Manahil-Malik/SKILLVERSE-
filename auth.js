/* auth.js — shared login/signup modal + session handling for SkillVerse
   Include this on any page with: <script src="auth.js"></script>

   It expects an element with id="authNavSlot" somewhere in your <nav> —
   it will render either a "Log In" button or the logged-in user's avatar there.

   Usage to gate an action behind login:
     SkillVerseAuth.requireAuth(() => { ...do the thing... });
   If the user isn't logged in, this opens the login modal instead, and
   automatically runs your callback right after they log in / sign up.
*/

(function () {
    const API_BASE = 'http://127.0.0.1:5000';
    const GOOGLE_CLIENT_ID = '235368564033-rt6pgea9p6orn1nu2qnbuv88n3m7dq44.apps.googleusercontent.com';

    // ── Session helpers ──
    function getToken() { return localStorage.getItem('sv_token'); }
    function getEmail() { return localStorage.getItem('sv_email'); }
    function isPaid() { return localStorage.getItem('sv_is_paid') === 'true'; }
    function isLoggedIn() { return !!getToken(); }

    function saveSession(token, email, is_paid) {
        localStorage.setItem('sv_token', token);
        localStorage.setItem('sv_email', email);
        localStorage.setItem('sv_is_paid', !!is_paid);
        renderNavSlot();
    }

    function logout() {
        localStorage.removeItem('sv_token');
        localStorage.removeItem('sv_email');
        localStorage.removeItem('sv_is_paid');
        renderNavSlot();
    }

    let pendingAction = null;

    function requireAuth(action) {
        if (isLoggedIn()) {
            action();
        } else {
            pendingAction = action;
            openModal('login');
        }
    }

    function injectModal() {
        if (document.getElementById('authModalOverlay')) return;

        const wrap = document.createElement('div');
        wrap.innerHTML = `
        <style>
            #authModalOverlay {
                display: none; position: fixed; inset: 0;
                background: rgba(26,26,46,0.55); z-index: 1000;
                align-items: center; justify-content: center; padding: 1rem;
            }
            #authModalOverlay.active { display: flex; }
            .auth-modal {
                background: white; border-radius: 16px; padding: 2rem;
                width: 100%; max-width: 380px; font-family: 'Inter', sans-serif;
                box-shadow: 0 20px 60px rgba(0,0,0,0.25); position: relative;
            }
            .auth-modal h2 { font-size: 1.3rem; margin-bottom: 0.3rem; color: #1a1a2e; }
            .auth-modal p.auth-sub { color: #6b6b8a; font-size: 0.85rem; margin-bottom: 1.3rem; }
            .auth-modal input {
                width: 100%; padding: 0.7rem 0.9rem; border: 1px solid #ede9fe;
                border-radius: 8px; font-size: 0.9rem; margin-bottom: 0.8rem;
                outline: none; font-family: 'Inter', sans-serif; box-sizing: border-box;
            }
            .auth-modal input:focus { border-color: #4f46e5; }
            .auth-modal .auth-submit {
                width: 100%; background: linear-gradient(135deg,#4f46e5,#7c5cfc);
                color: white; border: none; padding: 0.75rem; border-radius: 8px;
                font-weight: 600; font-size: 0.92rem; cursor: pointer; margin-top: 0.3rem;
            }
            .auth-modal .auth-submit:disabled { opacity: 0.6; cursor: not-allowed; }
            .auth-modal .auth-switch { text-align: center; margin-top: 1rem; font-size: 0.85rem; color: #6b6b8a; }
            .auth-modal .auth-switch a { color: #4f46e5; font-weight: 600; cursor: pointer; text-decoration: none; }
            .auth-modal .auth-close {
                position: absolute; top: 1rem; right: 1.2rem; background: none;
                border: none; font-size: 1.3rem; color: #9b9bb5; cursor: pointer; line-height: 1;
            }
            .auth-modal .auth-error {
                background: #fff1f0; color: #991b1b; padding: 0.6rem 0.8rem;
                border-radius: 8px; font-size: 0.82rem; margin-bottom: 0.8rem; display: none;
            }
            .auth-modal .auth-error.active { display: block; }
            .auth-modal .auth-hint {
                font-size: 0.75rem; color: #9b9bb5; margin: -0.5rem 0 0.8rem;
            }
            .auth-modal .auth-divider {
                display: flex; align-items: center; text-align: center;
                color: #9b9bb5; font-size: 0.78rem; margin: 1rem 0;
            }
            .auth-modal .auth-divider::before,
            .auth-modal .auth-divider::after {
                content: ''; flex: 1; border-bottom: 1px solid #ede9fe;
            }
            .auth-modal .auth-divider span { padding: 0 0.7rem; }
            #googleButtonContainer { display: flex; justify-content: center; margin-bottom: 0.5rem; min-height: 40px; }
            #authNavSlot { position: relative; }
            #authNavSlot .avatar-btn {
                width: 38px; height: 38px; border-radius: 50%;
                background: linear-gradient(135deg,#4f46e5,#7c5cfc); color: white;
                border: none; font-size: 0.95rem; font-weight: 700; cursor: pointer;
                font-family: 'Inter', sans-serif; display: flex; align-items: center;
                justify-content: center; line-height: 1;
            }
            #authNavSlot .avatar-dropdown {
                display: none; position: absolute; top: 48px; right: 0;
                background: white; border: 1px solid #ede9fe; border-radius: 10px;
                box-shadow: 0 12px 30px rgba(0,0,0,0.12); min-width: 210px;
                padding: 0.9rem; z-index: 50; font-family: 'Inter', sans-serif;
            }
            #authNavSlot .avatar-dropdown.open { display: block; }
            #authNavSlot .avatar-dropdown .dd-email {
                font-size: 0.82rem; color: #1a1a2e; font-weight: 600;
                word-break: break-all; margin-bottom: 0.8rem;
            }
            #authNavSlot .avatar-dropdown button {
                width: 100%; background: #f8f7ff; border: 1px solid #ede9fe; color: #4f46e5;
                padding: 0.5rem 0.9rem; border-radius: 8px; font-size: 0.82rem;
                font-weight: 600; cursor: pointer; font-family: 'Inter', sans-serif;
            }
            #authNavSlot .btn-login-nav {
                background: transparent; border: 1.5px solid #4f46e5; color: #4f46e5;
                padding: 0.5rem 1.2rem; border-radius: 8px; font-weight: 600;
                font-size: 0.88rem; cursor: pointer; font-family: 'Inter', sans-serif;
            }
        </style>
        <div id="authModalOverlay">
            <div class="auth-modal">
                <button class="auth-close" onclick="SkillVerseAuth.closeModal()">✕</button>
                <div id="authError" class="auth-error"></div>

                <div id="authLoginView">
                    <h2>Log In</h2>
                    <p class="auth-sub">Log in to analyse your CV.</p>
                    <input type="email" id="loginEmail" placeholder="Email">
                    <input type="password" id="loginPassword" placeholder="Password">
                    <button class="auth-submit" id="loginBtn" onclick="SkillVerseAuth.doLogin()">Log In</button>

                    <div class="auth-divider"><span>or</span></div>
                    <div id="googleButtonContainer"></div>

                    <div class="auth-switch">Don't have an account? <a onclick="SkillVerseAuth.openModal('signup')">Sign up</a></div>
                </div>

                <div id="authSignupView" style="display:none">
                    <h2>Create Account</h2>
                    <p class="auth-sub">Free — takes 10 seconds.</p>
                    <input type="email" id="signupEmail" placeholder="Email">
                    <input type="password" id="signupPassword" placeholder="Password">
                    <p class="auth-hint">Min 8 characters, 1 uppercase, 1 lowercase, 1 special character.</p>
                    <button class="auth-submit" id="signupBtn" onclick="SkillVerseAuth.doSignup()">Sign Up</button>
                    <div class="auth-switch">Already have an account? <a onclick="SkillVerseAuth.openModal('login')">Log in</a></div>
                </div>
            </div>
        </div>`;
        document.body.appendChild(wrap);

        wrap.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            const signupVisible = document.getElementById('authSignupView').style.display !== 'none';
            signupVisible ? doSignup() : doLogin();
        });
    }

    let googleInitialized = false;

    function tryInitGoogleButton() {
        if (!window.google || !window.google.accounts || !window.google.accounts.id) {
            return;
        }
        if (!googleInitialized) {
            window.google.accounts.id.initialize({
                client_id: GOOGLE_CLIENT_ID,
                callback: handleGoogleSignIn
            });
            googleInitialized = true;
        }
        const target = document.getElementById('googleButtonContainer');
        if (target) {
            target.innerHTML = '';
            window.google.accounts.id.renderButton(target, { theme: 'outline', size: 'large', width: 300 });
        }
    }

    function openModal(view) {
        injectModal();
        document.getElementById('authError').classList.remove('active');
        document.getElementById('authLoginView').style.display = view === 'signup' ? 'none' : 'block';
        document.getElementById('authSignupView').style.display = view === 'signup' ? 'block' : 'none';
        document.getElementById('authModalOverlay').classList.add('active');
        tryInitGoogleButton();
    }

    function closeModal() {
        const el = document.getElementById('authModalOverlay');
        if (el) el.classList.remove('active');
        pendingAction = null;
    }

    function showAuthError(msg) {
        const el = document.getElementById('authError');
        el.textContent = msg;
        el.classList.add('active');
    }

    async function doLogin() {
        const email = document.getElementById('loginEmail').value.trim();
        const password = document.getElementById('loginPassword').value;
        if (!email || !password) return showAuthError('Enter your email and password.');

        const btn = document.getElementById('loginBtn');
        btn.disabled = true; btn.textContent = 'Logging in…';
        try {
            const res = await fetch(API_BASE + '/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();
            if (!res.ok) { showAuthError(data.message || 'Login failed.'); return; }

            saveSession(data.token, email, data.is_paid);
            closeModal();
            if (pendingAction) { const a = pendingAction; pendingAction = null; a(); }
        } catch (e) {
            showAuthError('Could not reach the server. Is the backend running on port 5000?');
        } finally {
            btn.disabled = false; btn.textContent = 'Log In';
        }
    }

    async function doSignup() {
        const email = document.getElementById('signupEmail').value.trim();
        const password = document.getElementById('signupPassword').value;
        if (!email || !password) return showAuthError('Enter an email and password.');

        const passwordRules = /^(?=.*[a-z])(?=.*[A-Z])(?=.*[!@#$%^&*(),.?":{}|<>_\-+=~`[\]\\/;'])[A-Za-z\d!@#$%^&*(),.?":{}|<>_\-+=~`[\]\\/;']{8,}$/;
        if (!passwordRules.test(password)) {
            return showAuthError('Password must be 8+ characters with 1 uppercase, 1 lowercase, and 1 special character.');
        }

        const btn = document.getElementById('signupBtn');
        btn.disabled = true; btn.textContent = 'Creating account…';
        try {
            const res = await fetch(API_BASE + '/api/signup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();
            if (!res.ok) { showAuthError(data.message || 'Signup failed.'); return; }

            saveSession(data.token, email, data.is_paid);
            closeModal();
            if (pendingAction) { const a = pendingAction; pendingAction = null; a(); }
        } catch (e) {
            showAuthError('Could not reach the server. Is the backend running on port 5000?');
        } finally {
            btn.disabled = false; btn.textContent = 'Sign Up';
        }
    }

    async function handleGoogleSignIn(response) {
        try {
            const res = await fetch(API_BASE + '/api/google-login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ credential: response.credential })
            });
            const data = await res.json();
            if (!res.ok) { showAuthError(data.message || 'Google sign-in failed.'); return; }

            saveSession(data.token, data.email, data.is_paid);
            closeModal();
            if (pendingAction) { const a = pendingAction; pendingAction = null; a(); }
        } catch (e) {
            showAuthError('Could not reach the server. Is the backend running on port 5000?');
        }
    }

    function renderNavSlot() {
        const slot = document.getElementById('authNavSlot');
        if (!slot) return;
        if (isLoggedIn()) {
            const initial = getEmail().charAt(0).toUpperCase();
            slot.innerHTML = `
                <button class="avatar-btn" onclick="SkillVerseAuth.toggleDropdown()">${initial}</button>
                <div class="avatar-dropdown" id="avatarDropdown">
                    <div class="dd-email">${getEmail()}</div>
                    <button onclick="SkillVerseAuth.logout()">Log Out</button>
                </div>`;
        } else {
            slot.innerHTML = `<button class="btn-login-nav" onclick="SkillVerseAuth.openModal('login')">Log In</button>`;
        }
    }

    function toggleDropdown() {
        const dd = document.getElementById('avatarDropdown');
        if (dd) dd.classList.toggle('open');
    }

    document.addEventListener('click', (e) => {
        const slot = document.getElementById('authNavSlot');
        const dd = document.getElementById('avatarDropdown');
        if (dd && slot && !slot.contains(e.target)) dd.classList.remove('open');
    });

    document.addEventListener('DOMContentLoaded', () => {
        injectModal();
        renderNavSlot();
    });

    window.SkillVerseAuth = {
        isLoggedIn, getToken, getEmail, isPaid, logout,
        requireAuth, openModal, closeModal, doLogin, doSignup, toggleDropdown, handleGoogleSignIn
    };
    window.handleGoogleSignIn = handleGoogleSignIn;
})();