"""SharePoint 2019 REST & SOAP client with Windows SSO / SSPI / NTLM support."""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin
import requests
from requests_negotiate_sspi import HttpNegotiateAuth
from requests_ntlm import HttpNtlmAuth

logger = logging.getLogger(__name__)


class SharePointClientError(Exception):
    """Base exception for SharePoint client errors."""


class SharePointClient:
    """Client for querying SharePoint 2019 REST APIs and Nintex Workflow SOAP services."""

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        domain: str | None = None,
        verify_ssl: bool = True,
        timeout: int = 60,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.verify = verify_ssl

        # Configure Authentication
        if username and password:
            auth_user = f"{domain}\\{username}" if domain else username
            logger.info("Using NTLM authentication for user: %s", auth_user)
            self.session.auth = HttpNtlmAuth(auth_user, password)
        else:
            logger.info("Using Windows SSPI / Negotiate authentication (current user SSO)")
            self.session.auth = HttpNegotiateAuth()

        # Default headers
        self.session.headers.update({
            "User-Agent": "sp_extractor/0.1.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json;odata=nometadata",
        })

    def resolve_url(self, path_or_url: str) -> str:
        """Resolve a relative or absolute URL against the site base URL / origin."""
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            parsed = urlparse(path_or_url)
            # Ensure query stays on the same host origin
            return f"{self.origin}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")
        if path_or_url.startswith("/"):
            return f"{self.origin}{path_or_url}"
        return f"{self.base_url}/{path_or_url}"

    def get(
        self,
        path_or_url: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> dict | list | str:
        """Execute a GET request against SharePoint REST API and return parsed JSON."""
        full_url = self.resolve_url(path_or_url)
        req_headers = dict(self.session.headers)
        if headers:
            req_headers.update(headers)

        res = self.session.get(full_url, params=params, headers=req_headers, timeout=self.timeout)

        # Fallback to verbose odata if server complains about nometadata
        if res.status_code == 406 or (not res.ok and "odata" in res.text.lower()):
            req_headers["Accept"] = "application/json;odata=verbose"
            res = self.session.get(full_url, params=params, headers=req_headers, timeout=self.timeout)

        if not res.ok:
            raise SharePointClientError(
                f"HTTP {res.status_code} from {full_url}: {res.text[:400]}"
            )

        content_type = res.headers.get("Content-Type", "")
        if "application/json" in content_type:
            data = res.json()
            # If verbose response format: data['d']['results'] or data['d']
            if isinstance(data, dict) and "d" in data:
                d = data["d"]
                if isinstance(d, dict) and "results" in d:
                    return d["results"]
                return d
            return data
        return res.text

    def get_all(
        self,
        path_or_url: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> list[dict]:
        """Fetch all pages of a collection following odata pagination links."""
        items: list[dict] = []
        next_url: str | None = self.resolve_url(path_or_url)

        while next_url:
            full_url = self.resolve_url(next_url)
            req_headers = dict(self.session.headers)
            if headers:
                req_headers.update(headers)

            res = self.session.get(full_url, params=params, headers=req_headers, timeout=self.timeout)
            if res.status_code == 406 or (not res.ok and "odata" in res.text.lower()):
                req_headers["Accept"] = "application/json;odata=verbose"
                res = self.session.get(full_url, params=params, headers=req_headers, timeout=self.timeout)

            if not res.ok:
                raise SharePointClientError(
                    f"HTTP {res.status_code} in get_all from {full_url}: {res.text[:400]}"
                )

            data = res.json()
            if isinstance(data, dict):
                # odata=nometadata structure: {"value": [...], "odata.nextLink": "..."}
                if "value" in data and isinstance(data["value"], list):
                    items.extend(data["value"])
                    next_url = data.get("odata.nextLink")
                # odata=verbose structure: {"d": {"results": [...], "__next": "..."}}
                elif "d" in data and isinstance(data["d"], dict):
                    results = data["d"].get("results", [])
                    if isinstance(results, list):
                        items.extend(results)
                    next_url = data["d"].get("__next")
                else:
                    break
            elif isinstance(data, list):
                items.extend(data)
                break
            else:
                break

            params = None  # query parameters are already encoded in next_url

        return items

    def export_nintex_workflow(
        self,
        workflow_name: str,
        list_name: str = "",
        workflow_type: str = "list",
    ) -> str:
        """Call Nintex Workflow SOAP service (ExportWorkflow) to download the .nwf XML.

        Endpoint: {site_url}/_vti_bin/NintexWorkflow/Workflow.asmx
        """
        soap_url = f"{self.base_url}/_vti_bin/NintexWorkflow/Workflow.asmx"
        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ExportWorkflow xmlns="http://nintex.com">
      <workflowName>{self._escape_xml(workflow_name)}</workflowName>
      <listName>{self._escape_xml(list_name)}</listName>
      <workflowType>{self._escape_xml(workflow_type)}</workflowType>
    </ExportWorkflow>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://nintex.com/ExportWorkflow",
        }

        res = self.session.post(soap_url, data=soap_body.encode("utf-8"), headers=headers, timeout=self.timeout)
        if not res.ok:
            raise SharePointClientError(
                f"Nintex ExportWorkflow failed (HTTP {res.status_code}) for '{workflow_name}' "
                f"(list: '{list_name}'): {res.text[:400]}"
            )

        root = ET.fromstring(res.text)
        # Find ExportWorkflowResult ignoring namespace
        result_elem = None
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "ExportWorkflowResult":
                result_elem = elem
                break

        if result_elem is None or not result_elem.text:
            raise SharePointClientError(
                f"Empty or missing ExportWorkflowResult in Nintex response for '{workflow_name}'"
            )

        return result_elem.text

    @staticmethod
    def _escape_xml(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

