# What the authors still need to do

I fixed everything in the thesis that could be fixed from the PDF, the LaTeX source and the figures (see `thesis_source/` and the git history). This list covers what I *cannot* do: facts only you know, checks that need the code, and experiments that need the ADNI data and your GPU.

Find every red placeholder in the thesis with:

```
grep -rn authortodo thesis_source/Chapters thesis_source/main.tex
```

**The thesis must not be submitted while any red `[AUTHORS TO FILL: …]` text remains.**

---

## Resolved from the code repository

Source: `github.com/SamuelCormaken/Deep-Learning-for-Alzheimers-MRI`, commit `19e6863`.

| Item | Answer (where it comes from) | Applied to |
|---|---|---|
| A1 validation split | 12% of the training subjects in each fold, held out at random (seed 42 + fold) for early stopping. The test fold is never used for selection. (`src/data/dataset.py`) | thesis Ch. 4, paper §III-A |
| A3 imbalance | Every run uses a class-balanced `WeightedRandomSampler` **and** an inverse-frequency class-weighted loss; 3-class runs add focal loss on top. (`dataset.py`, `train.py`, configs) | thesis Ch. 4, paper §III-D |
| A4 labels | The ADNI research group, constant for every subject. Up to 6 scans per subject within ≤ 2 years (median 1). (`labels.csv`) | thesis Ch. 4, paper §III-B |
| A6 code URL | the repository above | thesis, paper |
| B2 aggregation | Softmax probabilities are averaged, not logits. (`src/utils/metrics.py`) | thesis Ch. 4/5 |
| B3 input sizes | DenseNet/ResNet use 128³; all transformer and hybrid models use 96³. The **thesis Appendix B was wrong** and has been rewritten from the YAML files. | thesis Ch. 3/4, App. B, paper Table II |
| B4 augmentation | Flip, affine, noise, smoothing, bias field, gamma, intensity. **No elastic deformation or MixUp**, so slide 10 must drop both. | slide fix |
| Age confound | **None.** The groups are age-matched (CN 74.8 vs AD 74.7 y, p = 0.93) and sex-matched (p = 0.24), and an age+sex-only baseline is at chance. (`conference_paper/analysis/cohort_and_age_baseline.py`) | thesis Ch. 4/5/8, paper |
| Model size | Parameters and GFLOPs measured with the project's `build_model`. (`analysis/model_complexity.py`) | paper Table II |

**New issues found in the code (please check):**
- **Hospital name:** `scripts/make_compare_table.py` calls the hospital **"DhakaMed"**, but the thesis says **"Comfort Diagnostic Center"**. Use the correct name everywhere.
- **Swin–ViT control:** the same script notes that the Swin–ViT checkpoint "uses a custom cross-attn ViT absent from current code". The thesis and paper now say so. Re-running `binary_hybrid_swinvit.yaml` with the released code would make it an exact control.
- **Unreported configs:** configs exist for `binary_hybrid_cnnswin`, `binary_hybrid_resnetswin`, `3class_hybrid_cnnvit`, `3class_hybrid_cnnswin` and `3class_resnet`. **If any of these were run, send the `experiments/<run>_fold*/result.json` files.** They would fill the missing cells of the comparison.
- **Missing result files:** no `result.json` or prediction files are in the repo (the CNN–ViT folds were deleted). The approximate confusion counts in `conference_paper/analysis/derived_stats.py` can only be made exact from the remaining runs' `result.json` (`test_subject.confusion_matrix`).

## A. Facts to fill in (red placeholders in the PDF)

| # | Where | What to write |
|---|---|---|
| 1 | Ch. 4, Evaluation Protocol (*Model selection / early stopping*) | Where the validation subjects come from in each fold. If the **test fold** was used for early stopping, say so here **and** in §5 Threats to Validity. Note: your binary-CNN training curves peak at about 0.87–0.93 validation macro-F1, while the reported test-fold scores are 0.77/0.81. That gap suggests a separate validation split was used, but you must confirm it from the code. |
| 2 | Ch. 8, §8.4 *Ethics and data handling* | Approving body and reference number (or formal waiver) for the Comfort Diagnostic Center scans; whether consent was obtained or waived; who de-identified the scans; where they are stored. **If there was no approval, delete §8.4, Table 8.1 and slide 40.** |
| 3 | Ch. 4, Training Recipe (*Class weights / weighted sampling*) | Exactly which imbalance corrections each run used: weighted CE loss, `WeightedRandomSampler`, focal loss, or several at once. |
| 4 | Ch. 4, Curation | Whether scan labels are the **baseline** diagnosis or the **per-visit** diagnosis; the follow-up span; and whether the 180 subjects with 4 scans have 4 visits or include repeat scans from the same session. |
| 5 | Ch. 6, Budget table (2 cells + total) | Real total GPU-hours from your training logs. Total = 6,100 BDT + GPU-hours × 150. |
| 6 | Code and Data Availability (end of main text) | The real public GitHub URL. Also fix this repo's broken submodule (below). |

