import re
import json
from typing import List, Tuple, Dict, Any, Optional

class FingerprintRule:
    """
    Defines a weighted rule for identifying a service or product.
    Contains a set of evidence patterns (regex) that map to a confidence score.
    """
    def __init__(self, name: str, type: str = "unknown", vendor: str = None, product: str = None, tags: List[str] = None):
        self.name = name
        self.type = type
        self.vendor = vendor
        self.product = product
        self.tags = tags or []
        
        # Evidence Weights (Max 100)
        # Patterns: (location, regex, weight)
        self.evidence: List[Tuple[str, str, int]] = []
        self.last_groups = None

    def add_evidence(self, location: str, pattern: str, weight: int):
        """Add a weighted regex pattern for a specific request location (body, banner, header:X)."""
        self.evidence.append((location, pattern, weight))
        return self

    def evaluate(self, observation: Dict[str, Any]) -> Tuple[int, List[str]]:
        """
        Returns confidence score (0-100) and matched groups details.
        observation: Observation dictionary (provides .banner, .headers, .body, .cert_info)
        """
        total_score = 0
        details = []
        
        # Helper to check string against regex
        def check(text, regex):
            if not text: return False, None
            m = re.search(regex, text, re.IGNORECASE)
            return bool(m), m

        for location, pattern, weight in self.evidence:
            match = False
            groups = None
            
            if location == "banner":
                match, groups = check(observation.get("banner"), pattern)
            elif location == "body":
                match, groups = check(observation.get("body"), pattern)
            elif location.startswith("header:"):
                # Check specific header
                header_key = location.split(":")[1].lower()
                headers = observation.get("headers", {})
                val = headers.get(header_key)
                match, groups = check(val, pattern)
            elif location == "title":
                 match, groups = check(observation.get("body"), f"<title>.*{pattern}.*</title>")

            if match:
                total_score += weight
                details.append(f"Matched {location}")
                # Store matched groups for version extraction
                if groups:
                    self.last_groups = groups.groups()

        return min(total_score, 100), details

# Define Rules with Weighted Evidence
RULES = []

# Apache
r_apache = FingerprintRule("Apache", type="http", vendor="Apache", product="HTTP Server")
r_apache.add_evidence("banner", r"Apache", 40) # Weak signal
r_apache.add_evidence("banner", r"Apache/([\d\.]+)", 60) # Stronger signal + version
r_apache.add_evidence("header:server", r"Apache", 30) # Header reinforcement
RULES.append(r_apache)

# Nginx
r_nginx = FingerprintRule("Nginx", type="http", vendor="Nginx", product="Nginx")
r_nginx.add_evidence("banner", r"nginx", 40)
r_nginx.add_evidence("banner", r"nginx/([\d\.]+)", 60)
r_nginx.add_evidence("header:server", r"nginx", 30)
RULES.append(r_nginx)

# Hikvision
r_hik = FingerprintRule("Hikvision", type="camera", vendor="Hikvision", product="IP Camera", tags=["iot", "surveillance"])
r_hik.add_evidence("banner", r"Hikvision", 50)
r_hik.add_evidence("body", r"<title>Hikvision</title>", 60)
r_hik.add_evidence("header:server", r"Hikvision", 50)
r_hik.add_evidence("header:server", r"App-webs", 30) # Common Hikvision web server
RULES.append(r_hik)

# OpenSSH
r_ssh = FingerprintRule("OpenSSH", type="ssh", vendor="OpenBSD", product="OpenSSH")
r_ssh.add_evidence("banner", r"OpenSSH", 50)
r_ssh.add_evidence("banner", r"OpenSSH_([\w\.]+)", 50)
RULES.append(r_ssh)

# Generic Rules (Fallbacks)
r_gen_http = FingerprintRule("Generic HTTP", type="http", vendor="unknown", product="HTTP Server")
r_gen_http.add_evidence("banner", r"HTTP/\d\.\d", 30) # Basic protocol header
r_gen_http.add_evidence("banner", r"Server:", 20)
r_gen_http.add_evidence("body", r"<html", 40)
RULES.append(r_gen_http)

r_gen_rtsp = FingerprintRule("Generic RTSP", type="rtsp", vendor="unknown", product="RTSP Server")
r_gen_rtsp.add_evidence("banner", r"RTSP/\d\.\d", 50)
RULES.append(r_gen_rtsp)

# VNC
r_vnc = FingerprintRule("VNC", type="vnc", vendor="RealVNC", product="VNC Server", tags=["remote_desktop"])
r_vnc.add_evidence("banner", r"^RFB \d{3}\.\d{3}", 100)
RULES.append(r_vnc)

# FTP
r_ftp = FingerprintRule("FTP", type="ftp", vendor="unknown", product="FTP Server", tags=["file_transfer"])
r_ftp.add_evidence("banner", r"^220.*FTP", 80)
r_ftp.add_evidence("banner", r"vsftpd", 90)
r_ftp.add_evidence("banner", r"ProFTPD", 90)
RULES.append(r_ftp)

# Caddy
r_caddy = FingerprintRule("Caddy", type="http", vendor="Caddy", product="Caddy Web Server")
r_caddy.add_evidence("header:server", r"Caddy", 100)
RULES.append(r_caddy)

# Dahua
r_dahua = FingerprintRule("Dahua", type="camera", vendor="Dahua", product="IP Camera", tags=["iot", "surveillance"])
r_dahua.add_evidence("banner", r"Dahua", 60)
r_dahua.add_evidence("header:server", r"Dahua", 60)
r_dahua.add_evidence("body", r"dahua", 40)
RULES.append(r_dahua)

# Home Assistant
r_ha = FingerprintRule("Home Assistant", type="iot", vendor="Home Assistant", product="Home Assistant", tags=["smart_home"])
r_ha.add_evidence("body", r"Home Assistant", 80)
r_ha.add_evidence("title", r"Home Assistant", 80)
RULES.append(r_ha)


def analyze(observation_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyzes an Observation dictionary using weighted rules to identify the technology stack.
    Returns an analysis dictionary containing service_type, vendor, product, version, and confidence score.
    """
    best_rule = None
    best_score = 0
    best_details = []
    
    for rule in RULES:
        score, details = rule.evaluate(observation_dict)
        if score > best_score:
            best_score = score
            best_rule = rule
            best_details = details
            
    result = {
        "service_type": "unknown",
        "vendor": "unknown",
        "product": "unknown",
        "version": None,
        "tags": [],
        "confidence": 0, # Explainability
        "evidence": []
    }
    
    if best_rule and best_score > 0:
        result["service_type"] = best_rule.type
        result["vendor"] = best_rule.vendor or "unknown"
        result["product"] = best_rule.product or "unknown"
        result["tags"] = best_rule.tags
        result["confidence"] = best_score
        result["evidence"] = best_details
        
        # Version extraction (heuristic)
        if hasattr(best_rule, 'last_groups') and best_rule.last_groups:
             result["version"] = best_rule.last_groups[0]
             
    return result
