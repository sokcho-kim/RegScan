# RegScan Proposal 환경 설정
# PowerShell 스크립트

Write-Host "=== RegScan Proposal 환경 설정 ===" -ForegroundColor Cyan

# 1. UV 환경 생성
Write-Host "`n[1/3] UV 환경 생성..." -ForegroundColor Yellow
uv venv
uv pip install -e .

# 2. Quarto 설치 확인
Write-Host "`n[2/3] Quarto 설치 확인..." -ForegroundColor Yellow
$quartoInstalled = Get-Command quarto -ErrorAction SilentlyContinue

if ($quartoInstalled) {
    Write-Host "Quarto 설치됨: $(quarto --version)" -ForegroundColor Green
} else {
    Write-Host "Quarto 미설치. 설치 중..." -ForegroundColor Yellow

    # winget으로 설치 시도
    $wingetInstalled = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetInstalled) {
        winget install Posit.Quarto
    } else {
        # choco로 설치 시도
        $chocoInstalled = Get-Command choco -ErrorAction SilentlyContinue
        if ($chocoInstalled) {
            choco install quarto -y
        } else {
            Write-Host "수동 설치 필요: https://quarto.org/docs/get-started/" -ForegroundColor Red
            Write-Host "또는: winget install Posit.Quarto" -ForegroundColor Yellow
        }
    }
}

# 3. 렌더링 테스트
Write-Host "`n[3/3] 프레젠테이션 렌더링..." -ForegroundColor Yellow
if (Get-Command quarto -ErrorAction SilentlyContinue) {
    quarto render regscan_server_proposal.qmd
    Write-Host "`n완료! regscan_server_proposal.html 생성됨" -ForegroundColor Green
    Write-Host "미리보기: quarto preview regscan_server_proposal.qmd" -ForegroundColor Cyan
}
