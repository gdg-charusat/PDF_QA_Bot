#!/usr/bin/env python3
"""
SSE Streaming Implementation Test Suite
Tests the /ask-stream endpoint for proper Server-Sent Events format and token streaming
"""

import requests
import json
import time
import sys

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def print_test(name, passed, details=""):
    status = f"{Colors.GREEN}✅ PASS{Colors.END}" if passed else f"{Colors.RED}❌ FAIL{Colors.END}"
    print(f"{status} | {name}")
    if details:
        print(f"       {details}")

def test_fastapi_streaming():
    """Test 1: FastAPI streaming endpoint returns proper SSE format"""
    print(f"\n{Colors.BLUE}Test 1: FastAPI Streaming Endpoint{Colors.END}")
    print("=" * 60)
    
    try:
        # Example session - this should already exist in your RAG service
        # For testing, you may need to create a session first with /upload endpoint
        test_session_id = "test-session-123"
        test_question = "What is RAG?"
        
        start_time = time.time()
        response = requests.post(
            "http://localhost:8000/ask-stream",
            json={
                "question": test_question,
                "session_id": test_session_id
            },
            stream=True,
            timeout=30
        )
        ttfb = time.time() - start_time
        
        # Test 1.1: Check status code
        passed_1_1 = response.status_code == 200
        print_test(
            "HTTP Status Code 200",
            passed_1_1,
            f"Got {response.status_code}"
        )
        
        # Test 1.2: Check Content-Type header
        content_type = response.headers.get("Content-Type", "")
        passed_1_2 = "application/x-ndjson" in content_type or "text/event-stream" in content_type
        print_test(
            "Content-Type is text/event-stream or application/x-ndjson",
            passed_1_2,
            f"Got: {content_type}"
        )
        
        # Test 1.3: Check SSE headers
        cache_control = response.headers.get("Cache-Control", "")
        connection = response.headers.get("Connection", "")
        passed_1_3 = "no-cache" in cache_control and "keep-alive" in connection
        print_test(
            "SSE Headers (Cache-Control, Connection)",
            passed_1_3,
            f"Cache-Control: {cache_control}, Connection: {connection}"
        )
        
        # Test 1.4: Parse SSE messages
        tokens = []
        citations = None
        done_received = False
        
        print(f"\n{Colors.YELLOW}Streaming tokens:{Colors.END}")
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8') if isinstance(line, bytes) else line
                if line.startswith("data: "):
                    try:
                        message = json.loads(line[6:])
                        
                        if "event" in message:
                            if message["event"] == "citations" and "data" in message:
                                citations = message["data"]
                                print(f"  📎 Citations: {len(citations)} sources")
                            elif message["event"] == "done":
                                done_received = True
                                print(f"  ✓ Stream complete")
                        elif "token" in message:
                            token = message.get("token", "")
                            tokens.append(token)
                            sys.stdout.write(token)
                            sys.stdout.flush()
                    except json.JSONDecodeError as e:
                        print(f"  ⚠ JSON Parse Error: {e}")
        
        print("\n")
        
        # Test 1.5: Verify tokens received
        total_tokens = len(tokens)
        full_response = "".join(tokens)
        passed_1_5 = total_tokens > 0
        print_test(
            "Tokens received from stream",
            passed_1_5,
            f"Received {total_tokens} tokens, {len(full_response)} chars"
        )
        
        # Test 1.6: Verify done signal
        passed_1_6 = done_received
        print_test(
            "Done signal received",
            passed_1_6,
            "Stream ended with 'done' event"
        )
        
        # Test 1.7: Check TTFB
        passed_1_7 = ttfb < 5  # Should be much less than 15 seconds
        print_test(
            "Time to First Byte < 5 seconds",
            passed_1_7,
            f"TTFB: {ttfb:.2f}s (Target: <1s after buffering)"
        )
        
        return all([passed_1_1, passed_1_2, passed_1_3, passed_1_5, passed_1_6, passed_1_7])
        
    except requests.exceptions.ConnectionError:
        print(f"{Colors.RED}❌ Cannot connect to http://localhost:8000{Colors.END}")
        print("   Make sure FastAPI service is running: python rag-service/main.py")
        return False
    except Exception as e:
        print(f"{Colors.RED}❌ Error: {str(e)}{Colors.END}")
        return False

