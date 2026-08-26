import asyncio
import re
import time
import ssl
from dataclasses import dataclass, field
from typing import Optional, Dict


def _error_status(exc: Exception) -> str:
    """Map a probe exception to a normalized Observation status string.

    Distinguishes timeout (filtered/no response) from closed (RST) and other
    errors, instead of collapsing everything into 'closed'.
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(exc, ConnectionRefusedError):
        return "closed"
    return "error"


def _extract_cert_info(ssl_obj) -> Dict[str, str]:
    """Extract TLS certificate metadata from an SSL object.

    With verify_mode=CERT_NONE, getpeercert(binary_form=False) returns {} (the
    decoded cert is not retained), so we fetch the DER bytes and decode them
    with `cryptography` when available. Falls back to an empty dict gracefully.
    """
    cert_info: Dict[str, str] = {}
    der = ssl_obj.getpeercert(binary_form=True)
    if not der:
        return cert_info
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID

        cert = x509.load_der_x509_certificate(der)

        def cn(name):
            attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
            return attrs[0].value if attrs else "Unknown"

        cert_info["subject_cn"] = cn(cert.subject)
        cert_info["issuer_cn"] = cn(cert.issuer)
        cert_info["self_signed"] = cert.subject == cert.issuer

        not_after = getattr(cert, "not_valid_after_utc", None)
        if not_after is not None:
            cert_info["not_after"] = not_after.isoformat()
    except Exception:
        # cryptography not installed or cert could not be decoded.
        pass
    return cert_info


@dataclass
class Observation:
    """Standardized result every probe returns."""
    ip: str
    port: int
    protocol: str
    service: str
    latency_ms: float
    status: str  # open, closed, timeout, error

    timestamp: float = field(default_factory=time.time)
    error_reason: Optional[str] = None
    banner: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None
    cert_info: Dict[str, str] = field(default_factory=dict)
    response_code: Optional[int] = None

    def to_dict(self):
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
    """Generic TCP connect probe."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000

            banner = ""
            try:
                data = await asyncio.wait_for(reader.read(1024), timeout=1.0)
                banner = data.decode('utf-8', errors='ignore').strip()
            except (asyncio.TimeoutError, Exception):
                pass
                
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
    """Probe for HTTP/HTTPS with TLS cert/cipher detection."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            ssl_ctx = None
            cert_info = {}
            cipher_info = None

            if self.port in [443, 8443]:
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port, ssl=ssl_ctx),
                timeout=self.timeout
            )

            # Grab cipher and cert for TLS connections.
            if ssl_ctx:
                ssl_obj = writer.get_extra_info('ssl_object')
                if ssl_obj:
                    cipher = ssl_obj.cipher()
                    if cipher:
                        cipher_info = f"{cipher[0]} ({cipher[1]})"
                    cert_info = _extract_cert_info(ssl_obj)

            req = f"GET / HTTP/1.1\r\nHost: {ip_address}\r\nUser-Agent: DeepFocus/1.0\r\nConnection: close\r\n\r\n"
            writer.write(req.encode())
            await writer.drain()

            data = await asyncio.wait_for(reader.read(4096), timeout=self.timeout)
            latency = (time.time() - start_time) * 1000

            writer.close()
            await writer.wait_closed()

            raw_response = data.decode('utf-8', errors='ignore')

            headers = {}
            body = None
            status_code = None

            parts = raw_response.split('\r\n\r\n', 1)
            head_part = parts[0]
            if len(parts) > 1:
                body = parts[1]

            lines = head_part.split('\r\n')
            if lines:
                status_line = lines[0]
                if " " in status_line:
                    try:
                        status_code = int(status_line.split(" ")[1])
                    except ValueError:
                        pass

                for line in lines[1:]:
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        headers[k.lower()] = v

            # Append cipher/cert info to the banner.
            service_type = "https" if ssl_ctx else "http"
            banner_parts = [head_part[:200]]
            
            if cipher_info:
                banner_parts.append(f"Cipher:[{cipher_info}]")
            
            if cert_info:
                self_signed_tag = "[SELF-SIGNED]" if cert_info.get('self_signed') else ""
                banner_parts.append(f"Cert:[{cert_info.get('subject_cn', '?')}] Issuer:[{cert_info.get('issuer_cn', '?')}] {self_signed_tag}")
            
            final_banner = " | ".join(banner_parts)
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service=service_type,
                latency_ms=latency, status="open", banner=final_banner,
                headers=headers, body=body, response_code=status_code,
                cert_info=cert_info
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="http",
                latency_ms=(time.time() - start_time) * 1000, status=_error_status(e), error_reason=str(e)
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
            
            server_version = await asyncio.wait_for(reader.read(12), timeout=2.0)
            writer.write(server_version)
            await writer.drain()

            sec_types_len_byte = await asyncio.wait_for(reader.read(1), timeout=2.0)
            if not sec_types_len_byte:
                raise Exception("Empty security payload")

            num_types = int.from_bytes(sec_types_len_byte, "big")

            if num_types == 0:
                # Server sent a failure reason instead of security types.
                reason = await reader.read(100)
                banner = f"{server_version.decode().strip()} (Connect Failed: {reason.decode().strip()})"
            else:
                sec_types = await asyncio.wait_for(reader.read(num_types), timeout=2.0)

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
                latency_ms=(time.time() - start_time) * 1000, status=_error_status(e), error_reason=str(e)
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
            
            banner = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            banner_str = banner.decode('utf-8', errors='ignore').strip()

            auth_status = "Unknown"

            if banner_str.startswith("220"):
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
                elif resp_user_str.startswith("550"):
                     auth_status = "Anonymous User Rejected (550)"
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
                latency_ms=(time.time() - start_time) * 1000, status=_error_status(e), error_reason=str(e)
            )

class SSHProbe(BaseProbe):
    """SSH Probe with full cipher/kex/MAC enumeration."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000
            
            server_banner = await asyncio.wait_for(reader.readline(), timeout=2.0)
            banner_str = server_banner.decode('utf-8', errors='ignore').strip()
            
            # Both sides send a banner before key exchange begins.
            client_banner = b"SSH-2.0-DeepFocus_Scanner\r\n"
            writer.write(client_banner)
            await writer.drain()
            
            # Binary packet: 4-byte length, then payload.
            kex_header = await asyncio.wait_for(reader.read(5), timeout=3.0)
            if len(kex_header) < 5:
                raise Exception("Short KEX header")
            
            packet_len = int.from_bytes(kex_header[0:4], 'big')

            # Read rest of packet (limit to 32KB for safety)
            packet_len = min(packet_len, 32768)
            kex_payload = await asyncio.wait_for(reader.read(packet_len - 1), timeout=3.0)
            
            # Parse SSH_MSG_KEXINIT (msg_type = 20)
            crypto_info = {}
            if len(kex_payload) > 17 and kex_payload[0] == 20:  # SSH_MSG_KEXINIT
                # Skip: msg_type(1) + cookie(16) = 17 bytes
                offset = 17
                
                # Helper to read name-list (uint32 len + comma-separated string)
                def read_namelist(data, off):
                    if off + 4 > len(data):
                        return [], off
                    length = int.from_bytes(data[off:off+4], 'big')
                    off += 4
                    if off + length > len(data):
                        return [], off
                    names = data[off:off+length].decode('utf-8', errors='ignore')
                    return names.split(','), off + length
                
                # Read algorithm lists in order per RFC 4253
                crypto_info['kex_algorithms'], offset = read_namelist(kex_payload, offset)
                crypto_info['host_key_algorithms'], offset = read_namelist(kex_payload, offset)
                crypto_info['ciphers_client_to_server'], offset = read_namelist(kex_payload, offset)
                crypto_info['ciphers_server_to_client'], offset = read_namelist(kex_payload, offset)
                crypto_info['mac_client_to_server'], offset = read_namelist(kex_payload, offset)
                crypto_info['mac_server_to_client'], offset = read_namelist(kex_payload, offset)
            
            device_info = "SSH"
            banner_lower = banner_str.lower()
            if "dropbear" in banner_lower:
                device_info = "Dropbear (IoT)"
            elif "cisco" in banner_lower:
                device_info = "Cisco IOS"
            elif "mikrotik" in banner_lower:
                device_info = "MikroTik"
            elif "openssh" in banner_lower:
                device_info = "OpenSSH"
            
            # top 3 of each algorithm list
            kex = crypto_info.get('kex_algorithms', [])[:3]
            ciphers = crypto_info.get('ciphers_client_to_server', [])[:3]
            macs = crypto_info.get('mac_client_to_server', [])[:3]
            hostkeys = crypto_info.get('host_key_algorithms', [])[:3]
            
            crypto_summary = f"KEX:[{','.join(kex)}] Ciphers:[{','.join(ciphers)}] MACs:[{','.join(macs)}] HostKeys:[{','.join(hostkeys)}]"
            
            final_banner = f"{banner_str} | {device_info} | {crypto_summary}"
            
            writer.close()
            await writer.wait_closed()
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="ssh",
                latency_ms=latency, status="open", banner=final_banner
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="ssh",
                latency_ms=(time.time() - start_time) * 1000, status=_error_status(e), error_reason=str(e)
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
            
            rtsp_request = f"OPTIONS rtsp://{ip_address}:{self.port}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: DeepFocus\r\n\r\n"
            writer.write(rtsp_request.encode())
            await writer.drain()
            
            response = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            response_str = response.decode('utf-8', errors='ignore')
            
            auth_status = "Unknown"
            camera_brand = "RTSP Camera"
            
            if "RTSP/1.0 200" in response_str:
                auth_status = "No Auth Required (OPEN)"
            elif "RTSP/1.0 401" in response_str:
                auth_status = "Auth Required"
            elif "RTSP/1.0 403" in response_str:
                auth_status = "Forbidden"
            
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
                latency_ms=(time.time() - start_time) * 1000, status=_error_status(e), error_reason=str(e)
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
            
            banner = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            banner_str = banner.decode('utf-8', errors='ignore').strip()
            banner_str = re.sub(r'[^\x20-\x7E]', '', banner_str)  # strip control chars
            
            writer.close()
            await writer.wait_closed()
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="telnet",
                latency_ms=latency, status="open", banner=banner_str
            )
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="telnet",
                latency_ms=(time.time() - start_time) * 1000, status=_error_status(e), error_reason=str(e)
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
            
            # MQTT v3.1.1 CONNECT with clean session, no auth.
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
                latency_ms=(time.time() - start_time) * 1000, status=_error_status(e), error_reason=str(e)
            )

