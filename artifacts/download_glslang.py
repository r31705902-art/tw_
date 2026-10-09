import os
import sys
import json
import zipfile
import urllib.request

GITHUB_API_RELEASE = "https://api.github.com/repos/KhronosGroup/glslang/releases/latest"

def download_and_extract():
    print(f"Fetching release metadata from GitHub API: {GITHUB_API_RELEASE}")
    req = urllib.request.Request(
        GITHUB_API_RELEASE,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(f"Release tag: {data.get('tag_name', 'Unknown')}")
        
        assets = data.get("assets", [])
        selected_asset = None
        for asset in assets:
            name = asset.get("name", "")
            print(f"Found asset: {name}")
            if "windows" in name.lower() or "win" in name.lower():
                selected_asset = asset
                break
        
        if not selected_asset and assets:
            selected_asset = assets[0]

        if not selected_asset:
            raise Exception("No assets found in release!")

        download_url = selected_asset.get("browser_download_url")
        filename = selected_asset.get("name")
        print(f"\nDownloading selected asset '{filename}' from:\n{download_url}")

    zip_path = os.path.abspath(filename)
    req_dl = urllib.request.Request(
        download_url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    with urllib.request.urlopen(req_dl, timeout=60) as resp, open(zip_path, "wb") as out_file:
        out_file.write(resp.read())
    
    print(f"Downloaded successfully ({os.path.getsize(zip_path)} bytes). Extracting...")
    
    extract_dir = os.path.abspath("glslang_bin")
    os.makedirs(extract_dir, exist_ok=True)
    
    if zip_path.endswith(".zip"):
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        print(f"Extracted to {extract_dir}")
    else:
        print(f"Downloaded file: {zip_path}")
        
    return extract_dir

def find_executable(dir_path):
    for root, dirs, files in os.walk(dir_path):
        for f in files:
            if f.lower() in ("glslangvalidator.exe", "glslang.exe"):
                return os.path.join(root, f)
    return None

if __name__ == "__main__":
    try:
        extract_dir = download_and_extract()
        exe_path = find_executable(extract_dir)
        if exe_path:
            print(f"\n[SUCCESS]: Found executable at: {exe_path}")
        else:
            print(f"\n[WARNING]: Executable not found in {extract_dir}")
    except Exception as e:
        print(f"[ERROR]: {e}")
