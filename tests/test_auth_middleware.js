// tests/test_auth_middleware.js
// ─────────────────────────────────────────────────────────────────────────────
// Unit tests for middleware/auth.js using Node.js built-in test runner.
//
// Run with:
//   node --test tests/test_auth_middleware.js
//
// These tests require jsonwebtoken to be installed:
//   npm install
// ─────────────────────────────────────────────────────────────────────────────

const { describe, it, before, after } = require('node:test');
const assert = require('node:assert/strict');
const jwt = require('jsonwebtoken');

// ── Test secret (isolated from production env) ────────────────────────────────
const TEST_SECRET = 'test-jwt-secret-for-unit-tests-only';

// Set environment variable BEFORE the module is loaded.
// middleware/auth.js reads JWT_SECRET at require() time.
process.env.JWT_SECRET = TEST_SECRET;

// Now it is safe to require the middleware
const { requireAuth, requireRole } = require('../middleware/auth');

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Build a mock Express request with an optional Authorization header.
 * @param {string|null} authHeader
 */
function mockReq(authHeader = null) {
    const headers = {};
    if (authHeader) headers['authorization'] = authHeader;
    return { headers, user: undefined };
}

/**
 * Build a minimal mock Express response that captures the status code and JSON body.
 */
function mockRes() {
    const res = {
        _status: null,
        _body: null,
        status(code) {
            this._status = code;
            return this;          // allow chaining: res.status(401).json(...)
        },
        json(body) {
            this._body = body;
            return this;
        },
    };
    return res;
}

/** Create a valid JWT with the given payload signed by the test secret. */
function makeToken(payload = {}, options = {}) {
    return jwt.sign(
        { sub: '42', username: 'testuser', role: 'user', is_active: true, ...payload },
        TEST_SECRET,
        { algorithm: 'HS256', expiresIn: '1h', ...options }
    );
}

// ── requireAuth tests ─────────────────────────────────────────────────────────

describe('requireAuth', () => {

    it('passes with a valid Bearer token and attaches req.user', () => {
        const token = makeToken({ role: 'user' });
        const req = mockReq(`Bearer ${token}`);
        const res = mockRes();
        let nextCalled = false;
        const next = () => { nextCalled = true; };

        requireAuth(req, res, next);

        assert.equal(nextCalled, true, 'next() should be called');
        assert.ok(req.user, 'req.user should be set');
        assert.equal(req.user.username, 'testuser');
        assert.equal(req.user.role, 'user');
        assert.equal(req.user.id, '42');
    });

    it('returns 401 when Authorization header is missing', () => {
        const req = mockReq(null);
        const res = mockRes();
        let nextCalled = false;

        requireAuth(req, res, () => { nextCalled = true; });

        assert.equal(nextCalled, false, 'next() should NOT be called');
        assert.equal(res._status, 401);
        assert.ok(res._body?.error, 'Response should have an error message');
    });

    it('returns 401 when Authorization header is not Bearer scheme', () => {
        const req = mockReq('Basic dXNlcjpwYXNz');
        const res = mockRes();
        let nextCalled = false;

        requireAuth(req, res, () => { nextCalled = true; });

        assert.equal(nextCalled, false);
        assert.equal(res._status, 401);
    });

    it('returns 401 when token has wrong signature (different secret)', () => {
        const token = jwt.sign(
            { sub: '99', username: 'hacker', role: 'admin', is_active: true },
            'wrong-secret',
            { algorithm: 'HS256' }
        );
        const req = mockReq(`Bearer ${token}`);
        const res = mockRes();
        let nextCalled = false;

        requireAuth(req, res, () => { nextCalled = true; });

        assert.equal(nextCalled, false);
        assert.equal(res._status, 401);
        assert.match(res._body?.error, /invalid/i);
    });

    it('returns 401 with informative message when token is expired', () => {
        const token = makeToken({}, { expiresIn: '-1s' }); // already expired
        const req = mockReq(`Bearer ${token}`);
        const res = mockRes();
        let nextCalled = false;

        requireAuth(req, res, () => { nextCalled = true; });

        assert.equal(nextCalled, false);
        assert.equal(res._status, 401);
        assert.match(res._body?.error, /expired/i);
    });

    it('returns 401 for a completely malformed token string', () => {
        const req = mockReq('Bearer this.is.not.valid.jwt');
        const res = mockRes();
        let nextCalled = false;

        requireAuth(req, res, () => { nextCalled = true; });

        assert.equal(nextCalled, false);
        assert.equal(res._status, 401);
    });

    it('returns 403 when token payload marks user as inactive', () => {
        const token = makeToken({ is_active: false });
        const req = mockReq(`Bearer ${token}`);
        const res = mockRes();
        let nextCalled = false;

        requireAuth(req, res, () => { nextCalled = true; });

        assert.equal(nextCalled, false);
        assert.equal(res._status, 403);
        assert.match(res._body?.error, /deactivated/i);
    });

    it('sets req.user with correct fields from token payload', () => {
        const token = makeToken({ sub: '7', username: 'alice', role: 'admin', is_active: true });
        const req = mockReq(`Bearer ${token}`);
        const res = mockRes();

        requireAuth(req, res, () => { });

        assert.equal(req.user.id, '7');
        assert.equal(req.user.username, 'alice');
        assert.equal(req.user.role, 'admin');
        assert.equal(req.user.isActive, true);
    });
});

// ── requireRole tests ─────────────────────────────────────────────────────────

describe('requireRole', () => {

    it('passes when user role matches allowed role', () => {
        const req = { headers: {}, user: { id: '1', username: 'alice', role: 'admin' } };
        const res = mockRes();
        let nextCalled = false;

        const checker = requireRole('admin');
        checker(req, res, () => { nextCalled = true; });

        assert.equal(nextCalled, true);
    });

    it('passes when user role is one of multiple allowed roles', () => {
        const req = { headers: {}, user: { id: '2', username: 'bob', role: 'user' } };
        const res = mockRes();
        let nextCalled = false;

        const checker = requireRole('user', 'admin');
        checker(req, res, () => { nextCalled = true; });

        assert.equal(nextCalled, true);
    });

    it('returns 403 when user role is not in allowed roles', () => {
        const req = { headers: {}, user: { id: '3', username: 'carol', role: 'user' } };
        const res = mockRes();
        let nextCalled = false;

        const checker = requireRole('admin');
        checker(req, res, () => { nextCalled = true; });

        assert.equal(nextCalled, false);
        assert.equal(res._status, 403);
        assert.ok(res._body?.error);
    });

    it('returns 401 when req.user is not set (requireRole used without requireAuth)', () => {
        const req = { headers: {}, user: undefined };
        const res = mockRes();
        let nextCalled = false;

        const checker = requireRole('admin');
        checker(req, res, () => { nextCalled = true; });

        assert.equal(nextCalled, false);
        assert.equal(res._status, 401);
    });

    it('403 response includes the required role name', () => {
        const req = { headers: {}, user: { id: '4', username: 'dave', role: 'user' } };
        const res = mockRes();

        const checker = requireRole('admin');
        checker(req, res, () => { });

        assert.match(res._body?.error, /admin/i);
    });

    it('403 response includes the user\'s actual role', () => {
        const req = { headers: {}, user: { id: '5', username: 'eve', role: 'user' } };
        const res = mockRes();

        const checker = requireRole('admin');
        checker(req, res, () => { });

        assert.match(res._body?.error, /user/i);
    });
});
