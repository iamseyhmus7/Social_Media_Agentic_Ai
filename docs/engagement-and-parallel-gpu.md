# Engagement and parallel GPU policy

New run settings snapshot `engagement_policy=1` and `kaggle_motion_profile=dual_required`.
Old run snapshots retain their previous policy. Existing Kaggle manifests, remote job
IDs, completed speech and references are never rewritten during deployment.

The script agent receives a topic-specific opening/closing instruction automatically.
The first spoken narration must start with its hook (up to eight words).
The opening is validated on actual narration and preserved during timing repair.
Automatic spoken like/follow requests and the social overlay were removed at the
owner's request. Legacy manifest flags remain readable but have no rendering effect.
Existing speech and generated clips are preserved.

`dual_fp32_sequential_v1` distributes independent shots between GPU 0 and GPU 1,
using the existing sequential CPU offload method on each device. Both processes
start before the parent waits for either. A required-parallel job fails explicitly
if fewer than two GPUs are provided; it does not silently fall back to one GPU.
Already committed clips survive worker errors. Existing single-GPU jobs keep their
original identity and finish without being resubmitted. Text preparation and the
last remaining shot need not occupy both GPUs simultaneously.

The former optional group-offload optimization still requires its measured
certificate; no successful benchmark certificate is fabricated for the new policy.
Real speedup and memory behavior must be measured on the target Kaggle hardware.
The existing private comparison tool now supports `--profile dual_fp32_sequential_v1`
and an explicit `--source-run`. It refuses to submit while another owned GPU job
occupies the account slot. Review extracted frames before using `--visual-checked`.

Focused tests cover narration constraints, hook preservation during retiming,
legacy compatibility, two-device process launch order and exact shot assignment.
The discarded social-overlay preview files were removed.
