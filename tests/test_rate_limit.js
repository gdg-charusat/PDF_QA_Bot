const axios = require('axios');

const API_BASE = 'http://localhost:4000';

async function testAskLimiter() {
    console.log('Testing /ask rate limiter (Limit: 20/min)...');

    const requests = [];
    // Send 21 requests to /ask
    for (let i = 1; i <= 21; i++) {
        requests.push(
            axios.post(`${API_BASE}/ask`, { question: 'test' })
                .then(res => ({ status: res.status, i: i, data: res.data }))
                .catch(err => ({ status: err.response ? err.response.status : err.code, i: i, data: err.response ? err.response.data : null }))
        );
    }

    const results = await Promise.all(requests);

    results.forEach(r => console.log(`Request ${r.i}: Status ${r.status}`));

    const successful = results.filter(r => r.status === 200).length;
    const rateLimited = results.filter(r => r.status === 429).length;

    console.log(`Summary: ${successful} successful (200), ${rateLimited} rate limited (429).`);

    if (rateLimited > 0) {
        console.log('✅ Rate limiting is working on /ask!');
        const sample429 = results.find(r => r.status === 429);
        console.log(`Sample 429 response index: ${sample429.i}`);
        // Log the error message if it's a 429
        console.log('429 Response Body:', results.find(r => r.status === 429).data);
    } else {
        console.log('❌ Rate limiting NOT working or limit too high for this test.');
    }
}

async function run() {
    try {
        await testAskLimiter();
    } catch (err) {
        console.error('Test failed:', err.message);
    }
}

run();
