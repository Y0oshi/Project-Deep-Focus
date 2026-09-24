import re
from typing import List, Tuple, Dict, Any

class FingerprintRule:
    """A weighted set of regex evidence that identifies a service or product."""
    def __init__(self, name: str, type: str = "unknown", vendor: str = None, product: str = None, tags: List[str] = None):
        self.name = name
        self.type = type
        self.vendor = vendor
        self.product = product
        self.tags = tags or []

        # Evidence patterns: (location, regex, weight), capped at 100 total.
        self.evidence: List[Tuple[str, str, int]] = []
        self.last_groups = None

    def add_evidence(self, location: str, pattern: str, weight: int):
        """Add a weighted regex pattern for a specific request location (body, banner, header:X)."""
        self.evidence.append((location, pattern, weight))
        return self

    def evaluate(self, observation: Dict[str, Any]) -> Tuple[int, List[str]]:
        """Return (confidence 0-100, matched evidence details) for an observation."""
        total_score = 0
        details = []
        self.last_groups = None  # avoid leaking a stale version between observations

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
                header_key = location.split(":")[1].lower()
                headers = observation.get("headers", {})
                val = headers.get(header_key)
                match, groups = check(val, pattern)
            elif location == "title":
                 match, groups = check(observation.get("body"), f"<title>.*{pattern}.*</title>")

            if match:
                total_score += weight
                details.append(f"Matched {location}")
                # A re.Match is truthy even with zero capture groups; only
                # overwrite when groups were actually captured, otherwise a
                # later non-capturing match would wipe a captured version.
                if groups and groups.groups():
                    self.last_groups = groups.groups()

        return min(total_score, 100), details

# Define Rules with Weighted Evidence
RULES = []

# Apache
r_apache = FingerprintRule("Apache", type="http", vendor="Apache", product="HTTP Server")
r_apache.add_evidence("banner", r"Apache", 40)
r_apache.add_evidence("banner", r"Apache/([\d\.]+)", 60)
r_apache.add_evidence("header:server", r"Apache", 30)
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

# Dropbear (embedded/IoT SSH)
r_dropbear = FingerprintRule("Dropbear", type="ssh", vendor="Dropbear", product="SSH Server", tags=["iot", "embedded"])
r_dropbear.add_evidence("banner", r"dropbear", 80)
r_dropbear.add_evidence("banner", r"dropbear[_/]([\w\.]+)", 40)
RULES.append(r_dropbear)

# MikroTik RouterOS (SSH banner)
r_mikrotik = FingerprintRule("MikroTik", type="ssh", vendor="MikroTik", product="RouterOS", tags=["network", "router"])
r_mikrotik.add_evidence("banner", r"mikrotik", 80)
r_mikrotik.add_evidence("banner", r"routeros", 80)
RULES.append(r_mikrotik)

# Cisco IOS (SSH banner)
r_cisco = FingerprintRule("Cisco IOS", type="ssh", vendor="Cisco", product="IOS", tags=["network", "router"])
r_cisco.add_evidence("banner", r"cisco", 80)
RULES.append(r_cisco)

# Generic SSH (any SSH protocol banner)
r_gen_ssh = FingerprintRule("Generic SSH", type="ssh", vendor="unknown", product="SSH Server")
r_gen_ssh.add_evidence("banner", r"^SSH-\d\.\d", 50)
RULES.append(r_gen_ssh)

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
    """Score an observation against all rules and return the best match."""
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
        "confidence": 0,
        "evidence": []
    }
    
    if best_rule and best_score > 0:
        result["service_type"] = best_rule.type
        result["vendor"] = best_rule.vendor or "unknown"
        result["product"] = best_rule.product or "unknown"
        result["tags"] = best_rule.tags
        result["confidence"] = best_score
        result["evidence"] = best_details

        if hasattr(best_rule, 'last_groups') and best_rule.last_groups:
            result["version"] = best_rule.last_groups[0]
             
    return result
