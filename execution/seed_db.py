import asyncio
import sys
import datetime
sys.path.append(".") 
from execution import db_manager

async def seed():
    await db_manager.init_db()
    
    data = [
        {"ip": "192.168.1.10", "port": 80, "banner": "Apache/2.4.41 (Ubuntu)", "service_type": "http", "vendor": "Apache", "product": "HTTP Server"},
        {"ip": "192.168.1.11", "port": 8080, "banner": "Hikvision RTSP", "service_type": "camera", "vendor": "Hikvision", "product": "IP Camera"},
        {"ip": "10.0.0.5", "port": 22, "banner": "SSH-2.0-OpenSSH_8.2p1", "service_type": "ssh", "vendor": "OpenBSD", "product": "OpenSSH"},
        {"ip": "8.8.8.8", "port": 53, "banner": "", "service_type": "dns", "vendor": "Google", "product": "DNS"},
    ]
    
    for d in data:
        d["timestamp"] = datetime.datetime.now().isoformat()
        await db_manager.save_service(d)
        
    print("Seeded.")

if __name__ == "__main__":
    asyncio.run(seed())
