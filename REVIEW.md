# Supervisor Review: "Alzheimer's Detection Using 3D CNN–ViT With Explainable AI"

**Reviewed:** `Thesis_Final_Report (1).pdf` (105 pp.), the Overleaf source in `Thesis_Report_Overleaf .zip` (8 chapters, 2 appendices, 45 references, 43 figures), and `Copy of Final Slides Correction.pdf` (51 slides).
**Not reviewable:** the code. `Deep-Learning-for-Alzheimers-MRI` is a git submodule pointer (commit `19e6863`) with no `.gitmodules`. It is empty here, and the thesis's own code link is a placeholder (`github.com/your-username/alzheimers-3d-cnn-vit`). Every point below that depends on the code is marked **[verify in code]**.

---

## 1. What the project is

- **Task:** classify structural MRI on the ADNI dataset as CN vs AD (binary), and as CN vs MCI vs AD (3-class).
- **Data:** ADNI GO/2/3, 3T, T1 MPRAGE. 1,132 scans from 395 subjects (CN 206, MCI 80, AD 109). Mean 2.9 scans per subject.
- **Protocol:** subject-level stratified 5-fold cross-validation, seed 42. Scan predictions are averaged into one prediction per subject. Macro-F1 is the primary metric.
- **Models:** 3D DenseNet-121 (trained from scratch), MedicalNet 3D ResNet-18, 3D ViT (384-d, 6 layers), SwinUNETR encoder, and the proposed hybrid DenseNet+ViT with late-concat fusion (1024+384 → 1408 → linear). A Swin+ViT hybrid also appears in the results.
- **Headline results:**
  - Binary: hybrid 82.2 ± 5.7% accuracy (macro-F1 0.802) vs DenseNet 81.0% (0.788).
  - 3-class: Swin 57.7%, DenseNet 57.2%, ViT 28.6%.
- **Explainability:** Grad-CAM, Grad-CAM++, Score-CAM, Integrated Gradients, SmoothGrad, Occlusion, LIME, and attention rollout.
- **External pilot:** 8 hospital scans (4 CN, 4 MCI) from Comfort Diagnostic Center.

**Overall verdict.** The framing is the thesis's real strength. Leakage-free, subject-level evaluation with honest negative results is more mature than most undergraduate work in this area. The internal arithmetic is sound: every per-class table reconciles exactly with its confusion counts. The weaknesses are in what the experiments actually support. The proposed model has no 3-class result. Its "win" is not statistically distinguishable from the baseline. The explainability claims are stronger than the figures show. Several figures, captions and citations contradict the text. All of this is fixable, and most of it is editing rather than new experiments.

---

## 2. Critical issues (fix before submission or defense)

### C1. The proposed hybrid was never run on the 3-class task, yet the thesis credits it with a 3-class number
- Table 5.x "This work vs literature" (`chapter5.tex`, `tab:compare_lit`) lists **"This work (Hybrid 3D CNN–ViT) … 3-class 57.7%"**. The 57.7% is **Swin**. The 3-class table has no hybrid row.
- Appendix B lists no `3class_hybrid_*` run either.
- **Fix:** either run `3class_hybrid_cnnvit`, or change that row to "This work (best model: Swin)" and state plainly that the hybrid was evaluated on the binary task only.

### C2. The "experimental grid" cannot answer RQ1 as stated
- RQ1 asks whether the hybrid beats single CNN *or Transformer* models. On the binary task, **no standalone ViT and no standalone Swin were run**. Only DenseNet and ResNet were.
- The thesis still says the hybrid "beats every standalone configuration tried" (§5 RQ answers). Slide 16 also says "Transformer-only models are the weakest and least stable", which has no binary evidence.
- The Swin+ViT hybrid is never described in Chapter 4, which lists 5 models. It appears for the first time in the results.
- Slide 16 claims "performance depends on the fusion strategy used". Only late-concat was ever evaluated. Cross-attention is described in Ch. 2–4 but never reported.
- **Minimum fix:** add `binary_vit` and `binary_swin` runs, which are cheap with the existing configs. Otherwise, rewrite RQ1 to "does adding a ViT branch to a CNN help?" and remove the transformer-only and fusion-strategy claims.

