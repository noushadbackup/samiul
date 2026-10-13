# Slide corrections: "Copy of Final Slides Correction.pdf"

The deck is a Canva export, so these edits must be made in Canva. Slide numbers are the numbers printed on the slides; the PDF page number is in brackets. Each row gives the current text and the exact replacement. Every replacement matches the revised thesis in `thesis_source/`.

---

## Table of contents (PDF pp. 2–4)

The listed slide numbers don't match the deck. Use these:

| Section | Correct slide |
|---|---|
| Motivation | 1 |
| Related Works | 2 |
| Research Gap | 4 |
| Research Questions | 5 |
| Dataset | 6 |
| Evaluation Protocol | 8 |
| Preprocessing | 9 |
| 3D Architectures Evaluated | 11 |
| Hybrid CNN + Transformer | 12 |
| Results: Binary CN vs AD | 13 |
| Results: 3-Class CN / MCI / AD | 14 |
| RQ1 Answer | 16 |
| RQ2 (Explainability) | 17 |
| Per-fold / CV results | 19 |
| Error cases | 22 |
| XAI Comparisons | 33 |
| Performance Diagnostics | 37 |
| Stakeholder Requirements | 39 |
| External Testing | 40 |
| Contributions | 41 |
| Limitation & Future Work | 42 |
| CEP / CEA Mapping | 43 |
| Conclusion | 45 |
| References | 46 |

Tip: if you add or remove slides, rebuild this table last.

---

## Slide 3 [p. 7]: Related Works table, Saoud & AlMarzouqi row

- **Limitations:** replace "Small dataset, slice level split, only 60% accuracy for 3-class"
  → **"Small dataset; very heavy 138-model ensemble; depends on ROI segmentation; only 60% for 3-class"**
- Reason: the paper uses one baseline 3D scan per subject, so it has no slice-level split.

## Slide 4 [p. 8]: Research Gap

- Change the citation "[2,4,5]" → **"[2,4]"** (Saoud [5] is not a leakage example).

## Slide 8 [p. 12]: Evaluation Protocol

- Replace "Each subject is tested once across 5 runs to prevent leakage"
  → **"Each subject is tested exactly once across the 5 folds, and never appears in its own training data"**
- Replace "Early stopping using validation Macro-F1"
  → **"Early stopping on validation Macro-F1 (validation subjects: \_\_\_)"**. Fill in the blank with where the validation subjects come from (see `AUTHORS_TODO.md`, item 1).
- Add a bullet: **"Majority-class baseline: 65.4% (binary), 52.2% (3-class)"**

## Slide 9 [p. 13]: Preprocessing

- Replace "Resize/pad to 128³"
  → **"Resize/pad to 96³ (binary, 3-class ViT) or 128³ (3-class CNN & Swin)"**

## Slide 10 [p. 14]: Augmentation

- "Mild elastic deformation" and "3D MixUp" are **not in the thesis**. Either:
  - remove them from the slide, or
  - if they really were used, add them to thesis §4.4. The two must match.

## Slide 11 [p. 15]: 3D Architectures Evaluated

- Replace "Hybrid CNN-ViT/CNN-Swin- feature fusion"
  → **"Hybrids: CNN–ViT (proposed) and Swin–ViT (no-CNN control), late-concat fusion"**

## Slide 13 [p. 17]: Results, Binary

- Add a table row in italics: **"Majority baseline (always CN) | 65.4 | 0.395"**
- Change the subtitle "Hybrid 3D CNN–ViT · leakage-free"
  → **"Hybrid 3D CNN–ViT: highest mean, statistically tied with DenseNet (p ≈ 0.54)"**

## Slide 14 [p. 18]: Results, 3-class

- Add a row: **"Majority baseline (always CN) | 52.2 | 0.229"**
- Change the subtitle "Swin · MCI is the bottleneck"
  → **"Swin ≈ CNN (tied, p ≈ 0.5); only +5.5 pts over majority baseline; MCI is the bottleneck"**
- Add a footnote: **"Proposed CNN–ViT not yet run on 3-class."**

## Slide 16 [p. 20]: RQ1 Answer

- Title: replace "RQ1 ANSWER: HYBRIDS HELP — BUT MODESTLY" → **"RQ1 ANSWER: NO DETECTABLE GAIN FROM HYBRIDISATION"**
- Replace all four bullets with:
  1. **"CNN–ViT has the highest mean (82.2%) but is statistically tied with DenseNet (81.0%): paired t = 0.67, p ≈ 0.54; wins 3 of 5 folds; 259 vs 255 subjects correct"**
  2. **"Swin–ViT (no CNN branch) is clearly weaker (0.66 macro-F1), so the CNN carries most of the signal"**
  3. **"Partly answered: standalone ViT/Swin not run on binary; hybrid not run on 3-class"**
  4. **"A well-trained 3D CNN is a very strong baseline at this data scale"**

## Slide 17 [p. 21]: RQ2

- Title: replace "ARE THE XAI MAPS ANATOMICALLY PLAUSIBLE?" → keep the question, and add the answer line **"Answer: not yet demonstrated"**
- Replace the bullets with:
  1. **"3D suite: Grad-CAM, Grad-CAM++, Score-CAM, IG, SmoothGrad, Occlusion, LIME, Attention rollout"**
  2. **"Methods disagree on the same subject (frontal vs central vs occipital/skull)"**
  3. **"Some maps fall on scalp, orbits, neck: volumes are not skull-stripped"**
  4. **"Next: skull-strip + atlas ROIs + sanity checks; maps for the proposed CNN–ViT"**

