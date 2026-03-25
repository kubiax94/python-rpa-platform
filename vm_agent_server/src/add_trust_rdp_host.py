# add_trusted_rdp_host.py
import winreg
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_trusted_rdp_host(hostname):
    """
    Dodaje host do zaufanych RDP hosts.
    Windows nie będzie pytał o certyfikat.
    """
    try:
        logger.info(f"Adding {hostname} to trusted RDP hosts...")
        
        # Registry path
        reg_path = r"Software\Microsoft\Terminal Server Client\Servers"
        
        # Open/create registry key
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                reg_path,
                0,
                winreg.KEY_WRITE
            )
        except FileNotFoundError:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path)
        
        # Create subkey for this host
        host_key = winreg.CreateKey(key, hostname)
        
        # Set CertHash to empty (trust any cert)
        winreg.SetValueEx(
            host_key,
            "CertHash",
            0,
            winreg.REG_BINARY,
            b''  # Empty = accept any cert
        )
        
        winreg.CloseKey(host_key)
        winreg.CloseKey(key)
        
        logger.info(f"✅ {hostname} added to trusted hosts")
        logger.info("   Windows will no longer ask about certificate")
        
        return True
    
    except Exception as e:
        logger.exception(f"❌ Failed to add trusted host: {e}")
        return False

def disable_rdp_publisher_warning():
    """
    Wyłącz ostrzeżenie o nieznanym wydawcy RDP.
    Windows nie będzie pytał przy otwieraniu plików .rdp
    """
    try:
        logger.info("Disabling RDP publisher warnings...")
        
        # Registry path
        reg_path = r"Software\Microsoft\Terminal Server Client"
        
        # Open/create key
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                reg_path,
                0,
                winreg.KEY_SET_VALUE
            )
        except FileNotFoundError:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path)
        
        # Disable warning about untrusted publishers
        # 0 = Don't warn
        winreg.SetValueEx(
            key,
            "AuthenticationLevelOverride",
            0,
            winreg.REG_DWORD,
            0
        )
        
        winreg.CloseKey(key)
        
        logger.info("✅ RDP publisher warnings DISABLED")
        logger.info("   Windows will no longer ask about .rdp file publishers")
        
        return True
    
    except Exception as e:
        logger.exception(f"❌ Failed: {e}")
        return False


if __name__ == "__main__":
    # ⭐ DODAJ PRAWDZIWY HOSTNAME Z BŁĘDU!
    hosts = [
        "DESKTOP-JJULF7D",  # ← To pokazuje w błędzie!
        "vm001.eastus.cloudapp.azure.com",
        "vm002.eastus.cloudapp.azure.com",
    ]
    
    print("="*60)
    print("🔐 Adding RDP hosts to trusted list")
    print("="*60)
    
    for host in hosts:
        print(f"\n{host}...")
        add_trusted_rdp_host(host)
    
    # ⭐ DODAJ RÓWNIEŻ disable warnings!
    print("\n" + "="*60)
    print("🔧 Disabling RDP publisher warnings...")
    print("="*60)
    disable_rdp_publisher_warning()
    
    print("\n" + "="*60)
    print("✅ Done! RDP will no longer ask about certificates")
    print("="*60)
    print("\n⚠️  Restart explorer.exe or reboot for changes to take effect!")