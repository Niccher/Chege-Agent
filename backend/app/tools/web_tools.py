import re
import httpx
from pydantic import BaseModel, Field
from backend.app.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult


class WebFetchInput(BaseModel):
    url: str = Field(description="The full HTTP/HTTPS URL to fetch.")


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch webpage content and convert to readable text (size-capped at 30KB) (TL-07)."
    risk = RiskLevel.NETWORK
    args_model = WebFetchInput

    def _html_to_clean_text(self, html: str) -> str:
        # Strip script and style blocks
        clean = re.sub(r"<(script|style|svg|noscript)[^>]*>[\s\S]*?</\1>", "", html, flags=re.IGNORECASE)
        # Convert links <a href="url">text</a> -> [text](url)
        clean = re.sub(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", clean, flags=re.IGNORECASE)
        # Convert paragraph/headings/breaks
        clean = re.sub(r"<(h[1-6]|p|div|tr)[^>]*>", "\n", clean, flags=re.IGNORECASE)
        clean = re.sub(r"<br\s*/?>", "\n", clean, flags=re.IGNORECASE)
        # Strip remaining tags
        clean = re.sub(r"<[^>]+>", " ", clean)
        # Collapse multiple whitespace
        clean = re.sub(r"[ \t]+", " ", clean)
        clean = re.sub(r"\n\s*\n+", "\n\n", clean)
        return clean.strip()

    async def run(self, ctx: ToolContext, args: WebFetchInput) -> ToolResult:
        if not args.url.startswith(("http://", "https://")):
            return ToolResult(content="ERROR: URL must begin with http:// or https://", is_error=True)

        from urllib.parse import urlparse
        parsed = urlparse(args.url)
        hostname = (parsed.hostname or "").lower()
        blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "::1", "metadata.google.internal"}
        if (
            hostname in blocked_hosts
            or hostname.startswith("127.")
            or hostname.startswith("10.")
            or hostname.startswith("192.168.")
        ):
            return ToolResult(content=f"ERROR: Access to private network/internal host '{hostname}' is blocked for security.", is_error=True)


        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                headers = {"User-Agent": "ChegeAgent/0.2.0 (+https://github.com/chege-agent)"}
                resp = await client.get(args.url, headers=headers)
                if resp.status_code >= 400:
                    return ToolResult(content=f"ERROR: HTTP {resp.status_code} fetching '{args.url}'", is_error=True)

                raw_text = resp.text
                clean_text = self._html_to_clean_text(raw_text)

                max_chars = 30000
                truncated = False
                if len(clean_text) > max_chars:
                    truncated = True
                    clean_text = clean_text[:max_chars] + "\n\n... (Content truncated at 30KB)"

                return ToolResult(content=clean_text, truncated=truncated)
        except Exception as e:
            return ToolResult(content=f"ERROR fetching URL '{args.url}': {str(e)}", is_error=True)


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query terms")
    limit: int = Field(default=5, description="Number of search results to return (max 10)")


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for programming documentation, error messages, and API references (TL-07)."
    risk = RiskLevel.NETWORK
    args_model = WebSearchInput

    async def run(self, ctx: ToolContext, args: WebSearchInput) -> ToolResult:
        # Use DuckDuckGo HTML endpoint as default lightweight zero-credential backend
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                params = {"q": args.query}
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                resp = await client.get("https://html.duckduckgo.com/html/", params=params, headers=headers)

                if resp.status_code != 200:
                    return ToolResult(content=f"Search backend returned HTTP {resp.status_code}", is_error=True)

                # Extract result links and snippets
                results = []
                pattern = r'<a class="result__snippet"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
                for match in re.finditer(pattern, resp.text, re.DOTALL):
                    url, snippet = match.group(1), match.group(2)
                    clean_snippet = re.sub(r"<[^>]+>", "", snippet).strip()
                    results.append(f"- {clean_snippet} ({url})")
                    if len(results) >= args.limit:
                        break

                if not results:
                    return ToolResult(content=f"No web results found for query '{args.query}'.")

                return ToolResult(content=f"Web search results for '{args.query}':\n" + "\n".join(results))
        except Exception as e:
            return ToolResult(content=f"Web search failed: {str(e)}", is_error=True)
