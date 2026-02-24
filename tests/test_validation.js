const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');
const path = require('path');

const API_BASE = 'http://localhost:4000';

async function testValidation() {
    console.log('--- Testing File Validation ---');

    // 1. Test valid PDF (assuming we have one or create a dummy)
    console.log('\nTesting valid PDF upload...');
    const dummyPdfPath = path.join(__dirname, 'test_dummy.pdf');
    fs.writeFileSync(dummyPdfPath, '%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF');

    try {
        const form = new FormData();
        form.append('file', fs.createReadStream(dummyPdfPath));
        const response = await axios.post(`${API_BASE}/upload`, form, {
            headers: form.getHeaders(),
        });
        console.log('✅ Valid PDF: Success (Status', response.status, ')');
    } catch (err) {
        console.log('❌ Valid PDF: Failed (Status', err.response?.status, ')');
        console.log('Response:', err.response?.data);
    }

    // 2. Test invalid extension (.txt)
    console.log('\nTesting invalid extension (.txt)...');
    const txtPath = path.join(__dirname, 'test.txt');
    fs.writeFileSync(txtPath, 'This is a text file');
    try {
        const form = new FormData();
        form.append('file', fs.createReadStream(txtPath));
        await axios.post(`${API_BASE}/upload`, form, {
            headers: form.getHeaders(),
        });
        console.log('❌ Invalid extension: Failed to catch!');
    } catch (err) {
        if (err.response?.status === 400 && err.response?.data?.error === 'Invalid file type. Only PDF files are accepted.') {
            console.log('✅ Invalid extension: Caught correctly (Status 400)');
        } else {
            console.log('❌ Invalid extension: Unexpected response (Status', err.response?.status, ')');
            console.log('Response:', err.response?.data);
        }
    }

    // 3. Test spoofed extension (txt renamed to .pdf)
    console.log('\nTesting spoofed extension (txt renamed to .pdf)...');
    const spoofedPath = path.join(__dirname, 'spoofed.pdf');
    fs.writeFileSync(spoofedPath, 'This is a text file labeled as PDF');
    try {
        const form = new FormData();
        form.append('file', fs.createReadStream(spoofedPath));
        await axios.post(`${API_BASE}/upload`, form, {
            headers: form.getHeaders(),
        });
        console.log('❌ Spoofed extension: Failed to catch!');
    } catch (err) {
        if (err.response?.status === 400 && err.response?.data?.error === 'Invalid file type. Only PDF files are accepted.') {
            console.log('✅ Spoofed extension: Caught correctly (Status 400)');
        } else {
            console.log('❌ Spoofed extension: Unexpected response (Status', err.response?.status, ')');
            console.log('Response:', err.response?.data);
        }
    }

    // 4. Test oversized file
    console.log('\nTesting oversized file ( > 20MB)...');
    const oversizedPath = path.join(__dirname, 'oversized.pdf');
    const buffer = Buffer.alloc(21 * 1024 * 1024); // 21MB
    buffer.write('%PDF-1.4\n');
    fs.writeFileSync(oversizedPath, buffer);
    try {
        const form = new FormData();
        form.append('file', fs.createReadStream(oversizedPath));
        await axios.post(`${API_BASE}/upload`, form, {
            headers: form.getHeaders(),
        });
        console.log('❌ Oversized file: Failed to catch!');
    } catch (err) {
        if (err.response?.status === 400 && err.response?.data?.error === 'File too large. Maximum allowed size is 20MB.') {
            console.log('✅ Oversized file: Caught correctly (Status 400)');
        } else {
            console.log('❌ Oversized file: Unexpected response (Status', err.response?.status, ')');
            console.log('Response:', err.response?.data);
        }
    }

    // Cleanup
    [dummyPdfPath, txtPath, spoofedPath, oversizedPath].forEach(p => {
        if (fs.existsSync(p)) fs.unlinkSync(p);
    });
}

testValidation();
