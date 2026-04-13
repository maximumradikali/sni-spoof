# SNI Forwarder (Optimized)

Original source: [`patterniha/SNI-Spoofing`](https://github.com/patterniha/SNI-Spoofing) by [`@patterniha`](https://github.com/patterniha).  
This version is edited and optimized by **Maximum Radikali**.

Maintainer GitHub: <https://github.com/maximumradikali>
Recommended repository name: `sni-spoof`

### Donate
- `BNB (BEP20)`: `0x4680c9A4b69aE6c5F7Ab3aEb9e8A38A9cf72a03A`
- `Ethereum (ERC20)`: `0x4680c9A4b69aE6c5F7Ab3aEb9e8A38A9cf72a03A`
- `TRON (TRX)`: `TUfmAKW8eeHvxhhrfdYb2MRPLNtX28zkVv`
- `USDT (TRC20)`: `TUfmAKW8eeHvxhhrfdYb2MRPLNtX28zkVv`

### Source And Improvements / منبع و بهینه‌سازی‌ها
- Upstream source repository: `https://github.com/patterniha/SNI-Spoofing`
- Original author profile: `https://github.com/patterniha`
- Main comparison target in this fork is the upstream `patterniha/SNI-Spoofing` source tree.
- منبع اصلی این پروژه ریپازیتوری `patterniha/SNI-Spoofing` است.
- این نسخه با حفظ ایده اصلی، توسط **Maximum Radikali** برای اجرا، پایداری، لاگ‌گیری و انتشار بهتر بهینه شده است.

### Differences From The Original Source / تفاوت با سورس اصلی
- Upstream uses a single `CONNECT_IP`; this fork uses `CONNECT_IPS` with retry and failover support.
- در سورس اصلی فقط یک `CONNECT_IP` وجود دارد؛ در این فورک از `CONNECT_IPS` با retry و failover استفاده می‌شود.
- Upstream is effectively Windows-focused with WinDivert assumptions; this fork adds direct-mode fallback for Linux, Debian, and Ubuntu.
- سورس اصلی عملا ویندوز-محور است و WinDivert را فرض می‌گیرد؛ این فورک حالت fallback مستقیم برای Linux/Debian/Ubuntu دارد.
- Upstream has minimal runtime visibility; this fork adds structured console/file logging and rotating logs.
- در سورس اصلی لاگ‌گیری محدود است؛ این فورک لاگ کنسول، فایل و rotation لاگ را اضافه می‌کند.
- Upstream can terminate the whole process from some connection-level failure paths; this fork handles those failures more safely and keeps the service alive.
- در سورس اصلی بعضی خطاهای سطح کانکشن می‌توانند کل پروسه را متوقف کنند؛ این فورک این خطاها را امن‌تر مدیریت می‌کند تا سرویس بالا بماند.
- Upstream has fixed runtime behavior; this fork adds configurable retries, backlog, socket buffers, connection limits, and WinDivert queue tuning.
- این فورک تنظیمات بیشتری برای کارایی و پایداری دارد: retries، backlog، socket buffer، محدودیت کانکشن و تنظیم صف WinDivert.
- Upstream has no full release pipeline; this fork adds Windows/Linux/Debian packaging scripts and GitHub Actions release automation.
- سورس اصلی مسیر کامل ریلیز ندارد؛ این فورک اسکریپت ساخت و workflow ریلیز برای Windows/Linux/Debian اضافه می‌کند.

---

## English

### Overview
- Local TCP forwarder with configurable upstream IP failover (`CONNECT_IPS`).
- Windows DPI bypass mode via WinDivert (`BYPASS_METHOD: "wrong_seq"`).
- Cross-platform direct mode (`BYPASS_METHOD: "none"`).
- Structured logging (console + rotating file logs).

### Repository
Default commands below assume your repo is:

`https://github.com/maximumradikali/sni-spoof`

If your repo name is different, replace `sni-spoof` in commands.

### Quick Install From Source

#### Linux / Debian / Ubuntu
```bash
git clone https://github.com/maximumradikali/sni-spoof.git
cd sni-spoof
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python main.py
```

#### Windows (PowerShell)
```powershell
git clone https://github.com/maximumradikali/sni-spoof.git
cd sni-spoof
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python main.py
```

### Direct Install From GitHub Release

#### Linux binary (`tar.gz`)
```bash
REPO="maximumradikali/sni-spoof"
TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | grep -Po '"tag_name": "\K.*?(?=")')"
curl -fL -o sni-forwarder-linux-amd64.tar.gz "https://github.com/$REPO/releases/download/$TAG/sni-forwarder-linux-amd64.tar.gz"
mkdir -p sni-forwarder
tar -xzf sni-forwarder-linux-amd64.tar.gz -C sni-forwarder
cd sni-forwarder
chmod +x sni-forwarder
./sni-forwarder
```

#### Debian / Ubuntu (`.deb`)
```bash
REPO="maximumradikali/sni-spoof"
TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | grep -Po '"tag_name": "\K.*?(?=")')"
VER="${TAG#v}"
curl -fL -o "sni-forwarder_${VER}_amd64.deb" "https://github.com/$REPO/releases/download/$TAG/sni-forwarder_${VER}_amd64.deb"
sudo apt install -y "./sni-forwarder_${VER}_amd64.deb"
sudo systemctl status sni-forwarder --no-pager
```

#### Windows release (`zip`)
```powershell
$repo = "maximumradikali/sni-spoof"
$tag = (Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest").tag_name
Invoke-WebRequest -Uri "https://github.com/$repo/releases/download/$tag/sni-forwarder-windows-amd64.zip" -OutFile "sni-forwarder-windows-amd64.zip"
Expand-Archive -Path "sni-forwarder-windows-amd64.zip" -DestinationPath ".\sni-forwarder" -Force
cd .\sni-forwarder
.\sni-forwarder.exe
```

### Configuration (`config.json`)

#### Core
- `LISTEN_HOST`
- `LISTEN_PORT`
- `CONNECT_IPS` (list of upstream IPv4 addresses; at least one required)
- `CONNECT_PORT`
- `FAKE_SNI`

#### Mode
- `BYPASS_METHOD`: `wrong_seq` or `none`
- `ALLOW_DIRECT_FALLBACK`
- `AUTO_ELEVATE_ADMIN`

#### Performance
- `CONNECT_TIMEOUT_SEC`
- `FAKE_ACK_TIMEOUT_SEC`
- `CONNECT_RETRIES`
- `RETRY_DELAY_SEC`
- `LISTEN_BACKLOG`
- `MAX_ACTIVE_CONNECTIONS`
- `CONNECTION_SLOT_TIMEOUT_SEC`
- `RELAY_BUFFER_SIZE`
- `SOCKET_BUFFER_BYTES`

#### WinDivert
- `FAKE_SEND_DELAY_MS`
- `FAKE_SEND_WORKERS`
- `WINDIVERT_QUEUE_LEN`
- `WINDIVERT_QUEUE_TIME_MS`
- `WINDIVERT_QUEUE_SIZE`
- `DEBUG_UNEXPECTED_PACKETS`

#### Logging
- `LOG_LEVEL`
- `LOG_TO_FILE`
- `LOG_FILE`
- `LOG_MAX_BYTES`
- `LOG_BACKUP_COUNT`

### Build

#### Windows
```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

#### Linux
```bash
bash scripts/build_linux.sh
```

#### Debian/Ubuntu package
```bash
bash scripts/build_deb.sh 1.0.0
```

### Release Automation (GitHub Actions)
- Create and push a tag (example: `v1.0.0`).
- Workflow: `.github/workflows/release.yml`
- Artifacts:
  - `sni-forwarder-windows-amd64.zip`
  - `sni-forwarder-linux-amd64.tar.gz`
  - `sni-forwarder-linux-arm64.tar.gz`
  - `sni-forwarder_<version>_amd64.deb`
  - `sni-forwarder_<version>_arm64.deb`

---

## فارسی

منبع اصلی: [`patterniha/SNI-Spoofing`](https://github.com/patterniha/SNI-Spoofing) از [`@patterniha`](https://github.com/patterniha)  
این نسخه از سورس اصلی پروژه گرفته شده و توسط **Maximum Radikali** ادیت و بهینه‌سازی شده است.  
گیت‌هاب: <https://github.com/maximumradikali>
نام پیشنهادی ریپو: `sni-spoof`

### معرفی
- فورواردر TCP با امکان failover روی چند IP از طریق `CONNECT_IPS`.
- حالت بایپس DPI روی ویندوز با WinDivert (`BYPASS_METHOD: "wrong_seq"`).
- حالت مستقیم چندسکویی (`BYPASS_METHOD: "none"`).
- لاگ کامل (کنسول + فایل چرخشی).

### ریپازیتوری
دستورهای زیر با فرض این URL نوشته شده‌اند:

`https://github.com/maximumradikali/sni-spoof`

اگر اسم ریپو را عوض کردی، `sni-spoof` را در دستورات جایگزین کن.

### نصب سریع از سورس

#### لینوکس / دبیان / اوبونتو
```bash
git clone https://github.com/maximumradikali/sni-spoof.git
cd sni-spoof
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python main.py
```

#### ویندوز (PowerShell)
```powershell
git clone https://github.com/maximumradikali/sni-spoof.git
cd sni-spoof
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python main.py
```

### نصب مستقیم از Release گیت‌هاب

#### لینوکس (`tar.gz`)
```bash
REPO="maximumradikali/sni-spoof"
TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | grep -Po '"tag_name": "\K.*?(?=")')"
curl -fL -o sni-forwarder-linux-amd64.tar.gz "https://github.com/$REPO/releases/download/$TAG/sni-forwarder-linux-amd64.tar.gz"
mkdir -p sni-forwarder
tar -xzf sni-forwarder-linux-amd64.tar.gz -C sni-forwarder
cd sni-forwarder
chmod +x sni-forwarder
./sni-forwarder
```

#### دبیان / اوبونتو (`.deb`)
```bash
REPO="maximumradikali/sni-spoof"
TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | grep -Po '"tag_name": "\K.*?(?=")')"
VER="${TAG#v}"
curl -fL -o "sni-forwarder_${VER}_amd64.deb" "https://github.com/$REPO/releases/download/$TAG/sni-forwarder_${VER}_amd64.deb"
sudo apt install -y "./sni-forwarder_${VER}_amd64.deb"
sudo systemctl status sni-forwarder --no-pager
```

#### ویندوز (`zip`)
```powershell
$repo = "maximumradikali/sni-spoof"
$tag = (Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest").tag_name
Invoke-WebRequest -Uri "https://github.com/$repo/releases/download/$tag/sni-forwarder-windows-amd64.zip" -OutFile "sni-forwarder-windows-amd64.zip"
Expand-Archive -Path "sni-forwarder-windows-amd64.zip" -DestinationPath ".\sni-forwarder" -Force
cd .\sni-forwarder
.\sni-forwarder.exe
```

### تنظیمات `config.json`
- هسته اصلی: `LISTEN_HOST`, `LISTEN_PORT`, `CONNECT_IPS`, `CONNECT_PORT`, `FAKE_SNI`
- حالت اجرا: `BYPASS_METHOD`, `ALLOW_DIRECT_FALLBACK`, `AUTO_ELEVATE_ADMIN`
- کارایی: `CONNECT_TIMEOUT_SEC`, `FAKE_ACK_TIMEOUT_SEC`, `CONNECT_RETRIES`, `RETRY_DELAY_SEC`, `LISTEN_BACKLOG`, `MAX_ACTIVE_CONNECTIONS`, `CONNECTION_SLOT_TIMEOUT_SEC`, `RELAY_BUFFER_SIZE`, `SOCKET_BUFFER_BYTES`
- WinDivert: `FAKE_SEND_DELAY_MS`, `FAKE_SEND_WORKERS`, `WINDIVERT_QUEUE_LEN`, `WINDIVERT_QUEUE_TIME_MS`, `WINDIVERT_QUEUE_SIZE`, `DEBUG_UNEXPECTED_PACKETS`
- لاگ: `LOG_LEVEL`, `LOG_TO_FILE`, `LOG_FILE`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`

### ساخت بیلد

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

```bash
bash scripts/build_linux.sh
```

```bash
bash scripts/build_deb.sh 1.0.0
```

### ریلیز خودکار
- یک تگ بزن (مثلا `v1.0.0`) و push کن.
- فایل `.github/workflows/release.yml` خودکار بیلدهای زیر را تولید و به Release وصل می‌کند:
  - ویندوز: `sni-forwarder-windows-amd64.zip`
  - لینوکس: `sni-forwarder-linux-amd64.tar.gz`
  - لینوکس: `sni-forwarder-linux-arm64.tar.gz`
  - دبیان/اوبونتو: `sni-forwarder_<version>_amd64.deb`
  - دبیان/اوبونتو: `sni-forwarder_<version>_arm64.deb`
