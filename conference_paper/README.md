# ICEEICT 2027 submission: conference paper

**Conference:** ICEEICT 2027, Military Institute of Science & Technology (MIST), Dhaka, 28–30 Jan 2027 (hybrid). <https://iceeict.mist.ac.bd/>

**Important dates (from web search; confirm on the site):**

| Event | Date |
|---|---|
| Paper submission | **25 Oct 2026** (extended) |
| Acceptance notification | 5 Dec 2026 |
| Camera-ready | 20 Dec 2026 |

Accepted papers are submitted to IEEE Xplore.

**Files:**
- `main.tex`: IEEE conference template (IEEEtran). Currently **5 pages** including references.
- `figures/`: the five figures used.
- `references.bib`: the thesis bibliography. Only cited entries are printed.
- `main.pdf`: compiled draft.

Build with:

```
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

Overleaf works too: upload this folder.

---

## Do these BEFORE submitting (in this order)

1. **ADNI publication rules — check today; this is the most time-critical item.**
   - The ADNI Data Use Agreement normally requires manuscripts to be sent to the **ADNI Data and Publications Committee (DPC)** for review before submission.
   - Check your DUA and the ADNI website for the current procedure and turnaround time. With a 25 Oct deadline you have very little slack.
   - Paste the official ADNI funding acknowledgement where the red TODO is in *Acknowledgment*. The investigator footnote is already included.
2. **Check the CFP page:** page limit (written for ≤ 6 pages), template, submission system (EDAS/CMT/EasyChair), and whether review is double-blind.
   - If double-blind, replace the author block with "Anonymous Authors" and remove the affiliation.
3. **Fill the 3 red `[TODO: …]` placeholders** (`grep -n authortodo main.tex`):
   - author e-mails and final author order (supervisors are usually listed last);
   - where the validation subjects for early stopping come from;
   - exactly which imbalance corrections each run used.
4. **Every author and both supervisors must approve** the final PDF and the author list before submission.
5. **Similarity check.** Much of the text overlaps your thesis. That is normally acceptable for an unpublished thesis, but run your institution's similarity check, and don't reuse sentences from the papers you cite.
6. **Camera-ready (if accepted):** convert the PDF with **IEEE PDF eXpress** using the conference ID given in the acceptance e-mail, and sign the IEEE copyright form.

## Deliberately left out of the paper

- **Hospital pilot (n = 8).** No ethics approval is documented, the labels are unvalidated, and the sample is too small to report. Reviewers would treat it as a weakness. Add it back only if you have approval, more cases, and AD cases.
- **Clinician opinion table.** It was not a structured study.
- **Questionnaire, CEP/CEA mapping, budget.** Thesis-only material.

## If you have GPU time before 25 Oct

Each of these turns a stated limitation into a result. Update Tables II/III and the *Limitations* list after each one:
1. `binary_vit` and `binary_swin` (completes the single-vs-hybrid comparison);
2. `3class_hybrid_cnnvit`;
3. age-only logistic-regression baseline (CPU, minutes): add as a table row;
4. repeat binary CNN and CNN–ViT with 3 seeds and re-run the paired test.

**Do not add anything you have not actually run.** The paper's strength is that every number in it is honest.