### C3. The hybrid's advantage is not statistically supported
- Per-fold macro-F1 differences between the hybrid and DenseNet are −0.052, +0.047, +0.065, −0.013 and +0.023. The mean is +0.014 (SD 0.047). A paired t-test gives **t = 0.67 with df = 4, so p ≈ 0.5**. The hybrid wins **3 of 5 folds**.
- On pooled subjects the hybrid gets **259/315 correct vs 255/315**, a difference of 4 subjects.
- The text calls this "a small, *consistent* edge" (§5, Ch. 8). It is not consistent. The honest finding is **"no detectable difference"**.
- Rewrite the claim, and report a paired test (fold-wise t-test or Wilcoxon, plus McNemar on pooled subjects).
- Better: repeat the CV with 3 seeds. One seed and 5 folds cannot separate a 1-point effect.

### C4. Possible test-fold reuse for early stopping / model selection [verify in code]
- Early stopping and checkpoint selection use "validation subject-level macro-F1". The 5-fold diagram on slide 8 shows only train (green) and test (orange). There is no validation block.
- If the held-out fold is both the early-stopping signal and the reported score, the results are **optimistically biased**. The validation curves are very noisy (slides 24–27 swing ±0.1 between epochs), so taking the best epoch can add several points.
- This would undercut the thesis's central "honest evaluation" claim.
- **Fix:** take an inner validation split from the 4 training folds (nested CV), or train for a fixed number of epochs. Then state the procedure explicitly in §4.

### C5. Explainability claims (RQ2) are stronger than the figures support
- **Wrong model.** The text says "the winning hybrid checkpoint was not retained", so the attributions use DenseNet. But `xai_roi_binary.png` (Fig. "Group-averaged importance") is titled **`binary_hybrid_swinvit`**. That is the 70% Swin+ViT model, not DenseNet. The "Hybrid explainability" figure is also Swin+ViT, not the proposed CNN+ViT. **The proposed model has no explanation maps at all.**
- **Wrong reading.** The text says importance concentrates "in the medial and central regions". In that figure, *Mid* is the **lowest** bar on the left–right axis. Posterior and inferior thirds are highest. All 9 bars fall within 0.036–0.055, which is close to uniform. It covers only 16 AD subjects (one fold).
- **Methods disagree** on `135_S_4863` (`xai_panel_binary_cnn.png`):
  - Grad-CAM: **frontal**
  - Grad-CAM++ and Score-CAM: a central blob
  - Occlusion: **occipital and skull**
  - LIME: partly the **scalp**
  - Integrated Gradients: almost empty
  
  This contradicts the claim that "agreement across methods is strong evidence that the models key on biology". It is *disagreement*. Because the volumes are not skull-stripped, skull, scalp and neck signal remain a plausible shortcut that the thesis cannot rule out.
- **Fix:**
  1. Rewrite RQ2's answer as "inconclusive / partially supported".
  2. Compute maps for the actual CNN+ViT, by retraining one fold if needed.
  3. Report a quantitative check: fraction of attribution inside a brain mask, a deletion/insertion curve, or a randomization sanity check (Adebayo et al., 2018).
  4. Ideally, run the skull-stripping ablation (HD-BET or SynthStrip) and see whether accuracy holds.

### C6. Binary CNN diagnostic figures come from 3 of 5 folds, which the captions don't disclose
- `res_perf_binary_cnn.png` is titled **"189 subjects, 3 folds"**. Its confusion matrix (102/22/19/46) gives 78.3% accuracy and AUC 0.823. That is not the 81.0% / 315-subject result in the tables.
- The error histogram (n = 124 CN + 65 AD) and the t-SNE come from the same partial set.
- The caption "Per-fold and pooled ROC…" implies the full CV.
- **Fix:** regenerate the figures from all 5 folds, or caption them honestly ("3 of 5 folds; checkpoints for folds 4–5 not retained").

### C7. The error-analysis text contradicts its own figure
- The text says "most binary errors occur at low confidence … the model is rarely confidently wrong".
- `err_binary_cnn_hist.png` shows **about 14 of the 22 misclassified CN subjects at P(AD) > 0.9**, including about 12 in the 0.95–1.0 bin. It also shows 7 AD subjects at P(AD) < 0.1.
- Slide 31 correctly says the model "occasionally predicts CN subjects as AD with very high confidence".
- The calibration plot is clearly over-confident at the top bins.
- Rewrite the paragraph. Investigate those high-confidence CN errors: check age, scanner and site, and look for MCI/AD conversion at later visits, which would mean the labels themselves may be wrong.

