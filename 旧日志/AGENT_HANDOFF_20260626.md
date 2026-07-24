# Agent Handoff 2026-06-26

## Project snapshot

- Workspace: `D:\Chef_Vision`
- Main file: `core/TrackFood.py`
- Current focus: IR wok-region tracking and RGB inverse-semantics stability
- User prefers concise replies and practical execution

## Stable rollback points

- Latest stable checkpoint:
  - commit: `dbef149`
  - tag: `stable-ir-wok-20260626`
- Older stable checkpoint:
  - commit: `8128b07`
  - tag: `stable-rgb-inverse-20260625`

If later experiments go wrong, roll back to `stable-ir-wok-20260626`.

## What was changed recently

1. RGB inverse semantics now mainly follows the IR-projected wok constraint.
   - Old RGB-side wok-circle tracking attempts were repeatedly unstable.

2. Inverse recovery thresholds were tightened.
   - `inv_ratio > 50%`: treat as abnormal / consider relabel-reset
   - `inv_ratio < 10%`: also treat as abnormal / consider relabel-reset
   - Earlier code had a much looser `>95%` style trigger

3. Inverse-mode recovery was pushed toward IR-guided relabeling.
   - Goal: when inverse SAM2 loses target, do not trust stale RGB state
   - Rebuild points from current IR information inside wok constraint, then continue inverse SAM2

4. The purple inverse temperature curve was changed to solid-line display.

5. Dataset trimming support was added:
   - `tools/trim_dataset_segments.py`

## Processed datasets already created

### `test_data/test1_1`

- removed `33s-38s`
- removed `40s-46s`
- removed `89s-96s`

### `test_data/test4_1`

- removed `29s-37s`
- removed `50s-57s`
- removed `72s-80s`

Each processed dataset folder was normalized to exactly 4 files:

- RGB mp4
- IR mp4
- temperature `.npy`
- `roi_config.json`

## IR wok-region tracking: attempted ideas so far

These have already been tried and were not reliable enough over the whole video:

1. temperature-drop boundary tracking
2. hot-ring / high-temperature ring fitting
3. Hough-based circle logic
4. `fitEllipse`
5. high-temperature blob center updates
6. IR projection plus extra secondary correction

User decision:

- Stop using wok boundary detection, hot-ring detection, Hough, `fitEllipse`, temperature-cliff boundary, and hot-blob-center logic as the **main** IR wok tracking path.

## New requested direction

User wants IR wok tracking changed to frame-registration translation:

1. First frame manually defines an IR-side wok mask strictly inside the wok
2. Later frames do not re-detect the wok boundary
3. Estimate overall translation `(dx, dy)` from previous IR frame to current IR frame
4. Translate previous `wok_mask_ir` by `(dx, dy)` to get current-frame wok region
5. Keep both RGB schemes consuming the IR-projected wok constraint as before

## Current code status for that direction

Partially prepared only. Not finished yet.

Already added to `core/TrackFood.py`:

- `_estimate_ir_frame_translation(...)`
- `_translate_binary_mask(...)`

Not done yet:

- the active chunk-level IR wok update block is still the older logic
- previous-frame IR state was not fully wired into the main update path
- old hot-ring / edge logic has not yet been fully disabled as the main path

So the repository currently contains:

- a stable checkpoint that works reasonably well
- plus partial helper work for the next IR translation-based tracking attempt

## Important files to inspect first

- `HANDOVER.md`
- `SESSION_NOTES.md`
- `core/TrackFood.py`
- `core/food_labels.json`
- `data/wok_region.json`
- `test_val.py`

## User preferences and constraints

- Keep explanations short and direct
- When user says “开始改”, actually modify code
- Do not casually touch `data/homography.npy`
- User often runs long jobs in the VS Code terminal manually
- For new videos, manual labeling is acceptable; unstable auto-tracking is not

## Recommended next implementation step

In `core/TrackFood.py`:

1. add previous-IR-frame state for wok tracking
2. replace the active IR wok update block with:
   - current IR frame extraction
   - translation estimation from previous IR frame
   - `wok_mask_ir` translation
   - RGB projected wok constraint refresh
3. stop using hot-ring / edge / boundary logic as the main wok update path
4. run:
   - `python -m py_compile core\\TrackFood.py`

## Useful commands

```powershell
python core\TrackFood.py
python -m py_compile core\TrackFood.py
git status --short
git show --stat dbef149
```

## Suggested prompt for the next AI chat

```text
请先阅读 D:\Chef_Vision\AGENT_HANDOFF_20260626.md、HANDOVER.md、SESSION_NOTES.md。
当前稳定回滚点是 dbef149 / stable-ir-wok-20260626。
现在要继续修改 core/TrackFood.py，把 IR 锅内圈选监测区域的主逻辑改成“基于前后 IR 帧图像配准的平移更新 wok_mask_ir”，不要再用锅边界、红环、Hough、fitEllipse、温度骤降边界、高温块中心作为主逻辑。
注意：_estimate_ir_frame_translation(...) 和 _translate_binary_mask(...) 已经加进 TrackFood.py，但主流程还没切过去。
两个 RGB 方案仍然继续使用 IR 映射过去的锅区约束信息。
先检查当前 TrackFood.py 的相关代码位置和未完成状态，再开始改。
```