## B. Things to check and correct by hand

1. **Supervisor and examiner roles.**
   - The title page says A.S. Zaforullah Momtaz is *Co-supervisor*.
   - The approval page says *Member of the Committee (External)*.
   - The acknowledgements call him *examiner*.
   - Use whichever is officially correct, everywhere (thesis and slide 1).
2. **Per-subject aggregation.** Ch. 2 says subject scores average the *softmax outputs*; Ch. 4/5 say *logits*. Check the code and use one term throughout.
3. **Input sizes.** I made Ch. 3/4 match Appendix B (96³ for binary runs and the 3-class ViT, 128³ for the 3-class CNN and Swin). Confirm this against the YAML configs.
4. **Augmentations.** Slides list elastic deformation and 3D MixUp, but the thesis doesn't. Check the code and make them match.
5. **Pandey et al. (2025).** I aligned the text to the table (5,760 images; 82% train / 72% val). Open the paper and confirm.
6. **Akan et al. (2025).** I rewrote the paragraph to describe the paper actually cited (ViTranZheimer, video ViT, 98.6%).
   - If you meant to cite a *different* paper (one about GAN-synthesised MRI + Grad-CAM), add that paper to `references.bib` and restore the original paragraph with the new citation.
7. **ResNet folds 2 and 3 both = 0.449.** Check the saved predictions. Two identical values is unusual and may indicate a constant-prediction collapse.
8. **Questionnaire Q11** (resting-state vs task MRI) has nothing to do with structural MRI. Remove it if the form was never distributed.
9. **Re-export the Overleaf zip.** The old zip in this repo was older than the submitted PDF (the Declaration still said "Lecturer"). The revised source is now packaged as `Thesis_Report_Overleaf_revised.zip`. Upload that zip to Overleaf; the original zip is kept unchanged.

## C. Fix the code repository link

`Deep-Learning-for-Alzheimers-MRI` in this repo is a git submodule pointer (commit `19e6863`) with **no `.gitmodules`**, so it clones empty. Either:

```
git rm --cached Deep-Learning-for-Alzheimers-MRI
git submodule add https://github.com/<owner>/Deep-Learning-for-Alzheimers-MRI
```

or copy the code into this repo directly.

## D. Experiments (each one turns a "limitation" into a result)

Ordered by value per GPU-hour. After each one, update the matching table in Ch. 5 and the slides.

| # | Run | Why | Where to report |
|---|---|---|---|
| 1 | Confirm the validation split (A1). If the test fold was used, rerun `binary_cnn` and `binary_hybrid_cnnvit` with an inner validation split from the 4 training folds | Protects the "honest evaluation" claim | Tables 5.1/5.3 |
| 2 | `binary_vit`, `binary_swin` | Completes RQ1 (hybrid vs *each* single model) | Table 5.1 |
| 3 | `3class_hybrid_cnnvit` | The proposed model has no 3-class result | Table 5.2 |
| 4 | Age-only logistic regression (age, or age + sex) on the same folds: CPU, minutes | Measures the age confound | New row in Tables 5.1/5.2 |
| 5 | `binary_resnet_pretrained` with a min-epoch guard (e.g. no early stop before epoch 40) | Tests the "early-stopping artifact" claim | §5 Transfer Learning |
| 6 | `3class_vit` with only ONE imbalance correction | Tests the ViT-collapse explanation | §5 ViT section |
| 7 | Regenerate the binary-CNN ROC / calibration / histogram / gallery from all 5 folds (needs the checkpoints, i.e. a rerun) | Removes the "3 of 5 folds" caveat | Figs 5.3, 5.8 |
| 8 | Grad-CAM + IG for the **CNN–ViT** hybrid, plus % of attribution inside a brain mask | RQ2 has no maps for the proposed model | §5 Explainability |
| 9 | Repeat the binary CNN and CNN–ViT CV with seeds 0, 1, 2 | Enough power to detect a 1–2 point difference | §5 RQ1 |
| 10 | Skull-stripping ablation (SynthStrip or HD-BET), then atlas-ROI XAI (hippocampus etc.) | The only way to answer RQ2 properly | §5, §8 |

The paired test I used is a fold-wise paired t-test on macro-F1 (`scipy.stats.ttest_rel`). Add McNemar on pooled subject predictions once you have the prediction files.

## E. Slides

Apply `SLIDE_FIXES.md` in Canva. It gives exact replacement text for every slide.