### C8. The ViT "near-chance" interpretation is wrong, and the collapse looks like a pipeline issue
- Majority-class accuracy is **52.2%** for 3-class (206/395) and **65.4%** for binary (206/315). Chance is not 33%.
- The 3-class ViT's 28.6% is far *below* trivial. Its confusion matrix (slide 23) shows it **never predicts CN** and splits everyone into MCI and AD.
- That pattern points to over-correction for class imbalance, not just "data-hungry ViT". The thesis uses class weighting *and* weighted sampling *and* focal loss, and stacking them pushes predictions toward the minority classes. Training loss barely moves (0.76 → 0.64) and the run early-stops around epoch 35 of 80.
- **[verify in code]** whether the loss weights and the `WeightedRandomSampler` are both active.
- **Also:**
  - Report the majority-class baseline in every results table.
  - 3-class Swin (57.7%) is only **+5.5 points above always predicting CN**. Say so.
  - Pretrained ResNet binary (69.8%) is only +4.4 above the majority baseline.

### C9. External hospital validation: ethics, label validity and placement
- The text uses real patient scans from Comfort Diagnostic Center. There is **no statement of ethics approval, consent or waiver, data agreement, or de-identification for these scans**.
- Ch. 7 then states that all data come from "ethically approved datasets", which is incorrect for this subset. At a defense this is the most dangerous single point.
- **Fix:** add an ethics statement (institutional approval or waiver, anonymization procedure, who held the data), or remove the pilot.
- **Label validity:** "MCI" is a clinical and neuropsychological diagnosis, and cannot be derived from a radiology report. The "CN" group has a mean age of about 35 against about 68 for MCI. The thesis already flags the age confound. The labels should also be described as unvalidated, not just "weak".
- n = 8: a 6/8 result has a 95% CI of 41–93%. Present it as a feasibility note, not as a results table with AUCs. A ViT AUC of 0.12 means the ranking is inverted, which is meaningless at n = 8.
- **Clinician feedback table (§3, slide 39).** Four doctors rated the system "Reliable", but no protocol is described: what they were shown, how many cases, and whether they were blinded. The external test then failed. Either document the procedure or soften this to "informal feedback". Do not use it as evidence of reliability.

---

## 3. Major issues

1. **Input size contradiction.** Ch. 3–4 say CNN/ResNet run at 128³ and ViT/Swin/hybrid at 96³. Appendix B says *all binary runs* use 96³, 3-class CNN and Swin use 128³, and ViT uses 96³. Slide 9 says "Resize/pad to 128³". Pick the truth from the configs and make every mention agree. This also matters for fairness: the 3-class Swin at 128³ vs ViT at 96³ is not like-for-like.
2. **"One shared recipe" is not true.** The two tasks use different losses, epochs, warmup, patience and weight decay (Appendix B). Say "one recipe per task".
3. **Augmentation mismatch.** Slide 10 lists "mild elastic deformation" and "3D MixUp". Neither appears in the thesis. Either they were used (add them to §4.4) or the slide is wrong.
4. **"Single site" is factually wrong.** §5 Threats and §8 Limitations say "single-site ADNI". ADNI is **multi-site, multi-scanner**. Say "single-cohort / single-source". Ch. 4 itself says "collected across multiple sites".
5. **The ResNet "early-stopping artifact" is asserted, not shown.** Two folds both at exactly 0.449 is unusual. Include the ResNet per-fold curves. Better, rerun with a min-epoch guard (a one-line change) and report the result. That turns a speculation into a finding.
6. **Label definition and longitudinal scans [verify in code].**
   - State whether each scan's label is the subject's baseline group or the diagnosis at that visit. CN and MCI subjects can convert over a 4-visit series.
   - 180 subjects have exactly 4 scans. Check whether these are repeat acquisitions within one session (MPRAGE + MPRAGE-repeat) rather than different time points.
   - Report the median follow-up span.
7. **Age confound in ADNI too.** In `ds_stats.png`, AD peaks around 76 years and CN around 70. Add an **age-only (or age + sex) logistic-regression baseline**. If it reaches about 65–70% on CN vs AD, the deep models' added value is clearer. Report it either way.
8. **The std convention changes.** The thesis reports population SD (ddof = 0, e.g. hybrid 0.062; sample SD would be 0.069). State which one is used. Better, add 95% CIs.
9. **No parameter or compute comparison.** The hybrid has DenseNet plus ViT parameters. Report parameters, FLOPs and training time per model, since "efficiency" is claimed in §1.6.3 and Ch. 7.

