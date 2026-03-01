const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');
const path = require('path');

const API_BASE = process.env.API_BASE || 'http://localhost:4000';

let passed = 0;
let failed = 0;
const tempFiles = [];

function pass(name) {
    passed++;
    console.log(`  ✅ ${name}`);
}

function fail(name, detail) {
    failed++;
    console.log(`  ❌ ${name}: ${detail}`);
}

function tmpFile(name) {
    const p = path.join(__dirname, name);
    tempFiles.push(p);
    return p;
}

function cleanup() {
    tempFiles.forEach(p => {
        try { if (fs.existsSync(p)) fs.unlinkSync(p); } catch (_) { /* ignore */ }
    });
}

/**
 * Integration tests for the /upload endpoint.
 *
 * Validates:
 *  1. Valid PDF is accepted
 *  2. Wrong extension (.txt) is rejected with 400
 *  3. Spoofed MIME (plain-text content in a .pdf) is rejected with 400
 *  4. File exceeding 20 MB limit is rejected with 400
 *  5. Missing file field is rejected with 400
 *
 * Requires the server to be running on API_BASE (default http://localhost:4000).
 */
async function testValidation() {
    console.log('--- PDF Upload Validation Tests ---\n');

    // 1. Valid PDF upload
    console.log('Test 1: Valid PDF upload');
    const dummyPdfPath = tmpFile('test_dummy.pdf');
    fs.writeFileSync(dummyPdfPath, '%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF');
    try {
        const form = new FormData();
        form.append('file', fs.createReadStream(dummyPdfPath));
        const res = await axios.post(`${API_BASE}/upload`, form, {
            headers: form.getHeaders(),
        });
        if (res.status === 200 && res.data.session_id) {
            pass('Valid PDF accepted (200)');
        } else {
            fail('Valid PDF', `Unexpected status ${res.status}`);
        }
    } catch (err) {
        fail('Valid PDF', `Server responded ${err.response?.status || err.code}: ${JSON.stringify(err.response?.data)}`);
    }

    // 2. Invalid extension (.txt)
    console.log('Test 2: Invalid extension (.txt)');
    const txtPath = tmpFile('test.txt');
    fs.writeFileSync(txtPath, 'This is a text file');
    try {
        const form = new FormData();
        form.append('file', fs.createReadStream(txtPath));
        await axios.post(`${API_BASE}/upload`, form, { headers: form.getHeaders() });
        fail('Invalid extension', 'Server did not reject the file');
    } catch (err) {
        if (err.response?.status === 400 &&
            err.response.data.error === 'Invalid file type. Only PDF files are accepted.') {
            pass('Invalid extension rejected (400)');
        } else {
            fail('Invalid extension', `Got ${err.response?.status}: ${JSON.stringify(err.response?.data)}`);
        }
    }

    // 3. Spoofed extension (plain-text content in a .pdf file)
    console.log('Test 3: Spoofed MIME (.pdf extension, text content)');
    const spoofedPath = tmpFile('spoofed.pdf');
    fs.writeFileSync(spoofedPath, 'This is a text file labeled as PDF');
    try {
        const form = new FormData();
        form.append('file', fs.createReadStream(spoofedPath));
        await axios.post(`${API_BASE}/upload`, form, { headers: form.getHeaders() });
        fail('Spoofed extension', 'Server did not reject the file');
    } catch (err) {
        if (err.response?.status === 400 &&
            err.response.data.error === 'Invalid file type. Only PDF files are accepted.') {
            pass('Spoofed extension rejected (400)');
        } else {
            fail('Spoofed extension', `Got ${err.response?.status}: ${JSON.stringify(err.response?.data)}`);
        }
    }

    // 4. Oversized file (> 20 MB)
    console.log('Test 4: Oversized file (21 MB)');
    const oversizedPath = tmpFile('oversized.pdf');
    const buf = Buffer.alloc(21 * 1024 * 1024); // 21 MB
    buf.write('%PDF-1.4\n');
    fs.writeFileSync(oversizedPath, buf);
    try {
        const form = new FormData();
        form.append('file', fs.createReadStream(oversizedPath));
        await axios.post(`${API_BASE}/upload`, form, { headers: form.getHeaders() });
        fail('Oversized file', 'Server did not reject the file');
    } catch (err) {
        if (err.response?.status === 400 &&
            err.response.data.error === 'File too large. Maximum allowed size is 20MB.') {
            pass('Oversized file rejected (400)');
        } else {
            fail('Oversized file', `Got ${err.response?.status}: ${JSON.stringify(err.response?.data)}`);
        }
    }

    // 5. Missing file field
    console.log('Test 5: Missing file field');
    try {
        await axios.post(`${API_BASE}/upload`, {}, {
            headers: { 'Content-Type': 'application/json' },
        });
        fail('Missing file', 'Server did not reject the request');
    } catch (err) {
        if (err.response?.status === 400) {
            pass('Missing file rejected (400)');
        } else {
            fail('Missing file', `Got ${err.response?.status}: ${JSON.stringify(err.response?.data)}`);
        }
    }
}

// Run and report
testValidation()
    .then(() => {
        cleanup();
        console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
        process.exit(failed > 0 ? 1 : 0);
    })
    .catch((err) => {
        cleanup();
        console.error('\nTest suite crashed:', err.message);
        process.exit(1);
    });
