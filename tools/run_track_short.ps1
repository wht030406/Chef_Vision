$video = "test_data\test1_1\rgb_20260529_112414.mp4"
$temp = "test_data\test1_1\temp_20260529_112414.npy"
$labels = "core\food_labels.json"
$maxFrames = 300
$irWokStrategy = "legacy"

Write-Host ""
Write-Host "Short TrackFood run"
Write-Host "  video:    $video"
Write-Host "  temp:     $temp"
Write-Host "  labels:   $labels"
Write-Host "  strategy: $irWokStrategy"
Write-Host "  frames:   $maxFrames"
Write-Host ""

python core\TrackFood.py `
  --video $video `
  --temp $temp `
  --labels $labels `
  --ir-wok-strategy $irWokStrategy `
  --max-frames $maxFrames

exit $LASTEXITCODE
