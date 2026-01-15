import asyncio
import time
import ssl
from dataclasses import dataclass, field
from typing import Optional, Dict

@dataclass
class Observation:
    """
    Standardized data contract for all probe outputs.
    Ensures consistent data structure for fingerprinting and storage logic.
    """
    # Transport Metadata
    ip: str
    port: int
    protocol: str       # tcp, udp
    service: str        # http, ssh, rtsp, etc. (inferred from probe type)
    latency_ms: float
    status: str         # open, closed, filtered, timeout, error
    
    timestamp: float = field(default_factory=time.time)
    
    # Error Context
    error_reason: Optional[str] = None
    
    # Identity Signals
    banner: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None
    cert_info: Dict[str, str] = field(default_factory=dict) # TLS Cert Info
    
    # Behavioral Signals
    response_code: Optional[int] = None # HTTP Status Code, etc.
    
    def to_dict(self):
        """Convert observation to dictionary for analyzing pipeline."""
        return {
            "ip": self.ip,
            "port": self.port,
            "protocol": self.protocol,
            "service": self.service,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
            "status": self.status,
            "error_reason": self.error_reason,
            "banner": self.banner,
            "headers": self.headers,
            "body": self.body,
            "cert_info": self.cert_info,
            "response_code": self.response_code
        }

class BaseProbe:
    """Abstract base class for all protocol-specific probes."""
    def __init__(self, port, timeout=1.5):
        self.port = port
        self.timeout = timeout

    async def run(self, ip_address: str) -> Observation:
        """Execute the probe against the target IP."""
        raise NotImplementedError

class TCPProbe(BaseProbe):
    """Basic TCP Connect Probe usually for generic ports."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000
            
            # Simple Banner Grab
            banner = ""
            try:
                # Read initial greeting if any
                data = await asyncio.wait_for(reader.read(1024), timeout=1.0)
                banner = data.decode('utf-8', errors='ignore').strip()
            except (asyncio.TimeoutError, Exception):
                pass # Connection works, just no banner
                
            writer.close()
            await writer.wait_closed()
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="tcp",
                latency_ms=latency, status="open", banner=banner
            )
            
        except asyncio.TimeoutError:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="tcp",
                latency_ms=(time.time() - start_time) * 1000, status="timeout", error_reason="Timeout"
            )
        except ConnectionRefusedError:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="tcp",
                latency_ms=(time.time() - start_time) * 1000, status="closed", error_reason="Refused"
            )
        except OSError as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="tcp",
                latency_ms=(time.time() - start_time) * 1000, status="error", error_reason=str(e)
            )

class HTTPProbe(BaseProbe):
    """Probe for HTTP/HTTPS services, extracting headers and titles."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            # TLS Configuration
            ssl_ctx = None
            if self.port in [443, 8443]:
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
            
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port, ssl=ssl_ctx), 
                timeout=self.timeout
            )
            
            # Send Minimal HTTP Request
            req = f"GET / HTTP/1.1\r\nHost: {ip_address}\r\nUser-Agent: DeepFocus/1.0\r\nConnection: close\r\n\r\n"
            writer.write(req.encode())
            await writer.drain()
            
            # Read Response
            data = await asyncio.wait_for(reader.read(4096), timeout=self.timeout)
            latency = (time.time() - start_time) * 1000
            
            writer.close()
            await writer.wait_closed()
            
            raw_response = data.decode('utf-8', errors='ignore')
            
            # Basic Parsing
            headers = {}
            body = None
            status_code = None
            
            parts = raw_response.split('\r\n\r\n', 1)
            head_part = parts[0]
            if len(parts) > 1:
                body = parts[1]
                
            lines = head_part.split('\r\n')
            if lines:
                # Parse Status Line (e.g. HTTP/1.1 200 OK)
                status_line = lines[0]
                if " " in status_line:
                    try:
                        status_code = int(status_line.split(" ")[1])
                    except ValueError:
                        pass
                
                # Parse Headers
                for line in lines[1:]:
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        headers[k.lower()] = v
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="https" if ssl_ctx else "http",
                latency_ms=latency, status="open", banner=head_part,
                headers=headers, body=body, response_code=status_code
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="http",
                latency_ms=(time.time() - start_time) * 1000, status="closed", error_reason=str(e)
            )

