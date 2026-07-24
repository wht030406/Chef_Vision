$video = "test_data\test1_1\rgb_20260529_112414.mp4"
$temp = "test_data\test1_1\temp_20260529_112414.npy"
$labels = "core\food_labels.json"

Write-Host ""
Write-Host "Step 1/4: IR wok inner region. Draw one strict in-wok ellipse, then save."
python core\ir_mask_viz.py --setup --npy $temp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Step 2/4: RGB forward food reference. Left click food, right click background/wok."
python core\LabelFirstFrame.py --video $video --labels $labels --food --frame 60 --label initial_food
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Step 3/4: RGB inverse/bottom reference. Left click wok bottom/body, right click food/non-bottom."
python core\LabelFirstFrame.py --video $video --labels $labels --bottom --frame 60 --label initial_bottom
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Step 4/4: Run TrackFood"
python core\TrackFood.py --labels $labels --video $video --temp $temp
exit $LASTEXITCODE
