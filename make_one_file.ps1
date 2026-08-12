# تعریف متغیرها
$targetDir = "D:\IT\PythonProjects\Deutsch-Bot"
$outFile = "$targetDir/all_project_files.txt"

# لیست دایرکتوری‌های مورد نظر برای حذف (regex)
$excludedDirs = "venv|\.git|\.github|\.pytest_cache|__pycache__|audio_cache|backups"
# لیست نام فایل‌های مورد نظر برای حذف (regex)
$excludedFiles = "\.db$|\.ps1$|\.csv$|\.mp3$|\.pyc$|^all_project_files\.txt$|^\.env$"

Get-ChildItem -Path $targetDir -Recurse -File |
    # فیلتر بر اساس پسوندهای ورودی (مشابه -name)
    Where-Object { $_.Extension -match "\.(py|md|txt)$" -or $_.Name -match "^\.env" } |
    # حذف دایرکتوری‌های ناخواسته (مشابه -not -path)
    Where-Object { $_.DirectoryName -notmatch "[\\/]($excludedDirs)[\\/]" } |
    # حذف فایل‌های ناخواسته (مشابه -not -name)
    Where-Object { $_.Name -notmatch $excludedFiles } |
    # مرتب‌سازی بر اساس مسیر کامل (مشابه sort)
    Sort-Object FullName |
    # حلقه برای چاپ هدر و محتوا (مشابه while read)
    ForEach-Object {
        $f = $_.FullName
        ""                          # خط خالی
        "========== FILE: $f =========="
        ""                          # خط خالی
        Get-Content -Path $f        # معادل cat
    } |
    Out-File -FilePath $outFile -Encoding UTF8