class RDPProbe(BaseProbe):
    """RDP Probe for Windows Remote Desktop detection."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000
            
            # Minimal TPKT + X.224 Connection Request to start RDP negotiation.
            x224_conn_request = bytes.fromhex(
                "030000130ee000000000000100080003000000"
            )
            
            writer.write(x224_conn_request)
            await writer.drain()
            
            response = await asyncio.wait_for(reader.read(256), timeout=3.0)

            banner = "RDP Service Detected"

            if len(response) >= 11:
                # Connection Confirm is byte 0xd0.
                if response[5] == 0xd0:
                    if len(response) >= 19:
                        neg_type = response[11] if len(response) > 11 else 0
                        if neg_type == 0x02:  # TYPE_RDP_NEG_RSP
                            protocol = response[15] if len(response) > 15 else 0
                            
                            if protocol == 0x00:
                                banner = "RDP (Standard RDP Security)"
                            elif protocol == 0x01:
                                banner = "RDP (TLS Security)"
                            elif protocol == 0x02:
                                banner = "RDP (CredSSP/NLA Required)"
                            elif protocol == 0x03:
                                banner = "RDP (TLS + CredSSP/NLA)"
                            else:
                                banner = f"RDP (Protocol: {protocol})"
                        elif neg_type == 0x03:  # TYPE_RDP_NEG_FAILURE
                            banner = "RDP (Negotiation Failed)"
                        else:
                            banner = "RDP (Unknown Response)"
                    else:
                        banner = "RDP (Legacy/No NLA)"
                elif response[5] == 0x00:
                    banner = "RDP (Connection Refused)"
            
            writer.close()
            await writer.wait_closed()
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="rdp",
                latency_ms=latency, status="open", banner=banner
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="rdp",
                latency_ms=(time.time() - start_time) * 1000, status=_error_status(e), error_reason=str(e)
            )
class SMTPProbe(BaseProbe):
    """SMTP Probe with STARTTLS cipher detection."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            conn = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port),
                timeout=self.timeout
            )
            reader, writer = conn
            latency = (time.time() - start_time) * 1000
            
            banner = await asyncio.wait_for(reader.readline(), timeout=2.0)
            banner_str = banner.decode('utf-8', errors='ignore').strip()

            writer.write(b"EHLO deepfocus.local\r\n")
            await writer.drain()

            ehlo_response = ""
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=2.0)
                ehlo_response += line.decode('utf-8', errors='ignore')
                if line[3:4] == b' ':  # last line has a space after the code
                    break
            
            cipher_info = None
            starttls_supported = "STARTTLS" in ehlo_response.upper()
            
            if starttls_supported:
                writer.write(b"STARTTLS\r\n")
                await writer.drain()

                response = await asyncio.wait_for(reader.readline(), timeout=2.0)
                if response.startswith(b"220"):
                    ssl_ctx = ssl.create_default_context()
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE

                    transport = writer.transport
                    protocol = transport.get_protocol()
                    await writer.drain()

                    new_transport = await asyncio.get_event_loop().start_tls(
                        transport, protocol, ssl_ctx, server_hostname=ip_address
                    )

                    ssl_obj = new_transport.get_extra_info('ssl_object')
                    if ssl_obj:
                        cipher = ssl_obj.cipher()
                        if cipher:
                            cipher_info = f"{cipher[0]} ({cipher[1]})"
            
            writer.close()
            await writer.wait_closed()
            
            final_banner = f"{banner_str} | STARTTLS:[{'YES' if starttls_supported else 'NO'}]"
            if cipher_info:
                final_banner += f" | Cipher:[{cipher_info}]"
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="smtp",
                latency_ms=latency, status="open", banner=final_banner
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="smtp",
                latency_ms=(time.time() - start_time) * 1000, status=_error_status(e), error_reason=str(e)
            )

