/**
 * GIZMO — main.js
 * Shared utilities used across all pages.
 */

// ─────────────────────────────────────────────
// CSRF — read Django's csrftoken cookie
// ─────────────────────────────────────────────
function getCookie(name) {
    const v = document.cookie.match('(^|;) ?' + name + '=([^;]*)(;|$)');
    return v ? v[2] : null;
}

// Shorthand used in fetch calls
function csrfToken() {
    return getCookie('csrftoken');
}


// ─────────────────────────────────────────────
// THEME — dark / light toggle
// ─────────────────────────────────────────────
function applyTheme() {
    const saved = localStorage.getItem('gizmo-theme');
    if (saved === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
    // Update any theme toggle buttons on the page
    document.querySelectorAll('.theme-toggle, .theme-btn, #themeToggleBtn, #themeBtn').forEach(btn => {
        btn.textContent = saved === 'dark' ? '☀️' : '🌙';
    });
}

function toggleThemeGlobal() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    localStorage.setItem('gizmo-theme', isDark ? '' : 'dark');
    applyTheme();
}

// Apply theme immediately on script load (before DOMContentLoaded)
applyTheme();


// ─────────────────────────────────────────────
// EMAIL VALIDATION — client-side instant check
// ─────────────────────────────────────────────
const ACADEMIC_PATTERNS = [
    /\.edu$/i,
    /\.edu\./i,
    /\.ac\./i,
    /\.ac$/i,
    /university\./i,
    /uni\./i,
    /college\./i,
    /\.institute$/i,
    /student\./i,
    /alumni\./i,
];

const PERSONAL_DOMAINS = new Set([
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
    'icloud.com', 'live.com', 'aol.com', 'protonmail.com',
    'mail.com', 'yandex.com', 'zoho.com', 'gmx.com',
    'msn.com', 'me.com', 'googlemail.com',
]);

/**
 * Quick client-side university email check.
 * Returns { ok: bool, error: string }
 */
function checkUniversityEmail(email) {
    email = email.trim().toLowerCase();
    if (!email.includes('@')) {
        return { ok: false, error: 'Please enter a valid email address.' };
    }
    const domain = email.split('@')[1];
    if (!domain) {
        return { ok: false, error: 'Please enter a valid email address.' };
    }
    if (PERSONAL_DOMAINS.has(domain)) {
        return {
            ok: false,
            error: `Personal email addresses (@${domain}) are not accepted. Please use your university email.`
        };
    }
    for (const pattern of ACADEMIC_PATTERNS) {
        if (pattern.test(domain)) {
            return { ok: true, error: '' };
        }
    }
    // If it doesn't match academic patterns, warn but don't hard-block
    // (server-side will do the final check)
    return {
        ok: true,
        error: '',
        warning: `'${email}' may not be a university address. Make sure to use your official institutional email.`
    };
}

/**
 * Wire a blur listener on an email input for instant feedback.
 * @param {string} inputId  - id of the email <input>
 * @param {string} errorId  - id of the error <div>
 */
function wireEmailValidation(inputId, errorId) {
    const input = document.getElementById(inputId);
    const errEl = document.getElementById(errorId);
    if (!input || !errEl) return;

    input.addEventListener('blur', function() {
        const result = checkUniversityEmail(this.value);
        if (!result.ok) {
            errEl.textContent = result.error;
            errEl.classList.add('show');
            errEl.style.display = 'block';
        } else if (result.warning) {
            errEl.textContent = result.warning;
            errEl.classList.add('show');
            errEl.style.display = 'block';
            errEl.style.color = 'var(--accent, #f59e0b)';
        } else {
            errEl.classList.remove('show');
            errEl.style.display = 'none';
        }
    });

    // Clear error on focus
    input.addEventListener('focus', function() {
        errEl.classList.remove('show');
        errEl.style.display = 'none';
    });
}


// ─────────────────────────────────────────────
// FETCH HELPER — wraps fetch with CSRF + JSON
// ─────────────────────────────────────────────
async function postJSON(url, data) {
    const res = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken(),
        },
        body: JSON.stringify(data),
    });
    return res.json();
}


// ─────────────────────────────────────────────
// FORM HELPERS
// ─────────────────────────────────────────────

/** Show or hide a field error element based on condition */
function validate(fieldId, condition) {
    const errEl = document.getElementById('err-' + fieldId);
    if (errEl) {
        errEl.classList.toggle('show', !condition);
        errEl.style.display = !condition ? 'block' : 'none';
    }
    return condition;
}

/** Set a button into loading state */
function setLoading(btnId, loading, loadingText = 'Please wait…', originalText = null) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.disabled = loading;
    const textEl = btn.querySelector('span:last-child') || btn;
    if (loading) {
        btn._originalText = textEl.textContent;
        textEl.textContent = loadingText;
        const spinner = btn.querySelector('.spinner');
        if (spinner) spinner.style.display = 'block';
    } else {
        textEl.textContent = originalText || btn._originalText || 'Continue';
        const spinner = btn.querySelector('.spinner');
        if (spinner) spinner.style.display = 'none';
    }
}


// ─────────────────────────────────────────────
// AUTO-INIT on DOMContentLoaded
// ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
    // Apply saved theme
    applyTheme();

    // Wire theme toggle buttons
    document.querySelectorAll('.theme-toggle, .theme-btn, #themeToggleBtn, #themeBtn').forEach(btn => {
        btn.addEventListener('click', toggleThemeGlobal);
    });

    // Wire email validation if fields exist on this page
    wireEmailValidation('email', 'err-email');
    wireEmailValidation('resetEmail', 'err-reset-email');
});