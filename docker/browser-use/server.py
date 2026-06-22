"""Browser-Use HTTP API for CentralChat web_search tool.

POST /search  {"query": "...", "limit": 5}
POST /health

No API keys in this container — the caller provides the LLM key.
"""

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

HOST = os.environ.get("BROWSER_USE_HOST", "0.0.0.0")
PORT = int(os.environ.get("BROWSER_USE_PORT", "8081"))


class SearchHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/health":
            self.send_json({"status": "ok", "browser_use": True})
            return

        if path == "/search":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                req = json.loads(body)
            except json.JSONDecodeError:
                self.send_json({"error": "invalid JSON"}, 400)
                return

            query = req.get("query", "")
            limit = req.get("limit", 5)

            if not query:
                self.send_json({"error": "query is required"}, 400)
                return

            try:
                results = self.search(query, limit)
                self.send_json({"results": results})
            except Exception as e:
                self.send_json(
                    {"error": str(e), "results": []}, 500
                )
        else:
            self.send_json({"error": "not found"}, 404)

    def search(self, query, limit):
        """Use browser-use to search and extract results."""
        from browser_use import Agent
        from langchain_openai import ChatOpenAI

        task = (
            f"Search the web for: {query}. "
            f"Return up to {limit} results as a JSON array. "
            f"Each result must have: title, url, snippet. "
            f"Respond ONLY with the JSON array, no other text."
        )

        llm = ChatOpenAI(model="gpt-4o-mini")
        agent = Agent(task=task, llm=llm)
        result = agent.run()

        # Try to parse JSON from the result
        text = str(result)
        try:
            # Find JSON array in the output
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                if isinstance(parsed, list):
                    return parsed[:limit]
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: extract URLs and use them as results
        lines = text.split("\n")
        results = []
        for line in lines:
            line = line.strip()
            if line.startswith(("http://", "https://")):
                results.append({
                    "title": "",
                    "url": line,
                    "snippet": "",
                })
            if len(results) >= limit:
                break
        return results

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Quiet logging
        pass


if __name__ == "__main__":
    print(f"Browser-Use API listening on {HOST}:{PORT}")
    HTTPServer((HOST, PORT), SearchHandler).serve_forever()