class LDAPSProbe(BaseProbe):
    """LDAPS Probe (Port 636) with TLS cipher detection."""
    async def run(self, ip_address: str) -> Observation:
        start_time = time.time()
        try:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip_address, self.port, ssl=ssl_ctx),
                timeout=self.timeout
            )
            latency = (time.time() - start_time) * 1000
            
            ssl_obj = writer.get_extra_info('ssl_object')
            cipher_info = None
            cert_info = {}

            if ssl_obj:
                cipher = ssl_obj.cipher()
                if cipher:
                    cipher_info = f"{cipher[0]} ({cipher[1]})"
                cert_info = _extract_cert_info(ssl_obj)
            
            writer.close()
            await writer.wait_closed()
            
            banner = "LDAPS Service"
            if cipher_info:
                banner += f" | Cipher:[{cipher_info}]"
            if cert_info:
                self_signed_tag = "[SELF-SIGNED]" if cert_info.get('self_signed') else ""
                banner += f" | Cert:[{cert_info.get('subject_cn', '?')}] {self_signed_tag}"
            
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="ldaps",
                latency_ms=latency, status="open", banner=banner,
                cert_info=cert_info
            )
            
        except Exception as e:
            return Observation(
                ip=ip_address, port=self.port, protocol="tcp", service="ldaps",
                latency_ms=(time.time() - start_time) * 1000, status=_error_status(e), error_reason=str(e)
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
    if port == 3389:
        return RDPProbe(port)
    if port in [25, 587]:
        return SMTPProbe(port)
    if port == 636:
        return LDAPSProbe(port)
        
    return TCPProbe(port)