def test_node_gateway():
    """Test 2: Node.js gateway proxies streaming correctly"""
    print(f"\n{Colors.BLUE}Test 2: Node.js Gateway Proxy{Colors.END}")
    print("=" * 60)
    
    try:
        test_session_id = "test-session-123"
        test_question = "Explain streaming?"
        
        response = requests.post(
            "http://localhost:3001/ask-stream",
            json={
                "question": test_question,
                "session_ids": [test_session_id]
            },
            stream=True,
            timeout=30
        )
        
        # Test 2.1: Check status
        passed_2_1 = response.status_code == 200
        print_test(
            "Gateway HTTP Status 200",
            passed_2_1,
            f"Got {response.status_code}"
        )
        
        # Test 2.2: Check headers from gateway
        content_type = response.headers.get("Content-Type", "")
        passed_2_2 = "event-stream" in content_type or "ndjson" in content_type
        print_test(
            "Gateway forwards SSE headers",
            passed_2_2,
            f"Content-Type: {content_type}"
        )
        
        # Test 2.3: Parse proxied SSE stream
        tokens = []
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8') if isinstance(line, bytes) else line
                if line.startswith("data: "):
                    try:
                        message = json.loads(line[6:])
                        if "token" in message:
                            tokens.append(message["token"])
                    except:
                        pass
        
        passed_2_3 = len(tokens) > 0
        print_test(
            "Gateway proxies tokens correctly",
            passed_2_3,
            f"Received {len(tokens)} tokens through gateway"
        )
        
        return all([passed_2_1, passed_2_2, passed_2_3])
        
    except requests.exceptions.ConnectionError:
        print(f"{Colors.RED}❌ Cannot connect to http://localhost:3001{Colors.END}")
        print("   Make sure Node.js gateway is running: npm start")
        return False
    except Exception as e:
        print(f"{Colors.RED}❌ Error: {str(e)}{Colors.END}")
        return False

def test_sse_format():
    """Test 3: Verify SSE format compliance"""
    print(f"\n{Colors.BLUE}Test 3: SSE Format Compliance{Colors.END}")
    print("=" * 60)
    
    try:
        test_session_id = "test-session-123"
        
        response = requests.post(
            "http://localhost:8000/ask-stream",
            json={
                "question": "Test SSE format",
                "session_id": test_session_id
            },
            stream=True,
            timeout=30
        )
        
        line_count = 0
        data_line_count = 0
        valid_json_count = 0
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8') if isinstance(line, bytes) else line
                line_count += 1
                
                if line.startswith("data: "):
                    data_line_count += 1
                    try:
                        json.loads(line[6:])
                        valid_json_count += 1
                    except:
                        pass
        
        # Test 3.1: Has data lines
        passed_3_1 = data_line_count > 0
        print_test(
            "SSE stream contains data: lines",
            passed_3_1,
            f"Found {data_line_count} data lines"
        )
        
        # Test 3.2: Valid JSON in data lines
        passed_3_2 = valid_json_count == data_line_count
        print_test(
            "All SSE messages have valid JSON",
            passed_3_2,
            f"{valid_json_count}/{data_line_count} valid JSON"
        )
        
        return all([passed_3_1, passed_3_2])
        
    except Exception as e:
        print(f"{Colors.RED}❌ Error: {str(e)}{Colors.END}")
        return False

def main():
    print(f"\n{Colors.BLUE}{'='*60}")
    print("SSE TOKEN STREAMING TEST SUITE")
    print(f"{'='*60}{Colors.END}\n")
    
    results = []
    
    # Run tests
    results.append(("FastAPI Streaming", test_fastapi_streaming()))
    results.append(("Node.js Gateway", test_node_gateway()))
    results.append(("SSE Format", test_sse_format()))
    
    # Summary
    print(f"\n{Colors.BLUE}{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}{Colors.END}\n")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = f"{Colors.GREEN}✅ PASS{Colors.END}" if result else f"{Colors.RED}❌ FAIL{Colors.END}"
        print(f"{status} | {test_name}")
    
    print(f"\n{Colors.BLUE}Overall: {passed}/{total} test suites passed{Colors.END}\n")
    
    if passed == total:
        print(f"{Colors.GREEN}🎉 All tests passed! SSE streaming is working correctly.{Colors.END}\n")
        return 0
    else:
        print(f"{Colors.RED}⚠️  Some tests failed. Check the issues above.{Colors.END}\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
