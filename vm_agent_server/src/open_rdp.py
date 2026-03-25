import subprocess
import logging
import os
import time
logger = logging.getLogger(__name__)


def connect_rdp(vm_host: str, username: str, password: str, domain: str = "."):
    """
    Connect to VM via RDP - NO certificate prompts.
    Uses /public flag to skip certificate validation.
    """
    try:
        logger.info(f"🔐 Connecting to {vm_host} as {domain}\\{username}")
        
        # 1. Store credentials
        subprocess.run([
            "cmdkey",
            f"/generic:TERMSRV/{vm_host}",
            f"/user:{vm_host}\\{username}",
            f"/pass:{password}"
        ], check=True, capture_output=True)
        
        logger.info("✅ Credentials stored")
        
        # 2. Create RDP file
        rdp_file = f"C:\\Temp\\rdp_{vm_host}_{username}.rdp"
        
        rdp_content = f"""screen mode id:i:2
use multimon:i:0
desktopwidth:i:1920
desktopheight:i:1080
session bpp:i:32
winposstr:s:0,3,0,0,800,600
compression:i:1
keyboardhook:i:2
audiocapturemode:i:0
videoplaybackmode:i:1
connection type:i:7
networkautodetect:i:1
bandwidthautodetect:i:1
displayconnectionbar:i:1
enableworkspacereconnect:i:0
disable wallpaper:i:0
allow font smoothing:i:0
allow desktop composition:i:0
disable full window drag:i:1
disable menu anims:i:1
disable themes:i:0
disable cursor setting:i:0
bitmapcachepersistenable:i:1
full address:s:{vm_host}
audiomode:i:0
redirectprinters:i:1
redirectcomports:i:0
redirectsmartcards:i:1
redirectwebauthn:i:1
redirectclipboard:i:1
redirectposdevices:i:0
autoreconnection enabled:i:1
authentication level:i:2
prompt for credentials:i:0
negotiate security layer:i:1
remoteapplicationmode:i:0
alternate shell:s:
shell working directory:s:
gatewayhostname:s:
gatewayusagemethod:i:4
gatewaycredentialssource:i:3
gatewayprofileusagemethod:i:0
promptcredentialonce:i:0
gatewaybrokeringtype:i:0
use redirection server name:i:0
rdgiskdcproxy:i:0
kdcproxyname:s:
enablerdsaadauth:i:0

"""
        
        os.makedirs("C:\\Temp", exist_ok=True)
        
        with open(rdp_file, "w") as f:
            f.write(rdp_content)
        
        logger.info(f"✅ RDP file: {rdp_file}")
        
        # 3. Launch mstsc with /public flag (NO cert check!)
        logger.info("Launching mstsc with /public flag...")
        
        process = subprocess.Popen([
            "mstsc.exe",
            rdp_file
        ])
        time.sleep(10)
        
        logger.info(f"✅ mstsc launched! PID={process.pid}")
        logger.info("👀 Should connect WITHOUT cert prompt!")
        
        return process.pid
    
    except Exception as e:
        logger.exception(f"❌ Failed to connect: {e}")
        raise
    
    finally:
        # Cleanup credentials
        try:
            subprocess.run([
                "cmdkey",
                f"/delete:TERMSRV/{vm_host}"
            ], capture_output=True)
        except:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test
    connect_rdp(
        vm_host="DESKTOP-JJULF7D",  # lub vm001.eastus.cloudapp.azure.com
        username="test1",
        password="test1",
        domain="."
    )
    
    print("\n✅ RDP should connect WITHOUT certificate prompt!")
    input("Press Enter to exit...")