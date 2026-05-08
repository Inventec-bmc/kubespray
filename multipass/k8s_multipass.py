#!/usr/bin/env python3
import subprocess
import os
import sys
import yaml
import time

CONFIG_FILE = 'config.yml'

def print_header(text):
    print(f"\n{'='*55}\n🚀 {text}\n{'='*55}")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ 錯誤: 找不到設定檔 {CONFIG_FILE}，請確認檔案存在。")
        sys.exit(1)
    with open(CONFIG_FILE, 'r') as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as exc:
            print(f"❌ YAML 解析錯誤: {exc}")
            sys.exit(1)

def run_cmd(cmd, capture=False, show_output=True):
    if show_output:
        print(f"⚙️  執行指令: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, check=True, text=True, capture_output=capture)
        return result.stdout.strip() if capture else None
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 錯誤: 指令執行失敗!\n{e.stderr if capture else ''}")
        return False

def check_vm_exists(vm_name):
    output = run_cmd("multipass list --format yaml", capture=True, show_output=False)
    if output:
        data = yaml.safe_load(output)
        return vm_name in data
    return False

def show_status():
    print_header("目前虛擬機狀態 (Status)")
    print("列出所有 Multipass 虛擬機：\n")
    run_cmd("multipass list")

def prepare_local_image(image_path):
    """
    處理本地映像檔，將其複製到 Snap 白名單目錄以避免 AppArmor 權限阻擋
    """
    # 移除可能帶有的 file:// 前綴
    raw_path = image_path.replace("file://", "")
    
    # 如果不是 .img 檔案，且不存在於本地，代表是一般的雲端代號 (如 noble, 24.04)
    if not raw_path.endswith('.img') and not os.path.exists(raw_path):
        return image_path
        
    if not os.path.exists(raw_path):
        print(f"❌ 錯誤: 找不到本地映像檔 -> {raw_path}")
        return None

    filename = os.path.basename(raw_path)
    target_dir = "/var/snap/multipass/common"
    target_path = os.path.join(target_dir, filename)

    # 如果檔案已經在目標目錄，直接回傳正確格式
    if raw_path == target_path:
        return f"file://{target_path}"

    print(f"\n[準備階段] 偵測到本地映像檔，正在搬移至 Snap 合法目錄以避開權限阻擋...")
    print(f"來源: {raw_path}")
    print(f"目標: {target_path}")
    
    # 執行複製與修改權限
    if run_cmd(f"sudo cp {raw_path} {target_path}") is False: return None
    if run_cmd(f"sudo chmod 777 {target_path}") is False: return None
    
    print("✅ 映像檔就緒！")
    return f"file://{target_path}"

def setup_vm(config):
    print_header("開始建立與初始化虛擬機 (Setup)")
    vm_name = config['vm_name']
    
    if check_vm_exists(vm_name):
        print(f"⚠️ 虛擬機 '{vm_name}' 已經存在！請先檢查狀態 (Status) 或直接啟動 (Open)。")
        return

    # 0. 處理本地映像檔權限問題
    launch_image = prepare_local_image(config['image'])
    if not launch_image:
        return

    # --- 修正：動態從 config 讀取外部網路設定檔的路徑 ---
    cloud_init_file = config.get('cloud_init_file')
    if not cloud_init_file:
        print("❌ 錯誤: config.yml 中未設定 'cloud_init_file' 欄位！")
        return

    print("\n[1/4] 檢查外部網路設定檔...")
    if not os.path.exists(cloud_init_file):
        print(f"❌ 錯誤: 找不到網路設定檔 '{cloud_init_file}'！")
        print("💡 請確保您已在該路徑建立檔案，以設定固定 IP。")
        return
    print(f"✅ 確認使用外部網路設定檔: {cloud_init_file}")

    # 1. 啟動虛擬機 (移除 --cloud-init 參數，純粹掛載橋接網卡)
    print(f"\n[2/4] 正在建立虛擬機 {vm_name} (配置 1024G 磁碟需數分鐘)...")
    launch_cmd = (
        f"multipass launch {launch_image} --name {vm_name} "
        f"--cpus {config['cpus']} --memory {config['memory']} --disk {config['disk']} "
        f"--network name={config['bridge_interface']},mode=manual"
    )
    if run_cmd(launch_cmd) is False: return

    # 2. 注入 SSH 公鑰
    print("\n[3/4] 正在注入 SSH 公鑰...")
    pub_key_path = os.path.expanduser(config['ssh_pub_key_path'])
    priv_key_path = pub_key_path.replace('.pub', '') # 自動推導私鑰路徑

    # 確保 .ssh 目錄存在
    os.makedirs(os.path.dirname(pub_key_path), exist_ok=True)

    if not os.path.exists(pub_key_path):
        print(f"⚠️ 找不到公鑰，正在自動產生專用金鑰 ({priv_key_path})...")
        # 使用動態路徑產生金鑰，並加上 -q (安靜模式) 避免卡在互動介面
        run_cmd(f'ssh-keygen -t rsa -b 4096 -q -N "" -f "{priv_key_path}"')
        
    with open(pub_key_path, 'r') as f:
        pub_key = f.read().strip()
    
    time.sleep(5) # 稍微等待系統網路就緒
    run_cmd(f"multipass exec {vm_name} -- bash -c \"echo '{pub_key}' >> ~/.ssh/authorized_keys\"")

    # 3. 強制注入網路設定 (取代原本無效的 cloud-init)
    print(f"\n[4/4] 正在強制寫入靜態 IP 設定並套用 ({cloud_init_file})...")
    run_cmd(f"multipass transfer {cloud_init_file} {vm_name}:/home/ubuntu/99-bridge-ip.yaml")
    run_cmd(f"multipass exec {vm_name} -- sudo mv /home/ubuntu/99-bridge-ip.yaml /etc/netplan/")
    run_cmd(f"multipass exec {vm_name} -- sudo chmod 600 /etc/netplan/99-bridge-ip.yaml")
    run_cmd(f"multipass exec {vm_name} -- sudo netplan apply")

    print(f"\n✅ 虛擬機 {vm_name} 建置完成！")
    print(f"👉 靜態 IP 已成功綁定。")
    print("\n💡 下一步：請記得手動將 IP 更新到您的 Kubespray hosts.ini 檔案中。")

def open_vm(config):
    print_header("啟動虛擬機 (Open)")
    run_cmd(f"multipass start {config['vm_name']}")
    print(f"✅ {config['vm_name']} 已啟動。")

def close_vm(config):
    print_header("關閉虛擬機 (Close)")
    run_cmd(f"multipass stop {config['vm_name']}")
    print(f"✅ {config['vm_name']} 已安全關閉。")

def delete_vm(config):
    print_header("刪除虛擬機 (Delete)")
    vm_name = config['vm_name']
    confirm = input(f"⚠️ 警告：確定要永久刪除 {vm_name} (含 {config['disk']} 資料) 嗎？(Y/N): ")
    if confirm == 'Y':
        run_cmd(f"multipass delete {vm_name}")
        run_cmd("multipass purge")
        print("🗑️ 虛擬機已徹底刪除。")
    else:
        print("🛑 已取消刪除動作。")

def display_menu(config):
    while True:
        print("\n" + "="*55)
        print("   Kubernetes 底層虛擬機管理工具 (Multipass)")
        print(f"   目標節點: {config['vm_name']}")
        print("="*55)
        print("  [1] Setup    - 建立虛擬機並初始化 (含金鑰與靜態IP)")
        print("  [2] Open     - 啟動虛擬機")
        print("  [3] Close    - 關閉虛擬機")
        print("  [4] Delete   - 刪除並清除虛擬機 (危險操作)")
        print("  [5] Status   - 顯示所有虛擬機存活狀態")
        print("  [0] Exit     - 離開程式")
        print("="*55)
        
        choice = input("👉 請選擇操作 (0-5): ").strip()
        
        if choice == '1': setup_vm(config)
        elif choice == '2': open_vm(config)
        elif choice == '3': close_vm(config)
        elif choice == '4': delete_vm(config)
        elif choice == '5': show_status()
        elif choice == '0':
            print("👋 離開程式。")
            break
        else: print("❌ 無效選擇。")
        time.sleep(1)

if __name__ == "__main__":
    display_menu(load_config())