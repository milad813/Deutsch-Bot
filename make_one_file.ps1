$targetDir = "D:\IT\PythonProjects\Deutsch-Bot"
$outFile = "$targetDir/all_project_files.txt"

$excludedDirs = "venv|\.git|\.github|\.pytest_cache|__pycache__|audio_cache|backups"
$excludedFiles = "\.db$|\.csv$|\.mp3$|\.pyc$|^all_project_files\.txt$|^\.env$"

Get-ChildItem -Path $targetDir -Recurse -File |
    Where-Object { $_.Extension -match "\.(py|md|txt)$" -or $_.Name -match "^\.env" } |
    Where-Object { $_.DirectoryName -notmatch "[\\/]($excludedDirs)[\\/]" } |
    Where-Object { $_.Name -notmatch $excludedFiles } |
    Sort-Object FullName |
    ForEach-Object {
        $f = $_.FullName
        "" 
        "========== FILE: $f =========="
        "" 
        # ✅ تغییر مهم: اضافه کردن -Encoding UTF8 برای خواندن صحیح فارسی
        Get-Content -Path $f -Encoding UTF8
    } |
    # ✅ تغییر مهم: ذخیره خروجی نهایی با UTF8 (بدون BOM برای سازگاری بهتر)
    Out-File -FilePath $outFile -Encoding UTF8