---

## 4. Literature review and citations

- **Hard-coded reference numbers are wrong in the compiled PDF.**
  - The literature comparison table cites "[4,6,7,8]" for slice-based ViT/CNN studies. In the bibliography those resolve to AlSaeed, **Bäckström (a 3D subject-level CNN)**, **Braak & Braak 1991 (neuropathology)** and Bravo-Ortiz (a review).
  - "ROI 3D ViT ensemble [11]" resolves to **Chen et al., Med3D**. Saoud & AlMarzouqi is [37].
  - **Fix:** replace the literals with `\cite{...}`.
- **Saoud & AlMarzouqi (2024) is contradictory.** The Ch. 2 table lists "slice-level split" as a limitation. The research-gap section and §5 call it "the one clearly subject-level / genuinely leakage-aware comparator". Slide 8 also cites it [5] as a leakage example. Read the paper and choose one.
- **Pandey et al. (2025) is inconsistent.** The text says 576 images and about 71%. The table and slide say 5,760 images, train 82% and val 72%.
- **Akan et al. (2025) has a citation/content mismatch [verify].** The bib entry is "Leveraging *Video Vision Transformer* for AD diagnosis from 3D brain MRI" (arXiv 2501.15733). The paragraph describes a GAN-synthesis + Grad-CAM framework. This looks like the wrong paper.
- **The summary says "reviewed twelve studies".** The comparison table has 6 entries, and 2 of those (Wen, Yagis) are not in the prose review. Align them.
- **Essential leakage-free 3D baselines are missing:** Wen et al. is cited but its subject-level numbers are not used in Table compare_lit. Add a few strong subject-level 3D CNN results (e.g. Wen 2020's 3D-subject CNN; Liu et al. 2018/2020; Korolev et al. 2017). A comparison against only one "honest" study is thin.

---

## 5. Front matter, Ch. 6–7, appendices

- **Source and PDF differ.** In the Overleaf zip the Declaration says "Lecturer". The PDF says "Assistant Professor". The zip is out of date; re-export it.
- **Role inconsistency.** The title page lists A.S. Zaforullah Momtaz as *Co-supervisor*. The approval page lists him as *External member*. The acknowledgements call him the *examiner*.
- **Acknowledgements** are written in the first person singular ("I", "my") for a three-author thesis.
- **Code availability** is a placeholder URL. Publish the repo (the submodule here is broken) and put the real link in both the PDF and the slides.
- **Ch. 7 standards are mislabeled.**
  - IEEE 829 is a test-documentation standard, not a lifecycle model.
  - "IEEE 829 (ISO/IEC 9126)" and "IEEE 829 (ISO/IEC 25010)" conflate unrelated standards.
  - IEEE 11073 (device communication) and DICOM are not used: the data are NIfTI.
  - "EU AI Risk Management Guidelines" should be the EU AI Act.
  - "Avoiding model bias through balanced datasets" contradicts the stated imbalance.
  - "Compressing MRI volumes", "encrypted during use" and cloud carbon-neutrality are unsupported claims.
  - The K6 bullet is in the future tense, and K8 is truncated mid-sentence.
- **CEP P6** says patients evaluated the model. They did not.
- **Budget.** 20 GPU-hours at 150 BDT/hr is implausible for 7 runs × 5 folds × up to 100 epochs of 3D training, and the hardware was a local RTX 5060 Ti that isn't costed. Use realistic GPU-hours from the logs.
- **Appendix A questionnaire.**
  - Numbering skips items 2–3 and 12.
  - Q11 (resting-state vs task fMRI) is irrelevant to structural MRI.
  - The thesis title on the questionnaire differs from the real title.
  - The "completed questionnaire" answers a *different* set of 11 questions than the form shown.
  - No aggregate responses are reported.
- **NFR1** sets an accuracy target of "high-70s to low-80s" that matches the achieved results exactly. It reads as written after the fact. Either justify it from the literature (e.g. Wen 2020's 85–88%) or drop the number.
- **Wording.** Ch. 2 averages "softmax outputs" per subject; Ch. 4/5 average "logits". Use one.

---

## 6. Slide deck: specific fixes

| Slide | Problem |
|---|---|
| ToC (2–4) | Slide numbers don't match the deck (e.g. Stakeholder is listed as 43 but is on 39; Conclusion 47 vs 45; References 48 vs 46). |
| 8 | Cites [5] Saoud as a leakage example, which conflicts with the report. "Each subject is tested once across 5 runs *to prevent leakage*" is misphrased: testing each subject once is a CV property, not the leakage guard. |
| 9 | "Resize/pad to 128³" conflicts with Appendix B (binary at 96³). |
| 10 | Elastic deformation and 3D MixUp are not in the thesis. |
| 11 | Lists a "CNN-Swin" hybrid. The result is actually Swin-ViT. |
| 16 | "Depends on fusion strategy" (only one strategy was tested). "Significantly reduces Macro-F1" (no test, and confounded: two components change). "Transformer-only weakest" (not tested on binary). |
| 17 | Lists LIME but not attention rollout. Slide 41 lists "Attention". Be consistent. |
| 18 | The ROI plot is the Swin-ViT model, and its bars do not show a medial or central peak. |
| 21 | Binary AD precision and recall are swapped relative to the report (report: hybrid P 0.739 / R 0.752; CNN P 0.706 / R 0.771). Say which model the row is. |
| 37 | Titled "Performance Diagnostics" but captioned "LIME Region-Based Explanation" (copy-paste). The figure is 3 folds / 189 subjects; say so. |
| 40 | External testing needs an ethics line, and n = 8 with a CI. |
| 42 | Omits the most important limitations: no 3-class hybrid, incomplete grid, possible validation reuse, no skull-stripping. |
| 45 | "Fair comparison of CNN, Transformer, and Hybrid": not complete (see C2). |

---

## 7. Questions the committee is likely to ask, and the answers you need

1. *"Where is your proposed model on the 3-class task?"* → C1.
2. *"Is 82.2 vs 81.0 significant?"* → C3. Answer honestly: no, p ≈ 0.5.
3. *"Which data decided when to stop training?"* → C4. Know the exact answer from the code.
4. *"Your Grad-CAM highlights the frontal lobe and occlusion highlights the back of the skull. How is that the hippocampus?"* → C5.
5. *"What does a model that always says CN score?"* → 65.4% binary, 52.2% 3-class (C8).
6. *"Did the hospital patients consent? Who approved it?"* → C9.
7. *"How can a radiology report give you an MCI label?"* → C9.
8. *"Could the model be using age or the skull rather than disease?"* → Major 7 and C5.

---

## 8. Prioritized action plan

**A. Text-only fixes (about 1–2 days, no GPU):**
- C1 row fix, C3 wording plus a paired test, C6 and C7 captions and text.
- C8 baselines and wording, C9 ethics statement.
- "single site" → "single cohort"; input-size consistency; citation literals.
- Saoud, Pandey and Akan consistency; front-matter roles; Ch. 7 standards.
- Slide fixes in §6.

**B. Cheap experiments (a few GPU-days on the RTX 5060 Ti), roughly in order of value:**
1. Confirm or fix validation-fold handling (C4). If it was the test fold, rerun binary DenseNet and the hybrid with an inner validation split.
2. `binary_vit` and `binary_swin` standalone runs (completes RQ1).
3. `3class_hybrid_cnnvit` (completes the proposed model).
4. ResNet with a min-epoch guard (resolves the "artifact" claim).
5. 3-class ViT with a single imbalance correction instead of three stacked (C8).
6. Age-only baseline (minutes on a CPU).
7. CNN+ViT attribution maps, plus a brain-mask attribution fraction.

**C. If time allows:** skull-stripping ablation (SynthStrip or HD-BET), 3-seed repeats, and OASIS-3 or AIBL as a genuine external test set (3D T1, research-grade labels).

---

## 9. What is genuinely good and worth defending

- Subject-level splitting, asserted in code, with seeded split files.
- Per-fold reporting, macro-F1 as the primary metric, and subject-level aggregation.
- Negative results are reported, not hidden (ViT collapse, ResNet instability, failed external transfer).
- An explicit "honesty note" about no skull-stripping.
- Internal numerical consistency: every pooled per-class precision, recall and support reconciles exactly with the accuracies reported.
- A clear threats-to-validity section that just needs to be made complete.

The thesis's identity is "honest evaluation". The fixes above mostly remove places where the text slipped back into the over-claiming it criticizes. Fix those and the work is well defended.
