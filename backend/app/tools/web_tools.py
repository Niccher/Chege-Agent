import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse
import httpx
from pydantic import BaseModel, Field
from backend.app.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult

BLOCKED_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "::1", "metadata.google.internal"}


def is_safe_url(url: str) -> tuple[bool, str]:
    """Validate that a URL uses http/https and does not resolve to private/local/metadata IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "URL must begin with http:// or https://"
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False, "URL missing hostname"
    if hostname in BLOCKED_HOSTNAMES:
        return False, f"Access to blocked host '{hostname}' is prohibited"

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False, f"Access to private/local network IP '{hostname}' is prohibited"
    except ValueError:
        try:
            addr_infos = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in addr_infos:
                ip_str = sockaddr[0]
                ip = ipaddress.ip_address(ip_str)
                if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                    return False, f"Hostname '{hostname}' resolves to private/local network IP '{ip_str}'"
        except socket.gaierror as e:
            return False, f"Could not resolve hostname '{hostname}': {e}"
        except Exception as e:
            return False, f"Failed address validation for '{hostname}': {e}"

    return True, ""


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
        safe, reason = is_safe_url(args.url)
        if not safe:
            return ToolResult(content=f"ERROR: {reason}.", is_error=True)

        current_url = args.url
        headers = {"User-Agent": "ChegeAgent/0.2.0 (+https://github.com/chege-agent)"}
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                resp = None
                for _ in range(5):
                    resp = await client.get(current_url, headers=headers)
                    if resp.is_redirect:
                        loc = resp.headers.get("Location")
                        if not loc:
                            break
                        redirect_url = urljoin(current_url, loc)
                        safe, reason = is_safe_url(redirect_url)
                        if not safe:
                            return ToolResult(content=f"ERROR: Redirect blocked: {reason}.", is_error=True)
                        current_url = redirect_url
                    else:
                        break

                if resp is None:
                    return ToolResult(content=f"ERROR: No response received from '{args.url}'", is_error=True)

                if resp.status_code >= 400:
                    return ToolResult(content=f"ERROR: HTTP {resp.status_code} fetching '{current_url}'", is_error=True)

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