class VNCProbe(BaseProbe):
    """VNC (RFB) Probe checking for NO-AUTH configurations."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000
            
            # 1. Handshake Phase: Server Version
            server_version = await asyncio.wait_for(reader.read(12), timeout=2.0)
            
            # 2. Echo Version to Server
            writer.write(server_version)
            await writer.drain()
            
            # 3. Read Security Types offered
            sec_types_len_byte = await asyncio.wait_for(reader.read(1), timeout=2.0)
            if not sec_types_len_byte:
                raise Exception("Empty security payload")
                
            num_types = int.from_bytes(sec_types_len_byte, "big")
            
            if num_types == 0:
                # Server sent failure reason
                reason = await reader.read(100)
                banner = f"{server_version.decode().strip()} (Connect Failed: {reason.decode().strip()})"
            else:
                sec_types = await asyncio.wait_for(reader.read(num_types), timeout=2.0)
                
                # Identify Auth Types
                types_desc = []
                for b in sec_types:
                    if b == 1: types_desc.append("None (OPEN)")
                    elif b == 2: types_desc.append("VNC Auth")
                    elif b == 16: types_desc.append("TightVNC")
                    elif b == 19: types_desc.append("VeNCrypt (TLS)")
                    else: types_desc.append(f"Type({b})")
                
                auth_str = ", ".join(types_desc)
                banner = f"{server_version.decode().strip()} | Auth: [{auth_str}]"
            
            writer.close()
            await writer.wait_closed()
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="vnc",
                latency_ms=latency, status="open", banner=banner
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="vnc",
                latency_ms=(time.time() - start_time) * 1000, status="closed", error_reason=str(e)
            )

class FTPProbe(BaseProbe):
    """FTP Probe checking for Anonymous Login capabilities."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000
            
            # 1. Read Initial Banner
            banner = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            banner_str = banner.decode('utf-8', errors='ignore').strip()
            
            auth_status = "Unknown"
            
            if banner_str.startswith("220"):
                 # Attempt Anonymous Login
                writer.write(b"USER anonymous\r\n")
                await writer.drain()
                
                resp_user = await asyncio.wait_for(reader.read(1024), timeout=2.0)
                resp_user_str = resp_user.decode('utf-8', errors='ignore').strip()
                
                if resp_user_str.startswith("331"): # Password required
                    writer.write(b"PASS anonymous@\r\n")
                    await writer.drain()
                    
                    resp_pass = await asyncio.wait_for(reader.read(1024), timeout=2.0)
                    resp_pass_str = resp_pass.decode('utf-8', errors='ignore').strip()
                    
                    if resp_pass_str.startswith("230"):
                         auth_status = "Anonymous Access ALLOWED"
                    elif resp_pass_str.startswith("530"):
                        auth_status = "Anonymous Access DENIED (530)"
                    else:
                        auth_status = f"Login Failed Code: {resp_pass_str[:3]}"
                        
                elif resp_user_str.startswith("230"): 
                     auth_status = "Anonymous Access ALLOWED (No Pass)"
                elif resp_user_str.startswith("530"):
                     auth_status = "Anonymous User Rejected"
                elif resp_user_str.startswith("500") or "auth" in resp_user_str.lower():
                     auth_status = "Encryption Required (AUTH TLS)"
                else:
                     auth_status = f"Handshake Error: {resp_user_str[:3]}"
            
            final_banner = f"{banner_str} | Auth: [{auth_status}]"
            
            writer.close()
            await writer.wait_closed()
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="ftp",
                latency_ms=latency, status="open", banner=final_banner
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="ftp",
                latency_ms=(time.time() - start_time) * 1000, status="closed", error_reason=str(e)
            )

