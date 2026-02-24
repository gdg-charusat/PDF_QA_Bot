// middleware/rateLimiter.js
// ─────────────────────────────────────────────────────────────────────────────
// Rate limiting middleware for the PDF_QA_Bot API Gateway.
// Import specific limiters in server.js and apply them per-route.
// Do NOT modify existing server.js route logic — just add the middleware.
// ─────────────────────────────────────────────────────────────────────────────

const rateLimit = require('express-rate-limit');

/**
 * Factory — builds a rate limiter with a consistent 429 response shape.
 * @param {number} windowMs   Time window in milliseconds.
 * @param {number} max        Max requests per window per IP.
 * @param {string} message    Human-readable error shown to the client.
 */
function buildLimiter(windowMs, max, message) {
    return rateLimit({
        windowMs,
        max,
        standardHeaders: true,   // Sends RateLimit-* headers (RFC 6585 compliant)
        legacyHeaders: false,     // Disables deprecated X-RateLimit-* headers
        handler: (req, res, next, options) => {
            const retryAfterSeconds = Math.ceil(options.windowMs / 1000);
            res.set('Retry-After', String(retryAfterSeconds));
            res.status(429).json({
                error: 'Too Many Requests',
                message,
                retryAfter: retryAfterSeconds,
            });
        },
    });
}

// ── Global backstop ───────────────────────────────────────────────────────────
// Applied to ALL routes via app.use(). Catches any endpoint not individually
// limited and provides a final line of defence against general flooding.
const globalLimiter = buildLimiter(
    15 * 60 * 1000, // 15-minute window
    200,
    'Too many requests from this IP. Please wait 15 minutes before retrying.'
);

// ── Upload limiter ────────────────────────────────────────────────────────────
// PDF parsing + FAISS indexing is expensive. 10 uploads per 30 minutes
// is sufficient for any legitimate user session.
const uploadLimiter = buildLimiter(
    30 * 60 * 1000, // 30-minute window
    10,
    'Upload limit reached. You may upload up to 10 PDFs per 30-minute window.'
);

// ── Ask limiter ───────────────────────────────────────────────────────────────
// Each /ask triggers FAISS vector lookup + LLM generation.
// 20 per minute comfortably covers active users; blocks scripted flooding.
const askLimiter = buildLimiter(
    60 * 1000, // 1-minute window
    20,
    'Query limit reached. You may ask up to 20 questions per minute.'
);

// ── Summarize limiter ─────────────────────────────────────────────────────────
// Full-document summarization is the most token-heavy LLM call.
// Tighter than /ask to protect against context explosion.
const summarizeLimiter = buildLimiter(
    60 * 1000, // 1-minute window
    10,
    'Summarization limit reached. You may request up to 10 summaries per minute.'
);

// ── Compare limiter ───────────────────────────────────────────────────────────
// Multi-document comparison multiplies embedding + LLM cost per request.
const compareLimiter = buildLimiter(
    60 * 1000, // 1-minute window
    10,
    'Comparison limit reached. You may request up to 10 comparisons per minute.'
);

module.exports = {
    globalLimiter,
    uploadLimiter,
    askLimiter,
    summarizeLimiter,
    compareLimiter,
};