## Slide 18 [p. 22]: "Does it see AD biology?"

- This bar chart is the **Swin–ViT** model (16 AD subjects, one fold), not the CNN or CNN–ViT.
- Caption → **"Swin–ViT: Integrated-Gradients importance by thirds of the head, close to uniform (0.036–0.055); no medial peak"**
- Title → **"EXPLAINABILITY (RQ2): REGIONAL IMPORTANCE"**

## Slide 21 [p. 25]: Per-class P/R/F1

Binary precision and recall are swapped and the model isn't named. Use the hybrid CNN–ViT values from thesis Table 5.5:

| Row | Precision | Recall | F1 |
|---|---|---|---|
| Binary — CN (CNN–ViT) | 0.87 | 0.86 | 0.86 |
| Binary — AD (CNN–ViT) | **0.74** | **0.75** | 0.75 |

3-class rows: label them **"(Swin / CNN)"**.

## Slide 24 [p. 28]: Training dynamics, binary CNN

- Add to the caption: **"(folds 0–1 shown; logs for other folds not retained)"**
- Replace "smooth loss reduction and strong validation Macro-F1"
  → **"steady loss reduction; validation Macro-F1 reaches 0.75–0.9 but fluctuates ±0.1 between epochs"**

## Slide 27 [p. 31]: ViT training

- Replace "validation Macro-F1 stays near chance"
  → **"validation Macro-F1 stays at 0.1–0.25; the model never predicts CN and scores 28.6%, below the 52.2% majority baseline"**

## Slides 31–32 [pp. 35–36]: Error cases / confidence

- Add to both captions: **"(3 of 5 folds, 189 subjects)"**
- Slide 31 text is correct. Optionally add: **"≈14 of 22 misclassified CN subjects have P(AD) > 0.9"**

## Slide 37 [p. 41]: Performance Diagnostics

- The caption wrongly says "LIME Region-Based Explanation…" (copy-paste error).
- Replace it with **"DenseNet121 binary: confusion, ROC (AUC 0.82), precision–recall, calibration (3 of 5 folds, 189 subjects)"**

## Slide 38 [p. 42]: 3-class diagnostics

- Caption → **"DenseNet121 3-class: one-vs-rest AUC CN 0.69 · MCI 0.66 · AD 0.77"**

## Slide 39 [p. 43]: Stakeholder Requirements

- Title → **"INFORMAL CLINICIAN FEEDBACK"**
- Add a footnote: **"Unstructured opinions; not a blinded reader study and not evidence of clinical reliability."**

## Slide 40 [p. 44]: External Testing

Add three lines under the table:
- **"n = 8 (4 CN, 4 MCI, no AD): best 6/8, 95% CI ≈ 41–93%"**
- **"CN ≈ 35 y vs MCI ≈ 68 y: AUC 0.94 is age-confounded"**
- **"Ethics: [approval body / ref no. / consent or waiver]"**: fill in exactly as in the thesis (see `AUTHORS_TODO.md`, item 2).

## Slide 41 [p. 45]: Contributions

- Replace "Validated predictions with Explainable AI (Grad-CAM, IG, SmoothGrad, Attention)"
  → **"Built an end-to-end 3D XAI pipeline and showed its current limits (method disagreement, non-brain attribution)"**
- Replace "Compared five 3D architectures with identical preprocessing and evaluation"
  → **"Compared 3D CNN, pretrained ResNet, ViT, Swin and two hybrids under one subject-level protocol, with paired statistics"**

## Slide 42 [p. 46]: Limitations & Future Work

Add these limitations:
- **"Hybrid not run on 3-class; standalone ViT/Swin not run on binary"**
- **"Single seed; differences of 1–2 pts not significant"**
- **"No skull-stripping; XAI maps not anatomically conclusive"**
- **"AD older than CN: possible age confound"**

Add these future-work items:
- **"Complete the model grid + 3-seed CV"**
- **"Skull-strip + atlas-ROI XAI for CNN–ViT"**
- **"Age-only baseline"**

## Slide 43 [p. 47]: CEP mapping, P6

- Replace "healthcare professionals and patients to evaluate model"
  → **"clinicians gave informal feedback; a diagnostic centre supplied pilot data"**

## Slide 45 [p. 49]: Conclusion

Replace the bullets with:
1. **"CNN–ViT had the highest binary mean (82.2%) but is statistically tied with a 3D CNN (81.0%)"**
2. **"Leakage-free, subject-level 5-fold evaluation with majority baselines and paired tests"**
3. **"3-class ≈ 58%: MCI is the bottleneck; only +5.5 pts over majority baseline"**
4. **"3D XAI pipeline built; anatomical grounding not yet demonstrated"**

## Slide 46 [p. 50]: References

Fix the typos copied from the PDF hyphenation:
- "visiontransformers" → "vision transformers"
- "analy-sis" → "analysis"
- "gener-ated" → "generated"

Also capitalise proper nouns: Alzheimer's, MRI, ROIs, 3D, CNN, AI.

## Title slide [p. 1]

- Write the third presenter's name as **"Md. Sarjil Hasan"**, matching the thesis.