class SSHProbe(BaseProbe):
    """SSH Probe indentifying server versions and device types."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000
            
            # Read Server Banner
            server_banner = await asyncio.wait_for(reader.read(256), timeout=2.0)
            banner_str = server_banner.decode('utf-8', errors='ignore').strip()
            
            # Heuristics
            device_info = "SSH Service"
            banner_lower = banner_str.lower()
            
            if "dropbear" in banner_lower:
                device_info = "Dropbear (Embedded/IoT)"
            elif "cisco" in banner_lower:
                device_info = "Cisco IOS"
            elif "mikrotik" in banner_lower:
                device_info = "MikroTik Router"
            elif "openssh" in banner_lower:
                 device_info = "OpenSSH"
                 
            final_banner = f"{banner_str} | Device: [{device_info}]"
            
            writer.close()
            await writer.wait_closed()
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="ssh",
                latency_ms=latency, status="open", banner=final_banner
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="ssh",
                latency_ms=(time.time() - start_time) * 1000, status="closed", error_reason=str(e)
            )

class RTSPProbe(BaseProbe):
    """RTSP Probe for IP Cameras (Port 554) with Auth Detection."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000
            
            # Send RTSP OPTIONS (The 'Hello' of cameras)
            rtsp_request = f"OPTIONS rtsp://{ip_address}:{self.port}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: DeepFocus\r\n\r\n"
            writer.write(rtsp_request.encode())
            await writer.drain()
            
            response = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            response_str = response.decode('utf-8', errors='ignore')
            
            # Analyze Auth Status
            auth_status = "Unknown"
            camera_brand = "RTSP Camera"
            
            if "RTSP/1.0 200" in response_str:
                auth_status = "No Auth Required (OPEN)"
            elif "RTSP/1.0 401" in response_str:
                auth_status = "Auth Required"
            elif "RTSP/1.0 403" in response_str:
                auth_status = "Forbidden"
            
            # Identify Brand
            resp_lower = response_str.lower()
            brands = ["hikvision", "dahua", "axis", "foscam", "amcrest", "reolink", "ubiquiti"]
            for brand in brands:
                if brand in resp_lower:
                    camera_brand = brand.capitalize()
                    break
                
            final_banner = f"{camera_brand} | Auth: [{auth_status}]"
            
            writer.close()
            await writer.wait_closed()
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="rtsp",
                latency_ms=latency, status="open", banner=final_banner
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="rtsp",
                latency_ms=(time.time() - start_time) * 1000, status="closed", error_reason=str(e)
            )

class TelnetProbe(BaseProbe):
    """Telnet Probe for routers and IoT devices."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000
            
            # Read initial banner (negotiation might be needed for some servers, 
            # but many just dump text immediately)
            banner = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            banner_str = banner.decode('utf-8', errors='ignore').strip()
            # Clean up control characters (re is imported at top of file)
            banner_str = re.sub(r'[^\x20-\x7E]', '', banner_str)
            
            writer.close()
            await writer.wait_closed()
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="telnet",
                latency_ms=latency, status="open", banner=banner_str
            )
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="telnet",
                latency_ms=(time.time() - start_time) * 1000, status="closed", error_reason=str(e)
            )

class MQTTProbe(BaseProbe):
    """MQTT Probe checking for No-Auth Broker access."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000
            
            # MQTT v3.1.1 CONNECT Packet (Standard)
            # Fixed Header: 0x10 (Connect), Remaining Length
            # Var Header: Proto Name (MQTT), Lvl(4), Flags(0x02=Clean), KeepAlive
            # Payload: ClientID
            
            # Packet Construction:
            # Fixed: 10 10 (Connect, Len=16)
            # Proto: 00 04 4D 51 54 54 (Len, MQTT)
            # Lvl: 04 
            # Flags: 02 (Clean Session)
            # KeepAlive: 00 3C (60s)
            # ClientID: 00 04 74 65 73 74 (Len=4, "test")
            connect_packet = bytes.fromhex("101000044D5154540402003C000474657374")
            
            writer.write(connect_packet)
            await writer.drain()
            
            # Read CONNACK (Fixed: 20 02, Var: Flags, ReturnCode)
            response = await asyncio.wait_for(reader.read(4), timeout=2.0)
            
            status_msg = "Unknown"
            if len(response) >= 4 and response[0] == 0x20:
                return_code = response[3]
                if return_code == 0x00:
                    status_msg = "Access ALLOWED (No Auth)"
                elif return_code == 0x01:
                    status_msg = "Refused: Protocol Version"
                elif return_code == 0x02:
                    status_msg = "Refused: ID Rejected"
                elif return_code == 0x03:
                    status_msg = "Refused: Server Unavailable"
                elif return_code == 0x04:
                    status_msg = "Refused: Bad User/Pass"
                elif return_code == 0x05:
                    status_msg = "Refused: Not Authorized"
                else:
                    status_msg = f"Refused: Code {return_code}"
            
            writer.close()
            await writer.wait_closed()
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="mqtt",
                latency_ms=latency, status="open", banner=status_msg
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="mqtt",
                latency_ms=(time.time() - start_time) * 1000, status="closed", error_reason=str(e)
            )

def get_probe(port: int) -> BaseProbe:
    """Factory function to return the correct probe class for a port."""
    if port in [80, 8080, 8000, 443, 8443]: 
        return HTTPProbe(port)
    if port == 5900:
        return VNCProbe(port)
    if port == 21:
        return FTPProbe(port)
    if port == 22:
        return SSHProbe(port)
    if port == 554:
        return RTSPProbe(port)
    if port == 23:
        return TelnetProbe(port)
    if port == 1883:
        return MQTTProbe(port)
        
    return TCPProbe(port)
