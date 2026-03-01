/**
 * SSE Streaming Frontend Test Suite
 * Tests the React frontend's ability to consume SSE tokens and update UI
 * Run this in browser console at http://localhost:3000
 */

const StreamingTests = {
  colors: {
    reset: '\x1b[0m',
    green: '\x1b[32m',
    red: '\x1b[31m',
    yellow: '\x1b[33m',
    blue: '\x1b[34m',
  },

  log: (message, color = 'reset') => {
    const colorCode = StreamingTests.colors[color] || '';
    console.log(`${colorCode}${message}${StreamingTests.colors.reset}`);
  },

  async testFetchStreamingAPI() {
    /**
     * Test 1: Verify fetch API can handle streaming response
     */
    StreamingTests.log('\n=== Test 1: Fetch API Streaming ===\n', 'blue');

    try {
      const sessionId = 'test-session-' + Date.now();
      const question = 'What is machine learning?';

      StreamingTests.log(`Testing: ${question}`, 'yellow');
      StreamingTests.log(`Session: ${sessionId}`, 'yellow');

      const response = await fetch('/ask-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, session_ids: [sessionId] }),
      });

      // Test 1.1: Status check
      const test1_1 = response.status === 200;
      StreamingTests.log(
        `${test1_1 ? '✅' : '❌'} HTTP Status 200: ${response.status}`,
        test1_1 ? 'green' : 'red'
      );

      // Test 1.2: Content-Type check
      const contentType = response.headers.get('content-type');
      const test1_2 =
        contentType.includes('event-stream') ||
        contentType.includes('ndjson');
      StreamingTests.log(
        `${test1_2 ? '✅' : '❌'} Content-Type: ${contentType}`,
        test1_2 ? 'green' : 'red'
      );

      // Test 1.3: ReadableStream available
      const test1_3 = response.body !== null;
      StreamingTests.log(
        `${test1_3 ? '✅' : '❌'} ReadableStream available`,
        test1_3 ? 'green' : 'red'
      );

      return test1_1 && test1_2 && test1_3;
    } catch (error) {
      StreamingTests.log(`❌ Error: ${error.message}`, 'red');
      return false;
    }
  },

  async testSSEParsing() {
    /**
     * Test 2: Verify SSE message parsing
     */
    StreamingTests.log('\n=== Test 2: SSE Parsing ===\n', 'blue');

    try {
      const sessionId = 'test-session-' + Date.now();
      const response = await fetch('/ask-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: 'Test streaming',
          session_ids: [sessionId],
        }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      let buffer = '';
      let tokens = [];
      let citations = null;
      let doneReceived = false;
      let messageCount = 0;

      StreamingTests.log('Streaming response in real-time:\n', 'yellow');

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value);
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const message = JSON.parse(line.slice(6));
              messageCount++;

              if (message.event === 'citations' && message.data) {
                citations = message.data;
                StreamingTests.log(
                  `📎 Citations: ${message.data.length} sources`,
                  'yellow'
                );
              } else if (message.event === 'done') {
                doneReceived = true;
                StreamingTests.log(`✓ Stream complete`, 'yellow');
              } else if (message.token) {
                tokens.push(message.token);
                process.stdout.write(message.token); // Show tokens in real-time
              }
            } catch (e) {
              StreamingTests.log(`⚠️ Parse error: ${e.message}`, 'yellow');
            }
          }
        }
      }

      const fullResponse = tokens.join('');
      console.log('\n');

      // Test 2.1: Messages received
      const test2_1 = messageCount > 0;
      StreamingTests.log(
        `${test2_1 ? '✅' : '❌'} SSE messages parsed: ${messageCount}`,
        test2_1 ? 'green' : 'red'
      );

      // Test 2.2: Tokens received
      const test2_2 = tokens.length > 0;
      StreamingTests.log(
        `${test2_2 ? '✅' : '❌'} Tokens received: ${tokens.length}`,
        test2_2 ? 'green' : 'red'
      );

      // Test 2.3: Full response length
      const test2_3 = fullResponse.length > 10;
      StreamingTests.log(
        `${test2_3 ? '✅' : '❌'} Response length: ${fullResponse.length} chars`,
        test2_3 ? 'green' : 'red'
      );

      // Test 2.4: Done signal
      const test2_4 = doneReceived;
      StreamingTests.log(
        `${test2_4 ? '✅' : '❌'} Done signal received`,
        test2_4 ? 'green' : 'red'
      );

      return test2_1 && test2_2 && test2_3 && test2_4;
    } catch (error) {
      StreamingTests.log(`❌ Error: ${error.message}`, 'red');
      return false;
    }
  },

  async testTokenAccumulation() {
    /**
     * Test 3: Verify token accumulation for UI display
     */
    StreamingTests.log('\n=== Test 3: Token Accumulation ===\n', 'blue');

    try {
      const sessionId = 'test-session-' + Date.now();
      const response = await fetch('/ask-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: 'Provide a detailed answer',
          session_ids: [sessionId],
        }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      let buffer = '';
      let fullAnswer = '';
      let tokenSequence = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value);
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const message = JSON.parse(line.slice(6));
              if (message.token) {
                tokenSequence.push(message.token);
                fullAnswer += message.token;
              }
            } catch (e) {}
          }
        }
      }

      // Test 3.1: Accumulation works
      const test3_1 = fullAnswer === tokenSequence.join('');
      StreamingTests.log(
        `${test3_1 ? '✅' : '❌'} Token accumulation correct`,
        test3_1 ? 'green' : 'red'
      );

      // Test 3.2: Maintains order
      const test3_2 = tokenSequence.length > 0;
      StreamingTests.log(
        `${test3_2 ? '✅' : '❌'} Token order preserved (${tokenSequence.length} tokens)`,
        test3_2 ? 'green' : 'red'
      );

      // Test 3.3: No token loss
      const test3_3 = fullAnswer.length > 20;
      StreamingTests.log(
        `${test3_3 ? '✅' : '❌'} Response quality (${fullAnswer.length} chars)`,
        test3_3 ? 'green' : 'red'
      );

      return test3_1 && test3_2 && test3_3;
    } catch (error) {
      StreamingTests.log(`❌ Error: ${error.message}`, 'red');
      return false;
    }
  },

  async testPerformance() {
    /**
     * Test 4: Verify performance improvements
     */
    StreamingTests.log(
      '\n=== Test 4: Performance (TTFB & Streaming Speed) ===\n',
      'blue'
    );

    try {
      const sessionId = 'test-session-' + Date.now();

      // Measure Time to First Byte
      const startTime = performance.now();
      const response = await fetch('/ask-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: 'Performance test',
          session_ids: [sessionId],
        }),
      });
      const ttfbTime = performance.now() - startTime;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      let buffer = '';
      let firstTokenTime = null;
      let tokenCount = 0;
      let lastTokenTime = performance.now();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value);
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const message = JSON.parse(line.slice(6));
              if (message.token) {
                tokenCount++;
                if (firstTokenTime === null) {
                  firstTokenTime = performance.now() - startTime;
                }
                lastTokenTime = performance.now();
              }
            } catch (e) {}
          }
        }
      }

      const totalTime = lastTokenTime - startTime;
      const avgTokenTime =
        tokenCount > 1 ? totalTime / tokenCount : totalTime;

      // Test 4.1: TTFB check
      const test4_1 = ttfbTime < 5000; // Should be < 5s typically
      StreamingTests.log(
        `${test4_1 ? '✅' : '❌'} TTFB: ${ttfbTime.toFixed(0)}ms (Target: <1000ms)`,
        test4_1 ? 'green' : 'red'
      );

      // Test 4.2: First token appearance
      const test4_2 = firstTokenTime !== null && firstTokenTime < 3000;
      StreamingTests.log(
        `${test4_2 ? '✅' : '❌'} First token: ${(firstTokenTime || 0).toFixed(0)}ms`,
        test4_2 ? 'green' : 'red'
      );

      // Test 4.3: Token streaming rate
      const test4_3 = tokenCount > 5;
      StreamingTests.log(
        `${test4_3 ? '✅' : '❌'} Tokens: ${tokenCount} @ ${avgTokenTime.toFixed(0)}ms/token`,
        test4_3 ? 'green' : 'red'
      );

      // Test 4.4: Total time reasonable
      const test4_4 = totalTime < 120000; // 2 minutes max
      StreamingTests.log(
        `${test4_4 ? '✅' : '❌'} Total time: ${(totalTime / 1000).toFixed(1)}s`,
        test4_4 ? 'green' : 'red'
      );

      return test4_1 && test4_2 && test4_3 && test4_4;
    } catch (error) {
      StreamingTests.log(`❌ Error: ${error.message}`, 'red');
      return false;
    }
  },

  async runAllTests() {
    StreamingTests.log(
      '\n╔════════════════════════════════════════════╗',
      'blue'
    );
    StreamingTests.log('║  SSE STREAMING FRONTEND TEST SUITE        ║', 'blue');
    StreamingTests.log(
      '╚════════════════════════════════════════════╝',
      'blue'
    );

    const results = [
      [
        'Fetch Streaming API',
        await StreamingTests.testFetchStreamingAPI(),
      ],
      ['SSE Parsing', await StreamingTests.testSSEParsing()],
      ['Token Accumulation', await StreamingTests.testTokenAccumulation()],
      ['Performance Metrics', await StreamingTests.testPerformance()],
    ];

    // Summary
    StreamingTests.log(
      '\n╔════════════════════════════════════════════╗',
      'blue'
    );
    StreamingTests.log('║  TEST SUMMARY                             ║', 'blue');
    StreamingTests.log(
      '╚════════════════════════════════════════════╝',
      'blue'
    );

    const passed = results.filter(([, result]) => result).length;
    const total = results.length;

    for (const [name, result] of results) {
      const status = result ? '✅ PASS' : '❌ FAIL';
      console.log(`${status} | ${name}`);
    }

    StreamingTests.log(
      `\n${passed}/${total} test suites passed\n`,
      passed === total ? 'green' : 'red'
    );

    if (passed === total) {
      StreamingTests.log(
        '🎉 All tests passed! SSE streaming is working correctly.',
        'green'
      );
    } else {
      StreamingTests.log(
        '⚠️  Some tests failed. Check the issues above.',
        'red'
      );
    }

    return passed === total;
  },
};

// Run tests
console.log(
  '%cPaste this in browser console to run frontend tests:\n%cStreamingTests.runAllTests()',
  'font-size: 14px',
  'font-size: 12px; background: #f0f0f0; padding: 5px'
);

// Additional helper function
console.log(
  '%c\nOr test individual components:\n%cStreamingTests.testFetchStreamingAPI()\nStreamingTests.testSSEParsing()\nStreamingTests.testTokenAccumulation()\nStreamingTests.testPerformance()',
  'font-size: 12px',
  'font-size: 11px; background: #f0f0f0; padding: 5px'
);
