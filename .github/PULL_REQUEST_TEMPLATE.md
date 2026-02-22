## Team Number : Team 150

## Description
Implemented robust rate-limiting at the Node.js API Gateway to protect expensive RAG inference endpoints and the upload pipeline from resource exhaustion and potential DoS attacks.

## Related Issue
Closes #rate-limiting-security

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [x] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [x] Documentation update
- [x] Code refactoring
- [x] Performance improvement
- [ ] Style/UI improvement

## Changes Made
- Installed `express-rate-limit` dependency.
- Created `middleware/rateLimiter.js` with tiered limiting strategies:
    - **Global**: 200 req / 15 min.
    - **Uploads**: 10 req / 30 min.
    - **Queries (/ask)**: 20 req / 1 min.
    - **Inference (/summarize, /compare)**: 10 req / 1 min.
- Configured `server.js` to trust proxies and apply limiters to targeted routes.
- Added a verification test script in `tests/test_rate_limit.js`.

## Screenshots (if applicable)
Testing log showing 429 enforcement:
![Rate Limit Test](../public/rate_limit_verification.png)

## Testing
- [x] Tested on Desktop (Chrome/Firefox/Safari)
- [x] Tested on Mobile (iOS/Android)
- [ ] Tested responsive design (different screen sizes)
- [x] No console errors or warnings
- [x] Verification script confirmed 429 blocking on Request #21 for /ask.

## Checklist
- [x] My code follows the project's code style guidelines
- [x] I have performed a self-review of my code
- [x] I have commented my code where necessary
- [x] My changes generate no new warnings
- [x] I have tested my changes thoroughly
- [x] All TypeScript types are properly defined
- [x] I have read and followed the [CONTRIBUTING.md](CONTRIBUTING.md) guidelines

## Additional Notes
The implementation uses `trust proxy` setting 1, which ensures that IP detection remains accurate when the application is behind a load balancer or Nginx proxy.
