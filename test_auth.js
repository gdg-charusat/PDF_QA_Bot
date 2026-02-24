const axios = require('axios');

const API_BASE = 'http://localhost:4000';
let token = '';

async function runTests() {
    console.log('--- Starting Auth Tests ---');

    try {
        // 1. Test registration
        console.log('1. Testing Registration...');
        await axios.post(`${API_BASE}/auth/register`, {
            email: 'test@example.com',
            password: 'password123',
            role: 'user'
        });
        console.log('   Registration successful!');

        // 2. Test login
        console.log('2. Testing Login...');
        const loginRes = await axios.post(`${API_BASE}/auth/login`, {
            email: 'test@example.com',
            password: 'password123'
        });
        token = loginRes.data.token;
        console.log('   Login successful! Token received.');

        // 3. Test unauthorized access
        console.log('3. Testing Unauthorized access to /ask...');
        try {
            await axios.post(`${API_BASE}/ask`, { question: 'hello', doc_ids: [] });
            console.log('   FAIL: Accessed /ask without token');
        } catch (err) {
            if (err.response.status === 401) {
                console.log('   PASS: Access denied (401)');
            } else {
                console.log('   FAIL: Unexpected error', err.response.status);
            }
        }

        // 4. Test authorized access
        console.log('4. Testing Authorized access to /ask...');
        try {
            const askRes = await axios.post(`${API_BASE}/ask`,
                { question: 'What is this document about?', doc_ids: [] },
                { headers: { Authorization: `Bearer ${token}` } }
            );
            // Note: This might still return "upload pdf first" which is fine, it means it passed auth
            console.log('   PASS: Access granted. Response:', askRes.data.answer || askRes.data);
        } catch (err) {
            console.log('   FAIL: Authorized access failed', err.response?.data || err.message);
        }

    } catch (err) {
        console.error('Test script failed:', err.response?.data || err.message);
    }
}

runTests();
