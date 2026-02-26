// middleware/auth.js
// ─────────────────────────────────────────────────────────────────────────────
// JWT Authentication and Role-based Authorization middleware for the Node.js
// API Gateway. Validates Bearer tokens signed by the FastAPI RAG service.
//
// Environment variables (required):
//   JWT_SECRET  — must match SECRET_KEY used in rag-service
//
// Usage in server.js:
//   const { requireAuth, requireRole } = require('./middleware/auth');
//   app.post('/upload', requireAuth, uploadLimiter, upload.single('file'), handler);
//   app.delete('/admin/resource', requireAuth, requireRole('admin'), handler);
// ─────────────────────────────────────────────────────────────────────────────

const jwt = require('jsonwebtoken');

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Extract the Bearer token string from the Authorization header.
 * Returns null if the header is missing or malformed.
 * @param {import('express').Request} req
 * @returns {string|null}
 */
function extractToken(req) {
    const authHeader = req.headers['authorization'] || req.headers['Authorization'];
    if (!authHeader) return null;

    const parts = authHeader.split(' ');
    if (parts.length !== 2 || parts[0].toLowerCase() !== 'bearer') return null;

    return parts[1] || null;
}

/**
 * Consistent error response for auth failures.
 * @param {import('express').Response} res
 * @param {number} status
 * @param {string} message
 */
function sendAuthError(res, status, message) {
    return res.status(status).json({ error: message });
}

// ── JWT Secret ────────────────────────────────────────────────────────────────

const JWT_SECRET = process.env.JWT_SECRET;

if (!JWT_SECRET) {
    // Fail loudly at startup — same pattern used for SESSION_SECRET in server.js
    throw new Error(
        'JWT_SECRET must be set in environment variables. ' +
        'It must match the SECRET_KEY used by the RAG service.'
    );
}

// ── requireAuth ───────────────────────────────────────────────────────────────

/**
 * Express middleware that verifies a JWT Bearer token.
 *
 * On success  → attaches decoded payload to req.user and calls next().
 * On failure  → responds with 401 Unauthorized.
 *
 * Expected token payload (produced by rag-service/auth/security.py):
 *   { sub: "<user_id>", username: "...", role: "user"|"admin", is_active: true, exp: ... }
 *
 * @type {import('express').RequestHandler}
 */
function requireAuth(req, res, next) {
    const token = extractToken(req);

    if (!token) {
        return sendAuthError(res, 401, 'Authentication required. Provide a valid Bearer token.');
    }

    try {
        const decoded = jwt.verify(token, JWT_SECRET, { algorithms: ['HS256'] });

        // Reject tokens for deactivated users (is_active field embedded at login)
        if (decoded.is_active === false) {
            return sendAuthError(res, 403, 'User account is deactivated.');
        }

        // Attach user info to request for downstream handlers and role checks
        req.user = {
            id: decoded.sub,
            username: decoded.username,
            role: decoded.role,
            isActive: decoded.is_active,
        };

        return next();
    } catch (err) {
        if (err.name === 'TokenExpiredError') {
            return sendAuthError(res, 401, 'Token has expired. Please log in again.');
        }
        if (err.name === 'JsonWebTokenError') {
            return sendAuthError(res, 401, 'Invalid token. Authentication failed.');
        }
        // Unknown JWT error — treat as auth failure, not server error
        return sendAuthError(res, 401, 'Authentication failed.');
    }
}

// ── requireRole ───────────────────────────────────────────────────────────────

/**
 * Returns an Express middleware that restricts access to users with one of
 * the specified roles. Must be used AFTER requireAuth.
 *
 * @param {...string} roles  One or more allowed role strings, e.g. 'admin', 'user'
 * @returns {import('express').RequestHandler}
 *
 * @example
 *   app.delete('/admin/users/:id', requireAuth, requireRole('admin'), handler);
 *   app.get('/data', requireAuth, requireRole('user', 'admin'), handler);
 */
function requireRole(...roles) {
    return function roleChecker(req, res, next) {
        if (!req.user) {
            // Guard: requireRole used without requireAuth
            return sendAuthError(res, 401, 'Authentication required.');
        }

        const userRole = req.user.role;
        if (!roles.includes(userRole)) {
            return sendAuthError(
                res,
                403,
                `Access denied. Required role(s): ${roles.join(', ')}. Your role: ${userRole}.`
            );
        }

        return next();
    };
}

module.exports = { requireAuth, requireRole };
