param(
    [string]$OutputPath = (Join-Path $PSScriptRoot "..\samples\meeting-ru-kk.wav")
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$ffprobe = (Get-Command ffprobe -ErrorAction Stop).Source
$output = [System.IO.Path]::GetFullPath($OutputPath)
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("hackalem-tts-" + [guid]::NewGuid())
[System.IO.Directory]::CreateDirectory($work) | Out-Null
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($output)) | Out-Null

$utterances = @(
    @{ Speaker = "A"; Rate = 1; Text = "Добрый день. Меня зовут Айгерим Серикова. Начинаем короткий статус по проекту." },
    @{ Speaker = "B"; Rate = 2; Text = "Сәлеметсіздер ме. Менің атым Данияр Ахметов. Давайте зафиксируем жауаптылар мен мерзімдер." },
    @{ Speaker = "A"; Rate = 1; Text = "Данияр, подготовьте список клиентов и отправьте его команде завтра до десяти утра." },
    @{ Speaker = "B"; Rate = 2; Text = "Жақсы, клиенттер тізімін ертең сағат онға дейін дайындап жіберемін." },
    @{ Speaker = "B"; Rate = 2; Text = "Айгерим, подготовьте финальную презентацию к пятнице и добавьте результаты тестирования." },
    @{ Speaker = "A"; Rate = 1; Text = "Принято. Презентацияны жұмаға дейін дайындаймын. Тест нәтижелерін до конца недели тексеру керек." },
    @{ Speaker = "B"; Rate = 2; Text = "Итог: Данияр отвечает за список клиентов до завтра, Айгерим за презентацию к пятнице." },
    @{ Speaker = "A"; Rate = 1; Text = "Все поручения зафиксированы. На этом совещание завершено. Рақмет." }
)

try {
    $synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
    $synth.SelectVoice("Microsoft Irina Desktop")
    $parts = [System.Collections.Generic.List[string]]::new()

    for ($index = 0; $index -lt $utterances.Count; $index++) {
        $raw = Join-Path $work ("raw-{0:d2}.wav" -f $index)
        $processed = Join-Path $work ("part-{0:d2}.wav" -f $index)
        $synth.Rate = $utterances[$index].Rate
        $synth.SetOutputToWaveFile($raw)
        $synth.Speak($utterances[$index].Text)
        $synth.SetOutputToNull()

        $filter = if ($utterances[$index].Speaker -eq "A") {
            "aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono"
        } else {
            "asetrate=25000,aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono"
        }
        & $ffmpeg -hide_banner -loglevel error -y -i $raw -af $filter $processed
        if ($LASTEXITCODE -ne 0) { throw "ffmpeg failed while processing utterance $index" }
        $parts.Add($processed)

        if ($index -lt $utterances.Count - 1) {
            $silence = Join-Path $work ("silence-{0:d2}.wav" -f $index)
            & $ffmpeg -hide_banner -loglevel error -y -f lavfi -i "anullsrc=r=16000:cl=mono" -t 0.85 $silence
            if ($LASTEXITCODE -ne 0) { throw "ffmpeg failed while creating silence" }
            $parts.Add($silence)
        }
    }

    $concatFile = Join-Path $work "concat.txt"
    $parts | ForEach-Object { "file '$($_.Replace("'", "''"))'" } |
        Set-Content -Encoding ASCII $concatFile
    & $ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i $concatFile -c:a pcm_s16le $output
    if ($LASTEXITCODE -ne 0) { throw "ffmpeg failed while concatenating the sample" }

    $duration = & $ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 $output
    Write-Output "Generated $output"
    Write-Output ("Duration: {0:n1} seconds" -f [double]$duration)
}
finally {
    if ($null -ne $synth) { $synth.Dispose() }
    if ($work.StartsWith([System.IO.Path]::GetTempPath(), [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}
